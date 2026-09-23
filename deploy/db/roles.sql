-- Least-privilege roles for the quiz database. Passwords come from session settings set by the caller
-- (init-roles.sh on first start, or the integration test):
--   quiz.migrator_password, quiz.app_password, quiz.backup_password
--
--   migrator   owns the schema; used only by `alembic upgrade` in deploy.sh
--   app_rt     the running app: read/write data, no DDL
--   backup_ro  nightly pg_dump: read only

DO $$
BEGIN
  EXECUTE format('CREATE ROLE migrator LOGIN PASSWORD %L', current_setting('quiz.migrator_password'));
  EXECUTE format('CREATE ROLE app_rt LOGIN PASSWORD %L', current_setting('quiz.app_password'));
  EXECUTE format('CREATE ROLE backup_ro LOGIN PASSWORD %L', current_setting('quiz.backup_password'));
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
