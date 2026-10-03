#!/bin/sh
# Logical backups of the quiz database, run in the `backup` service (postgres image, same major version).
#   backup.sh              loop: one dump a day at $BACKUP_AT (Europe/Madrid), keep $KEEP_DAYS days
#   backup.sh once LABEL   one dump now (used by deploy.sh before migrating)
# 03:30 exists every day; 02:xx is skipped on the spring daylight-saving night.
set -eu

dump() {
  file="/backups/${PGDATABASE}-$(date +%Y%m%d-%H%M%S)-$1.dump"
  pg_dump --format=custom --file="$file.part" || { rm -f "$file.part"; return 1; }
  mv "$file.part" "$file" || return 1
  if [ -n "${HEARTBEAT_URL:-}" ]; then wget -q -T 10 -O /dev/null "$HEARTBEAT_URL" || echo "backup: heartbeat ping failed" >&2; fi
  echo "backup: $file"
}

# Dumps older than KEEP_DAYS go even when tonight's dump failed, so deleted accounts leave the backups on time.
# -mtime +N matches files at least N+1 days old.
prune() {
  find /backups -name '*.dump' -mtime +"$((${KEEP_DAYS:-14} - 1))" -delete
}

if [ "${1:-}" = once ]; then
  dump "${2:-manual}"
  exit $?
fi

echo "backup: daily at ${BACKUP_AT:-03:30} $(date +%Z)"
while true; do
  if [ "$(date +%H:%M)" = "${BACKUP_AT:-03:30}" ]; then
    dump nightly || echo "backup: FAILED, no heartbeat sent" >&2
    prune
    sleep 61
  fi
  sleep 20
done
