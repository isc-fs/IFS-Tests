-- Least-privilege roles for the quiz database. Passwords come from session settings set by the caller
-- (init-roles.sh on first start, or the integration test):
--   quiz.migrator_password, quiz.app_password, quiz.backup_password
-- Safe to run again: existing roles keep their passwords. restore.sh re-applies it after recreating the schema.
--
--   migrator   owns the schema; used only by `alembic upgrade` in deploy.sh
--   app_rt     the running app: read/write data, no DDL
--   backup_ro  nightly pg_dump: read only

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'migrator') THEN
    EXECUTE format('CREATE ROLE migrator LOGIN PASSWORD %L', current_setting('quiz.migrator_password'));
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_rt') THEN
    EXECUTE format('CREATE ROLE app_rt LOGIN PASSWORD %L', current_setting('quiz.app_password'));
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'backup_ro') THEN
    EXECUTE format('CREATE ROLE backup_ro LOGIN PASSWORD %L', current_setting('quiz.backup_password'));
  END IF;
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO migrator, app_rt, backup_ro', current_database());
END $$;

ALTER SCHEMA public OWNER TO migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app_rt, backup_ro;

ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rt;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO app_rt;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA public
  GRANT SELECT ON TABLES TO backup_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA public
  GRANT SELECT ON SEQUENCES TO backup_ro;
