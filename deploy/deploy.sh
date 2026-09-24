#!/usr/bin/env bash
# Deploy a published image of the quiz app on the team server.
#
#   deploy/deploy.sh staging sha-1a2b3c4d5e6f
#   deploy/deploy.sh prod v0.3.0
#
# Pulls the image, dumps the database, runs migrations as `migrator`, restarts the stack and smoke-tests
# it. If the smoke test fails, the previous tag is started again (migrations are expand/contract, so the
# previous image still works with the new schema). Rolling back to an older tag works the same way: when
# the database is already past every migration the older image knows, migrations are skipped. Run it from
# a checkout of the repo on the server.
set -euo pipefail

die() { echo "deploy: $*" >&2; exit 1; }
log() { echo "deploy: $*"; }

[[ $# -eq 2 ]] || die "usage: $0 <staging|prod> <tag>"
env=$1 tag=$2
[[ $env =~ ^(staging|prod)$ ]] || die "environment must be staging or prod"
[[ $tag =~ ^(v[0-9]+\.[0-9]+\.[0-9]+|sha-[0-9a-f]{7,40})$ ]] || die "tag must be vX.Y.Z or sha-<commit>"
[[ $env == prod && $tag != v* ]] && die "prod only takes release tags (vX.Y.Z)"

repo=$(cd "$(dirname "$0")/.." && pwd)
dir=${QUIZ_ROOT:-/srv/quiz}/$env
envfile=$dir/.env
[[ -f $envfile ]] || die "missing $envfile (copy deploy/env.example)"
[[ $(stat -c %a "$envfile" 2>/dev/null || stat -f %Lp "$envfile") == 600 ]] || die "$envfile must be chmod 600"
set -a
# shellcheck source=/dev/null
. "$envfile"
set +a
[[ $QUIZ_ENV == "$env" ]] || die "QUIZ_ENV in $envfile is '$QUIZ_ENV', expected '$env'"

compose() {
  IMAGE_TAG=$1 docker compose --project-directory "$repo/deploy" -f "$repo/deploy/compose.yaml" \
    --env-file "$envfile" "${@:2}"
}

previous=$(cat "$dir/deployed-tag" 2>/dev/null || true)
log "$env: ${previous:-<none>} -> $tag"

if [[ ${QUIZ_PULL:-1} == 1 ]]; then
  compose "$tag" pull api
fi

compose "$tag" up -d --wait db backup
if [[ -n $previous ]]; then
  log "pre-deploy dump"
  compose "$tag" exec -T backup /bin/sh /quiz/backup.sh once "pre-$tag"
fi

# Passed by name only, so the passwords never show up on a command line (`ps`).
export IFS_DATABASE_URL="postgresql+psycopg://migrator:${MIGRATOR_PASSWORD}@db:5432/quiz"
export PGPASSWORD=$MIGRATOR_PASSWORD
current=$(compose "$tag" exec -T -e PGPASSWORD db psql -h 127.0.0.1 -U migrator -d quiz -tAc \
  "SELECT version_num FROM alembic_version" 2>/dev/null || true)
unset PGPASSWORD
known=1
if [[ -n $current ]] && ! out=$(compose "$tag" run --rm --no-deps api alembic show "$current" 2>&1); then
  grep -q "Can't locate revision" <<<"$out" || die "can't read migration $current in $tag: $out"
  known=0
fi
if [[ $known == 1 ]]; then
  log "migrating"
  compose "$tag" run --rm --no-deps -e IFS_DATABASE_URL api alembic upgrade head
else
  log "the database ($current) is ahead of $tag: skipping migrations (expand/contract keeps it compatible)"
fi
unset IFS_DATABASE_URL

smoke() {
  compose "$tag" exec -T api python - <<'PY'
import sys, urllib.error, urllib.request

def get(path):
    try:
        return urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=5)
    except urllib.error.HTTPError as e:
        return e

health = get("/healthz")
csp = health.headers.get("content-security-policy", "")
checks = {
    "healthz 200": health.status == 200,
    "CSP header": "default-src 'self'" in csp,
    "unknown API route 404": get("/api/__smoke__").status == 404,
    "OpenAPI hidden": get("/api/openapi.json").status == 404,
}
for name, ok in checks.items():
    print(("  ok   " if ok else "  FAIL ") + name)
sys.exit(0 if all(checks.values()) else 1)
PY
}

if compose "$tag" up -d --remove-orphans --wait --wait-timeout 90 api scheduler && smoke; then
  echo "$tag" > "$dir/deployed-tag"
  echo "$(date -u +%FT%TZ) $env $tag $(whoami)" >> "$dir/deploy-history"
  log "done: $env is on $tag"
else
  if [[ -n $previous ]]; then
    log "rolling back to $previous"
    compose "$previous" up -d --remove-orphans --wait --wait-timeout 90 api scheduler
  fi
  die "$tag failed to start or failed the smoke test"
fi
