#!/bin/sh
# Runs once, when the Postgres volume is first initialised (docker-entrypoint-initdb.d).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "SELECT set_config('quiz.migrator_password', '$MIGRATOR_PASSWORD', false),
             set_config('quiz.app_password', '$APP_PASSWORD', false),
             set_config('quiz.backup_password', '$BACKUP_PASSWORD', false)" \
  -f /quiz/roles.sql
