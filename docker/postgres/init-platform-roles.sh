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

SELECT 'CREATE ROLE platform_operator'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_operator')
\gexec
SELECT format(
    'ALTER ROLE platform_operator WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
    CASE
        WHEN right(secret_value, 2) = E'\r\n' THEN left(secret_value, -2)
        WHEN right(secret_value, 1) = E'\n' THEN left(secret_value, -1)
        ELSE secret_value
    END
)
FROM (
    SELECT pg_read_file('/run/secrets/platform_operator_db_password') AS secret_value
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

SELECT format(
    'REVOKE %I FROM platform_operator GRANTED BY %I CASCADE',
    granted_role.rolname,
    grantor_role.rolname
)
FROM pg_auth_members AS membership
JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
JOIN pg_roles AS member_role ON member_role.oid = membership.member
JOIN pg_roles AS grantor_role ON grantor_role.oid = membership.grantor
WHERE member_role.rolname = 'platform_operator'
\gexec
SELECT format(
    'REVOKE platform_operator FROM %I GRANTED BY %I CASCADE',
    member_role.rolname,
    grantor_role.rolname
)
FROM pg_auth_members AS membership
JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
JOIN pg_roles AS member_role ON member_role.oid = membership.member
JOIN pg_roles AS grantor_role ON grantor_role.oid = membership.grantor
WHERE granted_role.rolname = 'platform_operator'
\gexec

SELECT
    format('SET ROLE %I', public_grantor_role.rolname) AS public_set_role,
    format(
        'REVOKE %s ON DATABASE %I FROM PUBLIC GRANTED BY %I CASCADE',
        privilege.privilege_type,
        database.datname,
        public_grantor_role.rolname
    ) AS public_revoke_privilege,
    'RESET ROLE' AS public_reset_role
FROM pg_database AS database
CROSS JOIN LATERAL aclexplode(
    COALESCE(database.datacl, acldefault('d', database.datdba))
) AS privilege
JOIN pg_roles AS public_grantor_role ON public_grantor_role.oid = privilege.grantor
WHERE privilege.grantee = 0
  AND privilege.privilege_type IN ('CONNECT', 'CREATE', 'TEMPORARY')
ORDER BY database.datname, privilege.privilege_type, public_grantor_role.rolname
\gexec

SELECT
    format('SET ROLE %I', public_grantor_role.rolname) AS public_set_role,
    format(
        'REVOKE %s ON SCHEMA %I FROM PUBLIC GRANTED BY %I CASCADE',
        privilege.privilege_type,
        namespace.nspname,
        public_grantor_role.rolname
    ) AS public_revoke_privilege,
    'RESET ROLE' AS public_reset_role
FROM pg_namespace AS namespace
CROSS JOIN LATERAL aclexplode(
    COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))
) AS privilege
JOIN pg_roles AS public_grantor_role ON public_grantor_role.oid = privilege.grantor
WHERE privilege.grantee = 0
  AND privilege.privilege_type IN ('USAGE', 'CREATE')
  AND namespace.nspname <> 'information_schema'
  AND namespace.nspname !~ '^pg_'
ORDER BY namespace.nspname, privilege.privilege_type, public_grantor_role.rolname
\gexec

SELECT
    format('SET ROLE %I', public_grantor_role.rolname) AS public_set_role,
    format(
        'REVOKE %s ON TABLE %I.%I FROM PUBLIC GRANTED BY %I CASCADE',
        privilege.privilege_type,
        namespace.nspname,
        relation.relname,
        public_grantor_role.rolname
    ) AS public_revoke_privilege,
    'RESET ROLE' AS public_reset_role
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
CROSS JOIN LATERAL aclexplode(
    COALESCE(relation.relacl, acldefault('r', relation.relowner))
) AS privilege
JOIN pg_roles AS public_grantor_role ON public_grantor_role.oid = privilege.grantor
WHERE privilege.grantee = 0
  AND privilege.privilege_type IN
    ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN')
  AND namespace.nspname <> 'information_schema'
  AND namespace.nspname !~ '^pg_'
  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
