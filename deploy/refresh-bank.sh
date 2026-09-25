#!/usr/bin/env bash
# Refresh the question bank from FS-Quiz with the currently deployed image.
#
#   deploy/refresh-bank.sh staging
#   deploy/refresh-bank.sh prod
#   deploy/refresh-bank.sh prod --no-mirror   # load the mirror already in the volume, no FS-Quiz requests
#   deploy/refresh-bank.sh prod --no-mirror --allow-mass-removal   # FS-Quiz really deleted over a quarter
#
# Re-fetches every quiz, the document list and the last qualifier results (--refresh), so corrected
# questions, new rulebook editions and new results arrive too, not just new quizzes: about 125 requests,
# one per second, which is fine for a run once a season. Images stay cached: only missing ones are
# fetched. Then loads the bank into the database: options are updated in place, so past answers stay
# valid, and unchanged questions only have their answer parsed again. Safe to repeat.
set -euo pipefail

die() { echo "refresh-bank: $*" >&2; exit 1; }

usage="usage: $0 <staging|prod> [--no-mirror] [--allow-mass-removal]"
[[ $# -ge 1 ]] || die "$usage"
env=$1
shift
mirror=1 mass=
for arg in "$@"; do
  case $arg in
    --no-mirror) ((mirror)) || die "$usage"; mirror=0 ;;
    --allow-mass-removal) [[ -z $mass ]] || die "$usage"; mass=$arg ;;
    *) die "$usage" ;;
  esac
done
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
# Compose names the project after QUIZ_ENV: a mismatch would refresh the other environment.
[[ $QUIZ_ENV == "$env" ]] || die "QUIZ_ENV in $envfile is '$QUIZ_ENV', expected '$env'"
[[ -f $dir/deployed-tag ]] || die "nothing deployed in $env yet"

compose() {
  IMAGE_TAG=$(cat "$dir/deployed-tag") docker compose --project-directory "$repo/deploy" \
    -f "$repo/deploy/compose.yaml" --env-file "$envfile" "$@"
}

((mirror == 0)) || compose run --rm --no-deps api ifs-tests mirror --refresh --images
compose run --rm api ifs-tests push ${mass:+"$mass"}
