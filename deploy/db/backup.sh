#!/bin/sh
# Logical backups of the quiz database, run in the `backup` service (postgres image, same major version).
#   backup.sh              loop: one dump a day at $BACKUP_AT (Europe/Madrid), keep $KEEP_DAYS days
#   backup.sh once LABEL   one dump now (used by deploy.sh before migrating)
set -eu

dump() {
  file="/backups/${PGDATABASE}-$(date +%Y%m%d-%H%M%S)-$1.dump"
  pg_dump --format=custom --file="$file.part"
  mv "$file.part" "$file"
  find /backups -name '*.dump' -mtime +"${KEEP_DAYS:-14}" -delete
  if [ -n "${HEARTBEAT_URL:-}" ]; then wget -q -T 10 -O /dev/null "$HEARTBEAT_URL" || true; fi
  echo "backup: $file"
}

if [ "${1:-}" = once ]; then
  dump "${2:-manual}"
  exit 0
fi

echo "backup: daily at ${BACKUP_AT:-02:30} $(date +%Z)"
while true; do
  if [ "$(date +%H:%M)" = "${BACKUP_AT:-02:30}" ]; then
    dump nightly || echo "backup: FAILED" >&2
    sleep 61
  fi
  sleep 20
done
