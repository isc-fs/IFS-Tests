#!/bin/sh
# Runs once, when the Postgres volume is first initialised (docker-entrypoint-initdb.d).
# Passwords go in as psql variables (:'name' quotes them), never pasted into SQL text.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v migrator="$MIGRATOR_PASSWORD" -v app="$APP_PASSWORD" -v backup="$BACKUP_PASSWORD" <<'SQL'
SELECT set_config('quiz.migrator_password', :'migrator', false),
       set_config('quiz.app_password', :'app', false),
       set_config('quiz.backup_password', :'backup', false);
\i /quiz/roles.sql
SQL
