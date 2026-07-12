#!/bin/sh
set -eu

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\set ON_ERROR_STOP on

SELECT format('CREATE ROLE platform_control LOGIN PASSWORD %L',
              btrim(pg_read_file('/run/secrets/platform_control_db_password')))
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_control')
\gexec
SELECT format('ALTER ROLE platform_control WITH LOGIN PASSWORD %L',
              btrim(pg_read_file('/run/secrets/platform_control_db_password')))
\gexec

SELECT format('CREATE ROLE platform_supervisor LOGIN PASSWORD %L',
              btrim(pg_read_file('/run/secrets/platform_supervisor_db_password')))
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_supervisor')
\gexec
SELECT format('ALTER ROLE platform_supervisor WITH LOGIN PASSWORD %L',
              btrim(pg_read_file('/run/secrets/platform_supervisor_db_password')))
\gexec

REVOKE CREATE ON DATABASE platform FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL PRIVILEGES ON DATABASE platform FROM platform_control, platform_supervisor;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM platform_control, platform_supervisor;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM platform_control, platform_supervisor;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM platform_control, platform_supervisor;

GRANT CONNECT ON DATABASE platform TO platform_control, platform_supervisor;
GRANT USAGE ON SCHEMA public TO platform_control, platform_supervisor;

SELECT format(
    'GRANT SELECT ON TABLE public.%I TO platform_control, platform_supervisor',
    table_name
)
FROM (VALUES
    ('platform_catalog_revisions'),
    ('runtime_instances'),
    ('runtime_attempts'),
    ('runtime_lifecycle_jobs'),
    ('runtime_endpoints'),
    ('runtime_access_requests'),
    ('runtime_audit_events')
) AS catalog(table_name)
WHERE to_regclass(format('public.%I', table_name)) IS NOT NULL
\gexec

SELECT format(
    'GRANT INSERT ON TABLE public.%I TO platform_control',
    table_name
)
FROM (VALUES
    ('runtime_access_requests'),
    ('runtime_audit_events')
) AS control_writes(table_name)
WHERE to_regclass(format('public.%I', table_name)) IS NOT NULL
\gexec

SELECT 'GRANT UPDATE (status, result_code, completed_at) '
       'ON TABLE public.runtime_access_requests TO platform_control'
WHERE to_regclass('public.runtime_access_requests') IS NOT NULL
\gexec

SELECT format(
    'GRANT INSERT, UPDATE ON TABLE public.%I TO platform_supervisor',
    table_name
)
FROM (VALUES
    ('runtime_instances'),
    ('runtime_attempts'),
    ('runtime_lifecycle_jobs'),
    ('runtime_endpoints'),
    ('runtime_access_requests'),
    ('runtime_audit_events')
) AS supervisor_writes(table_name)
WHERE to_regclass(format('public.%I', table_name)) IS NOT NULL
\gexec
SQL
