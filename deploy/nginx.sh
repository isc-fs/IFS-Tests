#!/usr/bin/env bash
# Install deploy/nginx/quiz.conf in the website's Nginx container (ADR 0008).
#
#   deploy/nginx.sh
#
# The website's container (isc-web) owns ports 80 and 443 and mounts <QUIZ_ROOT>/nginx at /etc/nginx/quiz,
# whose *.conf it includes. This copies the checkout's quiz.conf there, has Nginx test the whole configuration,
# and reloads it; if the test fails it puts the previous file back, so a bad quiz.conf never reaches the
# website. Run it from a checkout of the repo on the server, after `git pull`, whenever deploy.sh says so.
set -euo pipefail

die() { echo "nginx: $*" >&2; exit 1; }
log() { echo "nginx: $*"; }

[[ $# -eq 0 ]] || die "usage: $0"
container=${NGINX_CONTAINER:-isc-web}
dir=${QUIZ_ROOT:-/srv/quiz}/nginx
src=$(cd "$(dirname "$0")" && pwd)/nginx/quiz.conf
dest=$dir/quiz.conf

[[ -d $dir ]] || die "$dir doesn't exist: create it (runbook 1.3)"
[[ $(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null) == true ]] ||
  die "the website's Nginx container $container isn't running"
docker inspect -f '{{range .Mounts}}{{.Source}}={{.Destination}} {{end}}' "$container" |
  grep -qw -- "$dir=/etc/nginx/quiz" ||
  die "$container doesn't mount $dir at /etc/nginx/quiz: the website's docker-compose.yml needs the change in runbook 1.3"

if [[ -f $dest ]] && cmp -s "$src" "$dest"; then
  log "quiz.conf is already the installed one; nothing to do"
  exit 0
fi

had_previous=false
if [[ -f $dest ]]; then
  cp -p "$dest" "$dest.previous"
  had_previous=true
fi
cp "$src" "$dest.new" && mv -f "$dest.new" "$dest"

if ! out=$(docker exec "$container" nginx -t 2>&1); then
  if $had_previous; then mv -f "$dest.previous" "$dest"; else rm -f "$dest"; fi
  echo "$out" >&2
  die "Nginx rejected the new quiz.conf; the previous one is back and the website is untouched"
fi
docker exec "$container" nginx -s reload
conf=$(docker exec "$container" nginx -T 2>/dev/null || true)
[[ $conf == *"server_name quiz.iscracingteam.com"* ]] ||
  log "warning: installed and reloaded, but $container's configuration doesn't include /etc/nginx/quiz/*.conf yet (runbook 1.3)"
log "quiz.conf installed and Nginx reloaded"