ORDER BY namespace.nspname, relation.relname,
    privilege.privilege_type, public_grantor_role.rolname
\gexec

SELECT
    format('SET ROLE %I', public_grantor_role.rolname) AS public_set_role,
    format(
        'REVOKE %s ON SEQUENCE %I.%I FROM PUBLIC GRANTED BY %I CASCADE',
        privilege.privilege_type,
        namespace.nspname,
        relation.relname,
        public_grantor_role.rolname
    ) AS public_revoke_privilege,
    'RESET ROLE' AS public_reset_role
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
CROSS JOIN LATERAL aclexplode(
    COALESCE(relation.relacl, acldefault('s', relation.relowner))
) AS privilege
JOIN pg_roles AS public_grantor_role ON public_grantor_role.oid = privilege.grantor
WHERE privilege.grantee = 0
  AND privilege.privilege_type IN ('USAGE', 'SELECT', 'UPDATE')
  AND namespace.nspname <> 'information_schema'
  AND namespace.nspname !~ '^pg_'
  AND relation.relkind = 'S'
ORDER BY namespace.nspname, relation.relname,
    privilege.privilege_type, public_grantor_role.rolname
\gexec

SELECT
    format('SET ROLE %I', public_grantor_role.rolname) AS public_set_role,
    format(
        'REVOKE %s (%I) ON TABLE %I.%I FROM PUBLIC GRANTED BY %I CASCADE',
        privilege.privilege_type,
        attribute.attname,
        namespace.nspname,
        relation.relname,
        public_grantor_role.rolname
    ) AS public_revoke_privilege,
    'RESET ROLE' AS public_reset_role
FROM pg_attribute AS attribute
JOIN pg_class AS relation ON relation.oid = attribute.attrelid
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
CROSS JOIN LATERAL aclexplode(
    COALESCE(attribute.attacl, acldefault('c', relation.relowner))
) AS privilege
JOIN pg_roles AS public_grantor_role ON public_grantor_role.oid = privilege.grantor
WHERE privilege.grantee = 0
  AND privilege.privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')
  AND namespace.nspname <> 'information_schema'
  AND namespace.nspname !~ '^pg_'
  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND attribute.attnum > 0
  AND NOT attribute.attisdropped
ORDER BY namespace.nspname, relation.relname, attribute.attname,
    privilege.privilege_type, public_grantor_role.rolname
\gexec

SELECT
    format('SET ROLE %I', public_grantor_role.rolname) AS public_set_role,
    format(
        'REVOKE EXECUTE ON ROUTINE %I.%I(%s) FROM PUBLIC GRANTED BY %I CASCADE',
        namespace.nspname,
        routine.proname,
        pg_get_function_identity_arguments(routine.oid),
        public_grantor_role.rolname
    ) AS public_revoke_privilege,
    'RESET ROLE' AS public_reset_role
FROM pg_proc AS routine
JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
CROSS JOIN LATERAL aclexplode(
    COALESCE(routine.proacl, acldefault('f', routine.proowner))
) AS privilege
JOIN pg_roles AS public_grantor_role ON public_grantor_role.oid = privilege.grantor
WHERE privilege.grantee = 0
  AND privilege.privilege_type = 'EXECUTE'
  AND namespace.nspname <> 'information_schema'
  AND namespace.nspname !~ '^pg_'
ORDER BY namespace.nspname, routine.proname,
    pg_get_function_identity_arguments(routine.oid), public_grantor_role.rolname
\gexec

ALTER DEFAULT PRIVILEGES FOR ROLE postgres REVOKE EXECUTE ON ROUTINES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE EXECUTE ON ROUTINES FROM PUBLIC;

