#!/usr/bin/env bash
# Restore a backup into staging or prod. Destroys the current data of that environment.
#
#   deploy/restore.sh staging                         list available dumps
#   deploy/restore.sh staging quiz-20261003-023000-nightly.dump
#
# Refuses a dump taken on a newer release than the deployed one, before touching anything. Otherwise it stops
# the app, takes a safety dump (quiz-<date>-<time>-pre-restore.dump), replaces the whole schema with the dump
# in one transaction (if that fails, the current data stays as it was), migrates it to the deployed release
# and starts the app again.
#
# Once you confirm, the restore runs on its own and logs to <QUIZ_ROOT>/<env>/restore-<date>-<time>.log; the
# terminal only follows that log, so a dropped SSH session, Ctrl-C or killing the script can't stop it half-way.
# If it fails, it checks whether the dump was loaded and says so: loaded, it migrates it before starting the
# app, and never starts the app on a schema the deployed release doesn't expect.
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
[[ -n ${RESTORE_CONFIRMED:-} ]] || log "$file is at revision $revision; $env runs $tag"

lock=$dir/restore.lock
if [[ -z ${RESTORE_CONFIRMED:-} ]]; then
  [[ ! -d $lock ]] || die "a restore is already running (tail -f $dir/restore-*.log); if none is (ps aux | grep restore), rmdir $lock"
  read -r -p "This replaces all $env data with $file. Type '$env' to continue: " answer
  [[ $answer == "$env" ]] || die "aborted"
  logfile=$dir/restore-$(TZ=Europe/Madrid date +%Y%m%d-%H%M%S).log
  set -m # its own process group: a signal to this terminal's group doesn't reach it
  RESTORE_CONFIRMED=1 nohup bash "$0" "$env" "$file" </dev/null >"$logfile" 2>&1 &
  worker=$!
  set +m
  log "running on its own: a dropped connection or Ctrl-C only stops this view. Log: $logfile"
  tail -n +1 -f "$logfile" &
  watcher=$!
  # Stops the view when the restore ends or when this script is killed, so it never outlives both.
  (while kill -0 $$ 2>/dev/null && kill -0 "$worker" 2>/dev/null; do sleep 1; done; sleep 1; kill "$watcher" 2>/dev/null) &
  status=0
  wait "$worker" || status=$?
  sleep 1
  kill "$watcher" 2>/dev/null || true
  exit "$status"
fi
mkdir "$lock" 2>/dev/null || die "a restore is already running; if none is, rmdir $lock"

sql() { compose exec -T db psql -X -tAq -U postgres -d quiz -c "$1" </dev/null; }
start_app() {
  log "starting api and scheduler"
  compose up -d --wait --wait-timeout 90 api scheduler
}
migrate() {
  log "migrating"
  IFS_DATABASE_URL="postgresql+psycopg://migrator:${MIGRATOR_PASSWORD}@db:5432/quiz" \
    compose run --rm --no-deps -e IFS_DATABASE_URL api alembic upgrade head </dev/null
}
marker='' stopped=''
on_exit() {
  local status=$?
  trap - EXIT
  echo "restore: FAILED, ${stopped:-see above}" >&2
  # A restore whose client died can still be running, and committing, inside the db container.
  for _ in $(seq 1 600); do
    [[ -z $(sql "SELECT 1 FROM pg_stat_activity WHERE application_name = 'quiz-restore'" 2>/dev/null) ]] && break
    sleep 1
  done
  if ! loaded=$(sql "SELECT obj_description('public'::regnamespace, 'pg_namespace')" 2>/dev/null); then
    echo "restore: couldn't reach the database to tell whether $file was loaded; the app stays stopped." >&2
    echo "restore: once it's reachable, run deploy/deploy.sh $env $tag: it migrates if needed and starts the app" >&2
  elif [[ -z $marker || $loaded != "$marker" ]]; then
    echo "restore: $file was not loaded: the data is as it was" >&2
    start_app || true
  elif migrate; then
    echo "restore: $file was loaded and migrated to $tag" >&2
    start_app || true
  else
    echo "restore: the database holds $file, not migrated to $tag; the app stays stopped. Fix the error above," >&2
    echo "restore: then run deploy/deploy.sh $env $tag (it migrates and starts the app), or restore $safety" >&2
  fi
  rmdir "$lock" 2>/dev/null || true
  exit "$status"
}
trap on_exit EXIT
trap 'stopped="stopped by SIGTERM"; exit 143' TERM
trap 'stopped="stopped by SIGINT"; exit 130' INT

compose stop api scheduler
safety=$(compose exec -T backup /bin/sh /quiz/backup.sh once pre-restore </dev/null | sed -n 's|^backup: /backups/||p')
[[ $safety =~ ^[A-Za-z0-9._-]+\.dump$ ]] || die "the safety dump didn't complete"
log "safety dump: $safety"
marker="restored from $file over $safety"

# One transaction: drop the schema, so nothing a newer release created survives, and rebuild it from the dump
# as migrator. The dump brings its own grants and default privileges; roles.sql re-applies the role set-up.
# COMMIT is only sent once pg_restore has read the whole dump; without it psql rolls everything back. The
# schema comment is how a failure afterwards tells whether this transaction committed.
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
  echo "COMMENT ON SCHEMA public IS '$marker';"
  echo "COMMIT;"
} | compose exec -T -e PGAPPNAME=quiz-restore db psql -X -q -o /dev/null -v ON_ERROR_STOP=1 -U postgres -d quiz

migrate
trap 'rmdir "$lock" 2>/dev/null || true' EXIT
start_app
log "$env restored from $file"
