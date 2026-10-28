#!/usr/bin/env bash
# Check the network between the website's Nginx and the quiz (ADR 0011).
#
#   deploy/edge-check.sh
#
# Passes when only isc-web and the quiz api containers are on the edge network, an address the website's
# Nginx forwards in X-Forwarded-For reaches the app as the client, and a container on the website's shared
# `proxy` network can reach neither api. Starts two throwaway containers and removes them. Run it after
# changing either network or the override, and after a reboot.
set -euo pipefail

die() { echo "edge-check: FAIL: $*" >&2; exit 1; }
log() { echo "edge-check: $*"; }

[[ $# -eq 0 ]] || die "usage: $0"
edge=${EDGE_NETWORK:-quiz-edge}
shared=${SHARED_NETWORK:-proxy}
web=${NGINX_CONTAINER:-isc-web}
api=${API_CONTAINER:-quiz-prod-api-1}
probe=quiz-edge-check-$$
trap 'docker rm -f "$probe" >/dev/null 2>&1 || true' EXIT

image=$(docker inspect -f '{{.Config.Image}}' "$api") || die "$api isn't running"
allow=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$api" | sed -n 's/^FORWARDED_ALLOW_IPS=//p')
subnet=$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}' "$edge") || die "no network $edge"
[[ $allow == "$subnet" ]] || die "$api trusts '$allow', but $edge is $subnet"

members=$(docker network inspect -f '{{range .Containers}}{{.Name}} {{end}}' "$edge")
for m in $members; do
  [[ $m == "$web" || $m =~ ^quiz-(prod|staging)-api-[0-9]+$ ]] || die "$m is on $edge; only $web and the quiz apis belong there"
done
[[ " $members " == *" $web "* ]] || die "$web isn't on $edge"
log "on $edge ($subnet): $members"

# The same uvicorn flags as the image, with an app that answers the client address it was given.
docker run -d --name "$probe" --network "$edge" --network-alias "$probe" -e FORWARDED_ALLOW_IPS="$allow" \
  --entrypoint sh "$image" -c 'printf "%s\n" \
"async def app(scope, receive, send):" \
"    await send({\"type\": \"http.response.start\", \"status\": 200, \"headers\": []})" \
"    await send({\"type\": \"http.response.body\", \"body\": scope[\"client\"][0].encode()})" > /tmp/probe.py &&
exec uvicorn probe:app --app-dir /tmp --host 0.0.0.0 --port 8000 --proxy-headers --no-access-log' >/dev/null
seen=
for _ in $(seq 20); do
  seen=$(docker exec "$web" wget -qO- -T 2 --header 'X-Forwarded-For: 203.0.113.7' "http://$probe:8000/" 2>/dev/null) && break
  sleep 0.5
done
[[ $seen == 203.0.113.7 ]] || die "a request from $web reached the app as '$seen', not the forwarded 203.0.113.7"
log "a client address forwarded by $web reaches the app"

# By alias, and by each api's address on the edge network.
names=(quiz-prod-api quiz-staging-api)
for c in $members; do
  [[ $c == "$web" ]] || names+=("$(docker inspect -f "{{(index .NetworkSettings.Networks \"$edge\").IPAddress}}" "$c")")
done
reached=$(docker run --rm --network "$shared" --entrypoint python "$image" -c '
import sys, urllib.request as u
for host in sys.argv[1:]:
    try:
        u.urlopen(f"http://{host}:8000/healthz", timeout=3)
        print(host)
    except Exception:
        pass' "${names[@]}")
[[ -z $reached ]] || die "a container on $shared reached $reached"
log "a container on $shared reaches none of: ${names[*]}"
log "PASS"
