#!/usr/bin/env bash
# Refresh the question bank from FS-Quiz with the currently deployed image.
#
#   deploy/refresh-bank.sh staging
#   deploy/refresh-bank.sh prod
#
# Mirrors new quizzes and images into the fsquiz volume (cached: only what is missing is fetched, one
# request per second), then loads them into the database. Safe to repeat.
set -euo pipefail

die() { echo "refresh-bank: $*" >&2; exit 1; }

[[ $# -eq 1 ]] || die "usage: $0 <staging|prod>"
env=$1
[[ $env =~ ^(staging|prod)$ ]] || die "environment must be staging or prod"

repo=$(cd "$(dirname "$0")/.." && pwd)
dir=${QUIZ_ROOT:-/srv/quiz}/$env
envfile=$dir/.env
[[ -f $envfile ]] || die "missing $envfile"
[[ -f $dir/deployed-tag ]] || die "nothing deployed in $env yet"

compose() {
  IMAGE_TAG=$(cat "$dir/deployed-tag") docker compose --project-directory "$repo/deploy" \
    -f "$repo/deploy/compose.yaml" --env-file "$envfile" "$@"
}

compose run --rm --no-deps api ifs-tests mirror --images
compose run --rm api ifs-tests push
