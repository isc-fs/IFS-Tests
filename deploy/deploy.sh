#!/usr/bin/env bash
# Deploy a published image of the quiz app on the team server.
#
#   deploy/deploy.sh staging sha-1a2b3c4d5e6f
#   deploy/deploy.sh prod v0.3.0
#
# Pulls the image, dumps the database, runs migrations as `migrator`, restarts the stack and smoke-tests
# it (including /readyz, a database query as the app role, and the SPA at /). If the smoke test fails, the
# previous tag is started again (migrations are expand/contract, so the previous image still works with the
# new schema). Rolling back to an older tag works the same way: when the database is already past every
# migration the older image knows, migrations are skipped. That is proven, not assumed: after migrating, the
# database records each migration of the image with a fingerprint of its code (table deploy_migrations), so a
# deploy refuses a database at a revision the image doesn't know unless the record shows the image's whole chain
# leads to it, and refuses an image whose migration under an applied number isn't the one applied (an edited
# migration would otherwise never run). Run it from a checkout of the repo on the server.
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
sql() { compose "$tag" exec -T -e PGPASSWORD db psql -h 127.0.0.1 -U migrator -d quiz -v ON_ERROR_STOP=1 -tAc "$1"; }
current=$(sql "SELECT version_num FROM alembic_version" 2>/dev/null || true)
sql "SET client_min_messages TO warning;
  CREATE TABLE IF NOT EXISTS deploy_migrations (revision text PRIMARY KEY, fingerprint text NOT NULL)" >/dev/null
recorded=$(sql "SELECT revision || ' ' || fingerprint FROM deploy_migrations") || die "can't read deploy_migrations"
# "<revision> <fingerprint>" for each migration the image has: its code without comments, docstrings or layout.
chain=$(compose "$tag" run --rm --no-deps -T api python - <<'PY'
import ast, hashlib
from alembic.config import Config
from alembic.script import ScriptDirectory

for script in ScriptDirectory.from_config(Config("alembic.ini")).walk_revisions():
    tree = ast.parse(open(script.path, encoding="utf-8").read())
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            node.body = body[1:] or [ast.Pass()]
    print(script.revision, hashlib.sha256(ast.unparse(tree).encode()).hexdigest()[:16])
PY
) || die "can't list the migrations of $tag"
grep -qvE '^[0-9A-Za-z_]+ [0-9a-f]{16}$' <<<"$chain" && die "unexpected migration list from $tag: $chain"
# Migrations of the image recorded here with other code: edited after they were applied.
edited=$(awk 'NR == FNR { if (NF == 2) seen[$1] = $2; next } ($1 in seen) && seen[$1] != $2 { print $1 }' \
  <(echo "$recorded") <(echo "$chain") | tr '\n' ' ')
[[ -z $edited ]] || die "migration(s) ${edited% } in $tag differ from the ones applied to this database: an \
applied migration was edited (write a new one instead). Nothing changed. See docs/runbook.md, 2.2"
if [[ -z $current ]] || grep -q "^$current " <<<"$chain"; then
  log "migrating"
  compose "$tag" run --rm --no-deps -e IFS_DATABASE_URL api alembic upgrade head
  values=$(sed -E "s/^([^ ]+) ([^ ]+)$/('\1', '\2')/" <<<"$chain" | paste -sd, -)
  sql "INSERT INTO deploy_migrations VALUES $values
    ON CONFLICT (revision) DO UPDATE SET fingerprint = EXCLUDED.fingerprint" >/dev/null
else
  # Ahead only if this database recorded the revision it is at and every migration of the image.
  missing=$(awk 'NR == FNR { if (NF == 2) seen[$1] = 1; next } !($1 in seen) { print $1 }' \
    <(echo "$recorded") <(echo "$chain") | tr '\n' ' ')
  if ! grep -q "^$current " <<<"$recorded" || [[ -n $missing ]]; then
    die "the database is at $current, which $tag doesn't know, and nothing shows it comes after $tag's \
migrations (a rewritten or foreign migration, or a restore not yet deployed over). Nothing changed. \
See docs/runbook.md, 2.2"
  fi
  log "the database ($current) is ahead of $tag: skipping migrations (expand/contract keeps it compatible)"
fi
unset PGPASSWORD IFS_DATABASE_URL

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
spa = get("/")
checks = {
    "healthz 200": health.status == 200,
    "CSP header": "default-src 'self'" in csp,
    "SPA shell at /": spa.status == 200 and '<div id="root">' in spa.read().decode(errors="replace"),
    "unknown API route 404": get("/api/__smoke__").status == 404,
    "OpenAPI hidden": get("/api/openapi.json").status == 404,
}
ready = get("/readyz")
if ready.headers.get_content_type() == "text/html":
    print("  skip readyz: this image predates it (a rollback to an older release)")
else:
    checks["readyz 200 (database reachable as app_rt, schema as the code maps it)"] = ready.status == 200
for name, ok in checks.items():
    print(("  ok   " if ok else "  FAIL ") + name)
sys.exit(0 if all(checks.values()) else 1)
PY
}

healthy=0
compose "$tag" up -d --remove-orphans --wait --wait-timeout 90 api scheduler && healthy=1
# Smoke-test even when a container isn't healthy: its checks say why (readyz FAIL: the database, APP_PASSWORD or
# a schema missing columns the code maps).
if smoke && [[ $healthy == 1 ]]; then
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
