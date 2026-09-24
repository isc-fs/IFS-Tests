#!/usr/bin/env bash
# Restore a backup into staging or prod. Destroys the current data of that environment.
#
#   deploy/restore.sh staging                         list available dumps
#   deploy/restore.sh staging quiz-20261003-023000-nightly.dump
#
# Refuses a dump taken on a newer release than the deployed one, before touching anything. Otherwise it stops
# the app, takes a safety dump (quiz-<date>-<time>-pre-restore.dump), replaces the whole schema with the dump
# in one transaction (if that fails, the current data stays as it was), migrates it to the deployed release
# and starts the app again. The app is started again whatever happens.
#
# To rehearse a prod restore, copy a prod dump into the staging backups volume and restore it there.
set -euo pipefail

die() { echo "restore: $*" >&2; exit 1; }
log() { echo "restore: $*"; }

[[ $# -ge 1 ]] || die "usage: $0 <staging|prod> [dump-file]"
env=$1 file=${2:-}
[[ $env =~ ^(staging|prod)$ ]] || die "environment must be staging or prod"

repo=$(cd "$(dirname "$0")/.." && pwd)
dir=${QUIZ_ROOT:-/srv/quiz}/$env
envfile=$dir/.env
[[ -f $envfile ]] || die "missing $envfile"
[[ $(stat -c %a "$envfile" 2>/dev/null || stat -f %Lp "$envfile") == 600 ]] || die "$envfile must be chmod 600"
set -a
# shellcheck source=/dev/null
. "$envfile"
set +a
[[ $QUIZ_ENV == "$env" ]] || die "QUIZ_ENV in $envfile is '$QUIZ_ENV', expected '$env'"
tag=$(cat "$dir/deployed-tag")

compose() {
  IMAGE_TAG=$tag docker compose --project-directory "$repo/deploy" -f "$repo/deploy/compose.yaml" \
    --env-file "$envfile" "$@"
}

if [[ -z $file ]]; then
  compose exec -T backup ls -lh /backups
  exit 0
fi
[[ $file =~ ^[A-Za-z0-9._-]+\.dump$ ]] || die "invalid dump file name"
compose exec -T backup test -f "/backups/$file" </dev/null || die "no dump named $file in the backups volume"

revision=$(compose exec -T backup pg_restore --data-only --table=alembic_version -f - "/backups/$file" </dev/null |
  awk '/^COPY public.alembic_version /{getline; print; exit}') || die "can't read $file: is it complete?"
[[ $revision =~ ^[0-9A-Za-z_]+$ ]] || die "can't read the schema revision of $file"
if ! out=$(compose run --rm --no-deps api alembic show "$revision" </dev/null 2>&1); then
  grep -q "Can't locate revision" <<<"$out" || die "can't check revision $revision with $tag: $out"
  die "$file is at revision $revision, which $tag doesn't know: deploy a release that has it first. Nothing changed"
fi
log "$file is at revision $revision; $env runs $tag"

read -r -p "This replaces all $env data with $file. Type '$env' to continue: " answer
[[ $answer == "$env" ]] || die "aborted"

start_app() {
  log "starting api and scheduler"
  compose up -d --wait --wait-timeout 90 api scheduler
}
on_exit() {
  local status=$?
  trap - EXIT
  echo "restore: FAILED, see above" >&2
  start_app || true
  exit "$status"
}
trap on_exit EXIT

compose stop api scheduler
compose exec -T backup /bin/sh /quiz/backup.sh once pre-restore </dev/null

# One transaction: drop the schema, so nothing a newer release created survives, and rebuild it from the dump
# as migrator. The dump brings its own grants and default privileges; roles.sql re-applies the role set-up.
# COMMIT is only sent once pg_restore has read the whole dump; without it psql rolls everything back.
log "restoring $file"
{
  echo "BEGIN; SET client_min_messages = warning;"
  echo "DROP SCHEMA public CASCADE;"
  echo "CREATE SCHEMA public AUTHORIZATION migrator;"
  echo "GRANT USAGE ON SCHEMA public TO PUBLIC;" # as in a new database
  echo "SET ROLE migrator;"
  compose exec -T backup pg_restore --no-owner -f - "/backups/$file" </dev/null || exit 1
  echo "RESET ROLE;"
  cat "$repo/deploy/db/roles.sql"
  echo "COMMIT;"
} | compose exec -T db psql -X -q -o /dev/null -v ON_ERROR_STOP=1 -U postgres -d quiz

log "migrating"
export IFS_DATABASE_URL="postgresql+psycopg://migrator:${MIGRATOR_PASSWORD}@db:5432/quiz"
compose run --rm --no-deps -e IFS_DATABASE_URL api alembic upgrade head </dev/null
unset IFS_DATABASE_URL

trap - EXIT
start_app
log "$env restored from $file"
