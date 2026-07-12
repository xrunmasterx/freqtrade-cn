#!/bin/sh
set -eu

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\set ON_ERROR_STOP on

SELECT 'CREATE ROLE platform_control'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_control')
\gexec
SELECT format(
    'ALTER ROLE platform_control WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
    CASE
        WHEN right(secret_value, 2) = E'\r\n' THEN left(secret_value, -2)
        WHEN right(secret_value, 1) = E'\n' THEN left(secret_value, -1)
        ELSE secret_value
    END
)
FROM (
    SELECT pg_read_file('/run/secrets/platform_control_db_password') AS secret_value
) AS secret
\gexec

SELECT 'CREATE ROLE platform_supervisor'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_supervisor')
\gexec
SELECT format(
    'ALTER ROLE platform_supervisor WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
    CASE
        WHEN right(secret_value, 2) = E'\r\n' THEN left(secret_value, -2)
        WHEN right(secret_value, 1) = E'\n' THEN left(secret_value, -1)
        ELSE secret_value
    END
)
FROM (
    SELECT pg_read_file('/run/secrets/platform_supervisor_db_password') AS secret_value
) AS secret
\gexec

SELECT format(
    'REVOKE %I FROM platform_control GRANTED BY %I CASCADE',
    granted_role.rolname,
    grantor_role.rolname
)
FROM pg_auth_members AS membership
JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
JOIN pg_roles AS member_role ON member_role.oid = membership.member
JOIN pg_roles AS grantor_role ON grantor_role.oid = membership.grantor
WHERE member_role.rolname = 'platform_control'
\gexec
SELECT format(
    'REVOKE platform_control FROM %I GRANTED BY %I CASCADE',
    member_role.rolname,
    grantor_role.rolname
)
FROM pg_auth_members AS membership
JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
JOIN pg_roles AS member_role ON member_role.oid = membership.member
JOIN pg_roles AS grantor_role ON grantor_role.oid = membership.grantor
WHERE granted_role.rolname = 'platform_control'
\gexec

SELECT format(
    'REVOKE %I FROM platform_supervisor GRANTED BY %I CASCADE',
    granted_role.rolname,
    grantor_role.rolname
)
FROM pg_auth_members AS membership
JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
JOIN pg_roles AS member_role ON member_role.oid = membership.member
JOIN pg_roles AS grantor_role ON grantor_role.oid = membership.grantor
WHERE member_role.rolname = 'platform_supervisor'
\gexec
SELECT format(
    'REVOKE platform_supervisor FROM %I GRANTED BY %I CASCADE',
    member_role.rolname,
    grantor_role.rolname
)
FROM pg_auth_members AS membership
JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
JOIN pg_roles AS member_role ON member_role.oid = membership.member
JOIN pg_roles AS grantor_role ON grantor_role.oid = membership.grantor
WHERE granted_role.rolname = 'platform_supervisor'
\gexec

REVOKE CREATE ON DATABASE platform FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL PRIVILEGES ON DATABASE platform FROM platform_control, platform_supervisor CASCADE;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM platform_control, platform_supervisor CASCADE;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM platform_control, platform_supervisor CASCADE;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM platform_control, platform_supervisor CASCADE;

SELECT format(
    'REVOKE %s (%I) ON TABLE %I.%I FROM %I CASCADE',
    privilege_type,
    column_name,
    table_schema,
    table_name,
    grantee
)
FROM information_schema.column_privileges
WHERE grantee IN ('platform_control', 'platform_supervisor')
  AND privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')
ORDER BY grantee, table_schema, table_name, column_name, privilege_type
\gexec

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
