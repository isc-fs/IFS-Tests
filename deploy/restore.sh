#!/usr/bin/env bash
# Restore a backup into staging or prod. Destroys the current data of that environment.
#
#   deploy/restore.sh staging                         list available dumps
#   deploy/restore.sh staging quiz-20261003-023000-nightly.dump
#
# To rehearse a prod restore, copy a prod dump into the staging backups volume and restore it there.
set -euo pipefail

die() { echo "restore: $*" >&2; exit 1; }

[[ $# -ge 1 ]] || die "usage: $0 <staging|prod> [dump-file]"
env=$1 file=${2:-}
[[ $env =~ ^(staging|prod)$ ]] || die "environment must be staging or prod"

repo=$(cd "$(dirname "$0")/.." && pwd)
dir=${QUIZ_ROOT:-/srv/quiz}/$env
envfile=$dir/.env
set -a
# shellcheck source=/dev/null
. "$envfile"
set +a
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

read -r -p "This replaces all $env data with $file. Type '$env' to continue: " answer
[[ $answer == "$env" ]] || die "aborted"

compose stop api
compose exec -T -e PGUSER=migrator -e PGPASSWORD="$MIGRATOR_PASSWORD" backup \
  pg_restore --clean --if-exists --no-owner --role=migrator --dbname=quiz "/backups/$file"
compose up -d --wait api
echo "restore: $env restored from $file"