REVOKE ALL PRIVILEGES ON DATABASE platform FROM platform_control, platform_supervisor, platform_operator CASCADE;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM platform_control, platform_supervisor, platform_operator CASCADE;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM platform_control, platform_supervisor, platform_operator CASCADE;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM platform_control, platform_supervisor, platform_operator CASCADE;

DO $authority_guard$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_shdepend AS shared_dependency
        JOIN pg_roles AS fixed_role ON fixed_role.oid = shared_dependency.refobjid
        WHERE shared_dependency.refclassid = 'pg_authid'::regclass
          AND shared_dependency.deptype = 'o'
          AND fixed_role.rolname IN
            ('platform_control', 'platform_supervisor', 'platform_operator')
        UNION ALL
        SELECT 1
        FROM pg_database AS database
        JOIN pg_roles AS owner_role ON owner_role.oid = database.datdba
        WHERE owner_role.rolname IN
            ('platform_control', 'platform_supervisor', 'platform_operator')
        UNION ALL
        SELECT 1
        FROM pg_namespace AS namespace
        JOIN pg_roles AS owner_role ON owner_role.oid = namespace.nspowner
        WHERE owner_role.rolname IN
            ('platform_control', 'platform_supervisor', 'platform_operator')
        UNION ALL
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_roles AS owner_role ON owner_role.oid = relation.relowner
        WHERE owner_role.rolname IN
            ('platform_control', 'platform_supervisor', 'platform_operator')
    ) THEN
        RAISE EXCEPTION 'fixed_platform_role_owns_object';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_default_acl AS default_acl
        JOIN pg_roles AS default_owner_role
          ON default_owner_role.oid = default_acl.defaclrole
        WHERE default_owner_role.rolname = 'platform_operator'
        UNION ALL
        SELECT 1
        FROM pg_default_acl AS default_acl
        CROSS JOIN LATERAL aclexplode(default_acl.defaclacl) AS default_privilege
        WHERE default_privilege.grantee = 0
           OR default_privilege.grantee = (
                SELECT oid FROM pg_roles WHERE rolname = 'platform_operator'
            )
    ) THEN
        RAISE EXCEPTION 'unsupported_platform_operator_default_authority';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_database AS database
        CROSS JOIN LATERAL aclexplode(
            COALESCE(database.datacl, acldefault('d', database.datdba))
        ) AS privilege
        WHERE privilege.grantee = 0
          AND privilege.privilege_type IN ('CONNECT', 'CREATE', 'TEMPORARY')
        UNION ALL
        SELECT 1
        FROM pg_namespace AS namespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))
        ) AS privilege
        WHERE privilege.grantee = 0
          AND privilege.privilege_type IN ('USAGE', 'CREATE')
          AND namespace.nspname <> 'information_schema'
          AND namespace.nspname !~ '^pg_'
        UNION ALL
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(relation.relacl, acldefault('r', relation.relowner))
        ) AS privilege
        WHERE privilege.grantee = 0
          AND privilege.privilege_type IN
            ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN')
          AND namespace.nspname <> 'information_schema'
          AND namespace.nspname !~ '^pg_'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
        UNION ALL
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(relation.relacl, acldefault('s', relation.relowner))
        ) AS privilege
        WHERE privilege.grantee = 0
          AND privilege.privilege_type IN ('USAGE', 'SELECT', 'UPDATE')
          AND namespace.nspname <> 'information_schema'
          AND namespace.nspname !~ '^pg_'
          AND relation.relkind = 'S'
        UNION ALL
        SELECT 1
        FROM pg_attribute AS attribute
        JOIN pg_class AS relation ON relation.oid = attribute.attrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(attribute.attacl, acldefault('c', relation.relowner))
        ) AS privilege
        WHERE privilege.grantee = 0
          AND privilege.privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')
          AND namespace.nspname <> 'information_schema'
          AND namespace.nspname !~ '^pg_'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
        UNION ALL
        SELECT 1
        FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(routine.proacl, acldefault('f', routine.proowner))
        ) AS privilege
        WHERE privilege.grantee = 0
          AND privilege.privilege_type = 'EXECUTE'
          AND namespace.nspname <> 'information_schema'
          AND namespace.nspname !~ '^pg_'
    ) THEN
        RAISE EXCEPTION 'unsupported_public_authority';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_database AS database
        CROSS JOIN LATERAL aclexplode(database.datacl) AS privilege
        JOIN pg_roles AS grantee_role ON grantee_role.oid = privilege.grantee
        WHERE grantee_role.rolname IN
            ('platform_control', 'platform_supervisor', 'platform_operator')
          AND (database.datname <> 'platform'
            OR privilege.privilege_type NOT IN ('CONNECT', 'CREATE', 'TEMPORARY'))
        UNION ALL
        SELECT 1
        FROM pg_namespace AS namespace
        CROSS JOIN LATERAL aclexplode(namespace.nspacl) AS privilege
        JOIN pg_roles AS grantee_role ON grantee_role.oid = privilege.grantee
        WHERE grantee_role.rolname IN
            ('platform_control', 'platform_supervisor', 'platform_operator')
          AND (namespace.nspname = 'information_schema'
            OR namespace.nspname ~ '^pg_'
            OR privilege.privilege_type NOT IN ('USAGE', 'CREATE'))
        UNION ALL
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL aclexplode(relation.relacl) AS privilege
        JOIN pg_roles AS grantee_role ON grantee_role.oid = privilege.grantee
        WHERE grantee_role.rolname IN
            ('platform_control', 'platform_supervisor', 'platform_operator')
          AND (namespace.nspname = 'information_schema'
            OR namespace.nspname ~ '^pg_'
            OR (relation.relkind IN ('r', 'p', 'v', 'm', 'f')
              AND privilege.privilege_type NOT IN
                ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN'))
            OR (relation.relkind = 'S'
              AND privilege.privilege_type NOT IN ('USAGE', 'SELECT', 'UPDATE'))
            OR relation.relkind NOT IN ('r', 'p', 'v', 'm', 'f', 'S'))
        UNION ALL
        SELECT 1
        FROM pg_attribute AS attribute
        JOIN pg_class AS relation ON relation.oid = attribute.attrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL aclexplode(attribute.attacl) AS privilege
        JOIN pg_roles AS grantee_role ON grantee_role.oid = privilege.grantee
        WHERE grantee_role.rolname IN
            ('platform_control', 'platform_supervisor', 'platform_operator')
          AND (namespace.nspname = 'information_schema'
            OR namespace.nspname ~ '^pg_'
            OR relation.relkind NOT IN ('r', 'p', 'v', 'm', 'f')
            OR privilege.privilege_type NOT IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES'))
        UNION ALL
        SELECT 1
        FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        CROSS JOIN LATERAL aclexplode(routine.proacl) AS privilege
        JOIN pg_roles AS routine_grantee_role
          ON routine_grantee_role.oid = privilege.grantee
        WHERE routine_grantee_role.rolname IN
            ('platform_control', 'platform_supervisor', 'platform_operator')
          AND (namespace.nspname = 'information_schema'
            OR namespace.nspname ~ '^pg_'
            OR privilege.privilege_type <> 'EXECUTE')
    ) THEN
        RAISE EXCEPTION 'unsupported_platform_role_authority';
    END IF;
END
$authority_guard$;

SELECT
    format('SET ROLE %I', object_grantor_role.rolname) AS object_set_role,
    format(
        'REVOKE %s ON DATABASE %I FROM %I GRANTED BY %I CASCADE',
        privilege.privilege_type,
        database.datname,
        object_grantee_role.rolname,
        object_grantor_role.rolname
    ) AS object_revoke_privilege,
    'RESET ROLE' AS object_reset_role
FROM pg_database AS database
CROSS JOIN LATERAL aclexplode(database.datacl) AS privilege
JOIN pg_roles AS object_grantee_role ON object_grantee_role.oid = privilege.grantee
JOIN pg_roles AS object_grantor_role ON object_grantor_role.oid = privilege.grantor
WHERE database.datname = 'platform'
  AND object_grantee_role.rolname IN
    ('platform_control', 'platform_supervisor', 'platform_operator')
  AND privilege.privilege_type IN ('CONNECT', 'CREATE', 'TEMPORARY')
ORDER BY object_grantee_role.rolname, privilege.privilege_type, object_grantor_role.rolname
\gexec

SELECT
    format('SET ROLE %I', object_grantor_role.rolname) AS object_set_role,
    format(
        'REVOKE %s ON SCHEMA %I FROM %I GRANTED BY %I CASCADE',
        privilege.privilege_type,
        namespace.nspname,
        object_grantee_role.rolname,
        object_grantor_role.rolname
    ) AS object_revoke_privilege,
    'RESET ROLE' AS object_reset_role
FROM pg_namespace AS namespace
CROSS JOIN LATERAL aclexplode(namespace.nspacl) AS privilege
JOIN pg_roles AS object_grantee_role ON object_grantee_role.oid = privilege.grantee
JOIN pg_roles AS object_grantor_role ON object_grantor_role.oid = privilege.grantor
WHERE namespace.nspname <> 'information_schema'
  AND namespace.nspname !~ '^pg_'
  AND object_grantee_role.rolname IN
    ('platform_control', 'platform_supervisor', 'platform_operator')
  AND privilege.privilege_type IN ('USAGE', 'CREATE')
ORDER BY object_grantee_role.rolname, namespace.nspname,
    privilege.privilege_type, object_grantor_role.rolname
\gexec

SELECT
    format('SET ROLE %I', object_grantor_role.rolname) AS object_set_role,
    format(
        'REVOKE %s ON TABLE %I.%I FROM %I GRANTED BY %I CASCADE',
        privilege.privilege_type,
        namespace.nspname,
        relation.relname,
        object_grantee_role.rolname,
        object_grantor_role.rolname
    ) AS object_revoke_privilege,
    'RESET ROLE' AS object_reset_role
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
CROSS JOIN LATERAL aclexplode(relation.relacl) AS privilege
JOIN pg_roles AS object_grantee_role ON object_grantee_role.oid = privilege.grantee
JOIN pg_roles AS object_grantor_role ON object_grantor_role.oid = privilege.grantor
WHERE namespace.nspname <> 'information_schema'
  AND namespace.nspname !~ '^pg_'
  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND object_grantee_role.rolname IN
    ('platform_control', 'platform_supervisor', 'platform_operator')
  AND privilege.privilege_type IN
    ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN')
ORDER BY object_grantee_role.rolname, namespace.nspname, relation.relname,
    privilege.privilege_type, object_grantor_role.rolname
\gexec

SELECT
    format('SET ROLE %I', object_grantor_role.rolname) AS object_set_role,
    format(
        'REVOKE %s ON SEQUENCE %I.%I FROM %I GRANTED BY %I CASCADE',
        privilege.privilege_type,
        namespace.nspname,
        relation.relname,
        object_grantee_role.rolname,
        object_grantor_role.rolname
    ) AS object_revoke_privilege,
    'RESET ROLE' AS object_reset_role
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
CROSS JOIN LATERAL aclexplode(relation.relacl) AS privilege
JOIN pg_roles AS object_grantee_role ON object_grantee_role.oid = privilege.grantee
JOIN pg_roles AS object_grantor_role ON object_grantor_role.oid = privilege.grantor
WHERE namespace.nspname <> 'information_schema'
  AND namespace.nspname !~ '^pg_'
  AND relation.relkind = 'S'
  AND object_grantee_role.rolname IN
    ('platform_control', 'platform_supervisor', 'platform_operator')
  AND privilege.privilege_type IN ('USAGE', 'SELECT', 'UPDATE')
ORDER BY object_grantee_role.rolname, namespace.nspname, relation.relname,
    privilege.privilege_type, object_grantor_role.rolname
\gexec

SELECT
    format('SET ROLE %I', column_grantor_role.rolname) AS set_role,
    format(
        'REVOKE %s (%I) ON TABLE %I.%I FROM %I GRANTED BY %I CASCADE',
        privilege.privilege_type,
        attribute.attname,
        namespace.nspname,
        relation.relname,
        column_grantee_role.rolname,
        column_grantor_role.rolname
    ) AS revoke_privilege,
    'RESET ROLE' AS reset_role
FROM pg_attribute AS attribute
JOIN pg_class AS relation ON relation.oid = attribute.attrelid
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
CROSS JOIN LATERAL aclexplode(attribute.attacl) AS privilege
JOIN pg_roles AS column_grantee_role
  ON column_grantee_role.oid = privilege.grantee
JOIN pg_roles AS column_grantor_role
  ON column_grantor_role.oid = privilege.grantor
WHERE column_grantee_role.rolname IN
  ('platform_control', 'platform_supervisor', 'platform_operator')
  AND privilege.privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')
  AND namespace.nspname <> 'information_schema'
  AND namespace.nspname !~ '^pg_'
  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND attribute.attnum > 0
  AND NOT attribute.attisdropped
ORDER BY
    column_grantee_role.rolname,
    namespace.nspname,
    relation.relname,
    attribute.attname,
    privilege.privilege_type,
    column_grantor_role.rolname
\gexec

SELECT
    format('SET ROLE %I', routine_grantor_role.rolname) AS routine_set_role,
    format(
        'REVOKE EXECUTE ON ROUTINE %I.%I(%s) FROM %I GRANTED BY %I CASCADE',
        namespace.nspname,
        routine.proname,
        pg_get_function_identity_arguments(routine.oid),
        routine_grantee_role.rolname,
        routine_grantor_role.rolname
    ) AS routine_revoke_privilege,
    'RESET ROLE' AS routine_reset_role
FROM pg_proc AS routine
JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
CROSS JOIN LATERAL aclexplode(routine.proacl) AS privilege
JOIN pg_roles AS routine_grantee_role
  ON routine_grantee_role.oid = privilege.grantee
JOIN pg_roles AS routine_grantor_role
  ON routine_grantor_role.oid = privilege.grantor
WHERE routine_grantee_role.rolname IN
  ('platform_control', 'platform_supervisor', 'platform_operator')
  AND privilege.privilege_type = 'EXECUTE'
  AND namespace.nspname <> 'information_schema'
  AND namespace.nspname !~ '^pg_'
ORDER BY
    routine_grantee_role.rolname,
    namespace.nspname,
    routine.proname,
    pg_get_function_identity_arguments(routine.oid),
    routine_grantor_role.rolname
\gexec

GRANT CONNECT ON DATABASE platform TO platform_control, platform_supervisor;
GRANT USAGE ON SCHEMA public TO platform_control, platform_supervisor;
GRANT CONNECT ON DATABASE platform TO platform_operator;
GRANT USAGE ON SCHEMA public TO platform_operator;

SELECT format(
    'GRANT SELECT, INSERT ON TABLE public.%I TO platform_operator',
    table_name
)
FROM (VALUES
    ('platform_catalog_revisions'),
    ('adapter_template_revisions'),
    ('state_allocations'),
    ('secret_references'),
    ('runtime_spec_revisions'),
    ('runtime_instances'),
    ('runtime_audit_events')
) AS operator_tables(table_name)
WHERE to_regclass(format('public.%I', table_name)) IS NOT NULL
\gexec

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
    'GRANT SELECT ON TABLE public.%I TO platform_supervisor',
    table_name
)
FROM (VALUES
    ('alembic_version'),
    ('adapter_template_revisions'),
    ('state_allocations'),
    ('secret_references'),
    ('secret_version_metadata'),
    ('runtime_spec_revisions')
) AS supervisor_authority(table_name)
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
