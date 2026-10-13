#!/usr/bin/env bash
# Run the integrity report, or its reveal step, on the team server with the deployed image
# (docs/guides/integrity-report.md).
#
#   deploy/integrity-report.sh staging report --until 2026-10-12 [--checks all] [--split 2026-10-20]
#     (--until is the first day left out; the per-person checks need IFS_RULES_1B_FROM in the environment)
#   deploy/integrity-report.sh prod reveal 1a2b3c4d [5e6f7a8b ...] [--include-alumni]
#
# Connects as backup_ro (read only) with its own DSN, never the app's. The thresholds come from
# <QUIZ_ROOT>/<env>/integrity.env (chmod 600, never in the repository). The salt is typed at the prompt by the
# reviewer who holds it, read here and handed to the container on stdin: it never reaches a command line, the
# environment or a file. The report goes to a file on tmpfs (/dev/shm) readable only by you: read it, then
# shred it. Takes the environment's operation lock, so it never runs during a deploy or a restore.
set -euo pipefail

die() { echo "integrity-report: $*" >&2; exit 1; }
log() { echo "integrity-report: $*"; }

usage="usage: $0 <staging|prod> report --until <first day left out> [options] | $0 <staging|prod> reveal <pseudonym>..."
[[ $# -ge 3 ]] || die "$usage"
env=$1 mode=$2
shift 2
[[ $env =~ ^(staging|prod)$ ]] || die "environment must be staging or prod"
[[ $mode =~ ^(report|reveal)$ ]] || die "$usage"

repo=$(cd "$(dirname "$0")/.." && pwd)
dir=${QUIZ_ROOT:-/srv/quiz}/$env
envfile=$dir/.env
mode600() { [[ $(stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1") == 600 ]]; }
[[ -f $envfile ]] || die "missing $envfile"
mode600 "$envfile" || die "$envfile must be chmod 600"
# Only what this needs is read from .env: the rest (the app's own password among it) stays out of this shell.
quiz_env=$(sed -n 's/^QUIZ_ENV=//p' "$envfile" | tail -n 1)
[[ $quiz_env == "$env" ]] || die "QUIZ_ENV in $envfile is '$quiz_env', expected '$env'"
[[ -f $dir/deployed-tag ]] || die "nothing deployed in $env yet"

thresholds=()
if [[ $mode == report ]]; then
  limits=$dir/integrity.env
  [[ -f $limits ]] || die "missing $limits (the thresholds, see docs/guides/integrity-report.md)"
  mode600 "$limits" || die "$limits must be chmod 600"
  while IFS= read -r line || [[ -n $line ]]; do
    [[ -z ${line//[[:space:]]/} || $line == \#* ]] && continue
    [[ $line =~ ^IFS_INTEGRITY_[A-Z_]+=.+$ ]] || die "$limits: not an IFS_INTEGRITY_ setting: ${line%%=*}"
    [[ $line =~ ^IFS_INTEGRITY_(SALT|DSN)= ]] && die "$limits holds ${line%%=*}: the salt is typed at the prompt, the DSN is set here"
    thresholds+=(-e "$line")
  done <"$limits"
fi

args=()
for arg in "$@"; do
  [[ $arg == --salt-stdin ]] || args+=("$arg")
done

compose() {
  IMAGE_TAG=$(cat "$dir/deployed-tag") docker compose --project-directory "$repo/deploy" \
    -f "$repo/deploy/compose.yaml" --env-file "$envfile" "$@"
}

# shellcheck source=/dev/null
. "$repo/deploy/lib.sh"
lock_check
lock_take "an integrity $mode"
trap lock_release EXIT
umask 077

PGPASSWORD=$(sed -n 's/^BACKUP_PASSWORD=//p' "$envfile" | tail -n 1)
[[ -n $PGPASSWORD ]] || die "BACKUP_PASSWORD is not set in $envfile"
export PGPASSWORD

if [[ -t 0 ]]; then
  IFS= read -rsp "Salt (typed by the reviewer who holds it): " salt </dev/tty
  echo >&2
else
  IFS= read -r salt || true
fi

run() {
  printf '%s\n' "$salt" | compose run --rm --no-deps -T -e PGPASSWORD \
    -e IFS_INTEGRITY_DSN=postgresql+psycopg://backup_ro@db:5432/quiz ${thresholds[@]+"${thresholds[@]}"} \
    api ifs-tests "integrity-$mode" ${args[@]+"${args[@]}"} --salt-stdin
}

# What ran, by whom: never the salt, never a pseudonym.
what=$mode
[[ $mode == report ]] && what+=" ${args[*]}"
[[ $mode == reveal ]] && what+=" ($(printf '%s\n' "${args[@]}" | grep -cv '^--') pseudonyms)"
echo "$(date '+%Y-%m-%dT%H:%M:%S%z') $(id -un) $what" >>"$dir/integrity-history"
if [[ $mode == report ]]; then
  out=${QUIZ_SHM:-/dev/shm}/quiz-$env-integrity-$(TZ=Europe/Madrid date +%Y%m%d-%H%M%S).md
  run >"$out" || { rm -f "$out"; die "the report failed (see above); nothing was kept"; }
  log "report: written to $out; read it, then: shred -u $out"
else
  run
fi
