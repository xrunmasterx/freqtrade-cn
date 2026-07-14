from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from tools import compose_runtime, runtime_contract


REPO_ROOT = Path(__file__).resolve().parents[1]


class PlatformControlContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compose = compose_runtime.render_platform_compose(root=REPO_ROOT)

    def errors(self, compose: dict[str, object] | None = None) -> list[str]:
        return runtime_contract.validate_platform_compose(
            copy.deepcopy(compose if compose is not None else self.compose),
            repo_root=REPO_ROOT,
        )

    def role_script(self) -> str:
        return (REPO_ROOT / "docker/postgres/init-platform-roles.sh").read_text(
            encoding="utf-8"
        )

    def role_script_errors(self, script: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "docker/postgres/init-platform-roles.sh"
            path.parent.mkdir(parents=True)
            path.write_text(script, encoding="utf-8", newline="")
            return runtime_contract._validate_platform_role_script(root)

    def test_documentation_keeps_operator_runtime_deferred_to_task_7_5(self) -> None:
        document = (REPO_ROOT / "docs/operations/platform-control.md").read_text(
            encoding="utf-8"
        )
        normalized = " ".join(document.split())
        required = (
            "Task 7.4 establishes only the `platform_operator` database authority",
            "`platform-operator` is not a Compose service in Task 7.4",
            "the `platform` profile still contains only `platform-postgres` and "
            "`platform-control`",
            "`rotate-secrets --service platform-operator` rotates only "
            "`platform_operator_db_password`",
            "The operator service, image copy, CLI, and executable PostgreSQL probes arrive "
            "atomically in Task 7.5",
            "none of the fixed roles inherits database DDL or temporary-table authority",
            "Task 7.5 must probe PostgreSQL 17 effective privileges, including authority "
            "inherited through `PUBLIC`",
        )
        for statement in required:
            self.assertIn(statement, normalized)

    def test_platform_compose_has_exact_isolated_inventory(self) -> None:
        self.assertEqual(set(self.compose["services"]), {"platform-postgres", "platform-control"})
        self.assertEqual(
            self.compose["networks"],
            {
                "platform-db": {
                    "name": "freqtrade-cn_platform-db",
                    "ipam": {},
                    "internal": True,
                },
                "platform-ingress": {
                    "name": "freqtrade-cn_platform-ingress",
                    "ipam": {},
                },
            },
        )
        self.assertEqual(
            self.compose["volumes"],
            {"platform-postgres-data": {"name": "freqtrade-cn_platform-postgres-data"}},
        )
        self.assertEqual(
            set(self.compose["secrets"]),
            {
                "platform_postgres_admin_password",
                "platform_control_db_password",
                "platform_supervisor_db_password",
                "platform_operator_db_password",
                "platform_control_api_password",
                "platform_control_jwt_secret",
            },
        )
        self.assertEqual(self.errors(), [])

    def test_operator_database_secret_is_mounted_only_into_postgres(self) -> None:
        definition = self.compose["secrets"]["platform_operator_db_password"]
        self.assertEqual(
            definition,
            {
                "name": "freqtrade-cn_platform_operator_db_password",
                "file": str(
                    (
                        REPO_ROOT
                        / "ft_userdata/secrets/platform/platform_operator_db_password"
                    ).resolve()
                ),
            },
        )
        postgres = self.compose["services"]["platform-postgres"]
        self.assertEqual(
            postgres["secrets"],
            [
                {
                    "source": "platform_postgres_admin_password",
                    "target": "postgres_admin_password",
                },
                {
                    "source": "platform_control_db_password",
                    "target": "platform_control_db_password",
                },
                {
                    "source": "platform_supervisor_db_password",
                    "target": "platform_supervisor_db_password",
                },
                {
                    "source": "platform_operator_db_password",
                    "target": "platform_operator_db_password",
                },
            ],
        )
        self.assertNotIn(
            "platform_operator_db_password",
            {
                secret["source"]
                for secret in self.compose["services"]["platform-control"]["secrets"]
            },
        )

    def test_operator_database_secret_mutations_fail_closed(self) -> None:
        mutations: list[tuple[str, dict[str, object]]] = []

        missing = copy.deepcopy(self.compose)
        missing["secrets"].pop("platform_operator_db_password")
        mutations.append(("platform Compose secrets differ", missing))

        changed_file = copy.deepcopy(self.compose)
        changed_file["secrets"]["platform_operator_db_password"]["file"] = (
            "private-operator-path"
        )
        mutations.append(("platform Compose secret definition differs", changed_file))

        changed_target = copy.deepcopy(self.compose)
        changed_target["services"]["platform-postgres"]["secrets"][-1]["target"] = (
            "alternate_operator_password"
        )
        mutations.append(("platform-postgres secrets differs", changed_target))

        writable_mode = copy.deepcopy(self.compose)
        writable_mode["services"]["platform-postgres"]["secrets"][-1]["mode"] = 0o666
        mutations.append(("platform-postgres secrets differs", writable_mode))

        control_mount = copy.deepcopy(self.compose)
        control_mount["services"]["platform-control"]["secrets"].append(
            {
                "source": "platform_operator_db_password",
                "target": "operator_database_password",
            }
        )
        mutations.append(("platform-control secret allocation differs", control_mount))

        direct_value = copy.deepcopy(self.compose)
        direct_value["services"]["platform-control"]["environment"][
            "PLATFORM_OPERATOR_DATABASE_PASSWORD"
        ] = "private-operator-value"
        mutations.append(("platform-control direct secret environment", direct_value))

        extra_service = copy.deepcopy(self.compose)
        extra_service["services"]["platform-operator"] = {}
        mutations.append(("platform Compose services differ", extra_service))

        for expected, compose in mutations:
            with self.subTest(expected=expected):
                text = "\n".join(self.errors(compose))
                self.assertIn(expected, text)
                self.assertNotIn("private-operator", text)

    def test_platform_control_is_only_fixed_loopback_application_port(self) -> None:
        service = self.compose["services"]["platform-control"]
        self.assertEqual(
            service["ports"],
            [{
                "target": 8090,
                "published": "8090",
                "host_ip": "127.0.0.1",
                "protocol": "tcp",
                "mode": "ingress",
            }],
        )
        self.assertEqual(
            service["environment"],
            {
                "PLATFORM_CONTROL_API_PASSWORD_FILE": "/run/secrets/api_password",
                "PLATFORM_CONTROL_BIND_MODE": "container_loopback_publish",
                "PLATFORM_CONTROL_JWT_SECRET_FILE": "/run/secrets/jwt_secret_key",
                "PLATFORM_CONTROL_LISTEN_HOST": "0.0.0.0",
                "PLATFORM_CONTROL_USERNAME": "platform_operator",
                "PLATFORM_DATABASE_HOST": "platform-postgres",
                "PLATFORM_DATABASE_NAME": "platform",
                "PLATFORM_DATABASE_PASSWORD_FILE": "/run/secrets/database_password",
                "PLATFORM_DATABASE_PORT": "5432",
                "PLATFORM_DATABASE_USERNAME": "platform_control",
            },
        )
        self.assertEqual(
            service["networks"],
            {"platform-db": None, "platform-ingress": None},
        )

    def test_platform_control_has_no_docker_or_runtime_state_mount(self) -> None:
        service = self.compose["services"]["platform-control"]
        volumes = service.get("volumes", [])
        rendered_volumes = json.dumps(volumes, sort_keys=True)
        self.assertNotIn("docker.sock", rendered_volumes)
        self.assertNotIn("ft_userdata/runtime", rendered_volumes)
        self.assertNotIn(str(REPO_ROOT), rendered_volumes)
        self.assertEqual(volumes, [])
        self.assertEqual(service["user"], "1000:1000")
        self.assertTrue(service["read_only"])
        self.assertTrue(service["init"])
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertEqual(service["security_opt"], ["no-new-privileges:true"])
        self.assertNotIn("extra_hosts", service)

    def test_postgres_is_internal_and_uses_only_named_database_storage(self) -> None:
        service = self.compose["services"]["platform-postgres"]
        self.assertEqual(service["image"], "postgres:17.10-alpine")
        self.assertEqual(service.get("ports", []), [])
        self.assertEqual(service["expose"], ["5432"])
        self.assertEqual(service["networks"], {"platform-db": None})
        self.assertEqual(service["volumes"][0], {
                "type": "volume",
                "source": "platform-postgres-data",
                "target": "/var/lib/postgresql/data",
            })
        self.assertEqual(service["volumes"][1]["target"], "/docker-entrypoint-initdb.d/init-platform-roles.sh")
        self.assertTrue(service["volumes"][1]["read_only"])
        self.assertEqual(
            service["environment"],
            {
                "POSTGRES_DB": "platform",
                "POSTGRES_PASSWORD_FILE": "/run/secrets/postgres_admin_password",
                "POSTGRES_USER": "postgres",
            },
        )

    def test_mutations_fail_closed(self) -> None:
        cases: list[tuple[str, object]] = []

        wildcard = copy.deepcopy(self.compose)
        wildcard["services"]["platform-control"]["ports"][0]["host_ip"] = "0.0.0.0"
        cases.append(("host loopback", wildcard))

        loopback_bind = copy.deepcopy(self.compose)
        loopback_bind["services"]["platform-control"]["environment"][
            "PLATFORM_CONTROL_LISTEN_HOST"
        ] = "127.0.0.1"
        cases.append(("container bind", loopback_bind))

        admin_secret = copy.deepcopy(self.compose)
        admin_secret["services"]["platform-control"]["secrets"].append(
            {"source": "platform_postgres_admin_password", "target": "admin"}
        )
        cases.append(("secret allocation", admin_secret))

        supervisor_secret = copy.deepcopy(self.compose)
        supervisor_secret["services"]["platform-control"]["secrets"].append(
            {"source": "platform_supervisor_db_password", "target": "supervisor"}
        )
        cases.append(("secret allocation", supervisor_secret))

        direct_password = copy.deepcopy(self.compose)
        direct_password["services"]["platform-control"]["environment"][
            "PLATFORM_CONTROL_PASSWORD"
        ] = "private-value"
        cases.append(("direct secret environment", direct_password))

        direct_dsn = copy.deepcopy(self.compose)
        direct_dsn["services"]["platform-control"]["environment"][
            "PLATFORM_DATABASE_DSN"
        ] = "postgresql://private-value"
        cases.append(("direct secret environment", direct_dsn))

        docker_mount = copy.deepcopy(self.compose)
        docker_mount["services"]["platform-control"]["volumes"] = [
            {"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock"}
        ]
        cases.append(("volumes", docker_mount))

        state_mount = copy.deepcopy(self.compose)
        state_mount["services"]["platform-control"]["volumes"] = [
            {"type": "bind", "source": str(REPO_ROOT / "ft_userdata/runtime"), "target": "/state"}
        ]
        cases.append(("volumes", state_mount))

        root_mount = copy.deepcopy(self.compose)
        root_mount["services"]["platform-control"]["volumes"] = [
            {"type": "bind", "source": str(REPO_ROOT), "target": "/repo"}
        ]
        cases.append(("volumes", root_mount))

        extra_service = copy.deepcopy(self.compose)
        extra_service["services"]["rogue"] = {}
        cases.append(("services", extra_service))

        extra_secret = copy.deepcopy(self.compose)
        extra_secret["secrets"]["rogue"] = {"file": "private-value"}
        cases.append(("secrets", extra_secret))

        extra_resource = copy.deepcopy(self.compose)
        extra_resource["networks"]["rogue"] = {}
        cases.append(("networks", extra_resource))

        missing_ingress = copy.deepcopy(self.compose)
        del missing_ingress["services"]["platform-control"]["networks"]["platform-ingress"]
        cases.append(("platform-control networks", missing_ingress))

        extra_volume = copy.deepcopy(self.compose)
        extra_volume["volumes"]["rogue"] = {}
        cases.append(("volumes", extra_volume))

        for expected, compose in cases:
            with self.subTest(expected=expected):
                errors = self.errors(compose)
                self.assertTrue(errors, expected)
                self.assertNotIn("private-value", "\n".join(errors))

    def test_role_script_is_idempotent_and_narrow(self) -> None:
        script = (REPO_ROOT / "docker/postgres/init-platform-roles.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("pg_read_file", script)
        self.assertIn("format(", script)
        self.assertIn("ACLDEFAULT('D', DATABASE.DATDBA)", script.upper())
        self.assertIn("PRIVILEGE.GRANTEE = 0", script.upper())
        self.assertIn("UPDATE (status, result_code, completed_at)", script)
        self.assertEqual(
            script.upper().count("ALTER DEFAULT PRIVILEGES FOR ROLE POSTGRES"), 4
        )
        self.assertNotIn("GRANT ALL", script.upper())
        self.assertNotIn("GRANT DELETE", script.upper())
        self.assertNotIn("GRANT TRUNCATE", script.upper())
        self.assertNotIn("PASSWORD=", script.upper())

    def test_role_script_validator_rejects_broadened_grants(self) -> None:
        errors = self.role_script_errors(
            self.role_script()
            + "\nGRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO platform_control;\n"
        )
        self.assertIn("platform role initializer broadens database authority", errors)

    def test_role_script_closes_public_effective_authority(self) -> None:
        safe_script = self.role_script()
        compact = runtime_contract._active_platform_role_script(safe_script)
        compact = re.sub(r"\(\s+", "(", compact)
        compact = re.sub(r"\s+\)", ")", compact)
        cleanup_fragments = (
            "ACLEXPLODE(COALESCE(DATABASE.DATACL, ACLDEFAULT('D', DATABASE.DATDBA)))",
            "ACLEXPLODE(COALESCE(NAMESPACE.NSPACL, ACLDEFAULT('N', NAMESPACE.NSPOWNER)))",
            "ACLEXPLODE(COALESCE(RELATION.RELACL, ACLDEFAULT('R', RELATION.RELOWNER)))",
            "ACLEXPLODE(COALESCE(RELATION.RELACL, ACLDEFAULT('S', RELATION.RELOWNER)))",
            "ACLEXPLODE(COALESCE(ATTRIBUTE.ATTACL, ACLDEFAULT('C', RELATION.RELOWNER)))",
            "ACLEXPLODE(COALESCE(ROUTINE.PROACL, ACLDEFAULT('F', ROUTINE.PROOWNER)))",
            "REVOKE %S ON DATABASE %I FROM PUBLIC GRANTED BY %I CASCADE",
            "REVOKE %S ON SCHEMA %I FROM PUBLIC GRANTED BY %I CASCADE",
            "REVOKE %S ON TABLE %I.%I FROM PUBLIC GRANTED BY %I CASCADE",
            "REVOKE %S ON SEQUENCE %I.%I FROM PUBLIC GRANTED BY %I CASCADE",
            "REVOKE %S (%I) ON TABLE %I.%I FROM PUBLIC GRANTED BY %I CASCADE",
            "REVOKE EXECUTE ON ROUTINE %I.%I(%S) FROM PUBLIC GRANTED BY %I CASCADE",
            "RAISE EXCEPTION 'UNSUPPORTED_PUBLIC_AUTHORITY'",
        )
        for fragment in cleanup_fragments:
            self.assertIn(fragment, compact)
        self.assertGreaterEqual(compact.count("PRIVILEGE.GRANTEE = 0"), 7)
        self.assertEqual(
            compact.count(
                "PRIVILEGE.PRIVILEGE_TYPE IN ('SELECT', 'INSERT', 'UPDATE', "
                "'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN')"
            ),
            2,
        )
        self.assertIn("NAMESPACE.NSPNAME <> 'INFORMATION_SCHEMA'", compact)
        self.assertIn("NAMESPACE.NSPNAME !~ '^PG_'", compact)

        default_hardening = (
            "ALTER DEFAULT PRIVILEGES FOR ROLE POSTGRES REVOKE EXECUTE ON ROUTINES "
            "FROM PUBLIC;",
            "ALTER DEFAULT PRIVILEGES FOR ROLE POSTGRES IN SCHEMA PUBLIC REVOKE ALL "
            "PRIVILEGES ON TABLES FROM PUBLIC;",
            "ALTER DEFAULT PRIVILEGES FOR ROLE POSTGRES IN SCHEMA PUBLIC REVOKE ALL "
            "PRIVILEGES ON SEQUENCES FROM PUBLIC;",
            "ALTER DEFAULT PRIVILEGES FOR ROLE POSTGRES IN SCHEMA PUBLIC REVOKE EXECUTE "
            "ON ROUTINES FROM PUBLIC;",
        )
        for fragment in default_hardening:
            self.assertEqual(compact.count(fragment), 1)
        self.assertEqual(self.role_script_errors(safe_script), [])

        mutations = {
            "database null acl default omitted": safe_script.replace(
                "COALESCE(database.datacl, acldefault('d', database.datdba))",
                "database.datacl",
                1,
            ),
            "public oid zero omitted": safe_script.replace(
                "privilege.grantee = 0",
                "FALSE",
                1,
            ),
            "database revoke omitted": safe_script.replace(
                "FROM PUBLIC GRANTED BY %I CASCADE',\n"
                "        privilege.privilege_type,\n"
                "        database.datname,",
                "FROM platform_operator GRANTED BY %I CASCADE',\n"
                "        privilege.privilege_type,\n"
                "        database.datname,",
                1,
            ),
            "routine revoke omitted": safe_script.replace(
                "REVOKE EXECUTE ON ROUTINE %I.%I(%s) FROM PUBLIC",
                "REVOKE EXECUTE ON ROUTINE %I.%I(%s) FROM platform_operator",
                1,
            ),
            "postgres routine default omitted": safe_script.replace(
                "ALTER DEFAULT PRIVILEGES FOR ROLE postgres REVOKE EXECUTE ON ROUTINES "
                "FROM PUBLIC;\n",
                "",
                1,
            ),
            "default public guard omitted": safe_script.replace(
                "default_privilege.grantee = 0",
                "FALSE",
                1,
            ),
        }
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                self.assertNotEqual(mutated, safe_script)
                self.assertTrue(
                    any(
                        "public authority" in error
                        or "default privilege" in error
                        or "default authority" in error
                        for error in self.role_script_errors(mutated)
                    )
                )

    def test_role_validator_rejects_public_grants(self) -> None:
        grants = (
            "GRANT UPDATE ON TABLE public.runtime_instances TO PUBLIC;",
            "GRANT UPDATE (desired_state) ON TABLE public.runtime_instances TO PUBLIC;",
            "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
            "GRANT UPDATE ON TABLES TO PUBLIC;",
        )
        for grant in grants:
            with self.subTest(grant=grant):
                errors = self.role_script_errors(self.role_script() + "\n" + grant + "\n")
                self.assertIn("platform role initializer broadens database authority", errors)

    def test_role_validator_rejects_public_default_hardening_reordering(self) -> None:
        script = self.role_script()
        default_revoke = (
            "ALTER DEFAULT PRIVILEGES FOR ROLE postgres REVOKE EXECUTE ON ROUTINES "
            "FROM PUBLIC;\n"
        )
        moved = script.replace(default_revoke, "", 1).replace(
            "DO $authority_guard$\n",
            default_revoke + "\nDO $authority_guard$\n",
            1,
        )
        self.assertNotEqual(moved, script)
        self.assertIn(
            "platform role initializer public authority order differs",
            self.role_script_errors(moved),
        )

    def test_role_password_normalization_removes_only_one_terminal_newline(self) -> None:
        script = self.role_script().lower()
        self.assertNotRegex(script, r"\b(?:btrim|trim)\s*\(")
        self.assertEqual(script.count("right(secret_value, 2) = e'\\r\\n'"), 3)
        self.assertEqual(script.count("left(secret_value, -2)"), 3)
        self.assertEqual(script.count("right(secret_value, 1) = e'\\n'"), 3)
        self.assertEqual(script.count("left(secret_value, -1)"), 3)

    def test_role_script_resets_exact_attributes_and_both_membership_directions(self) -> None:
        script = " ".join(self.role_script().upper().split())
        attributes = (
            "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
            "NOREPLICATION NOBYPASSRLS PASSWORD %L"
        )
        self.assertEqual(script.count(attributes), 3)
        for role in ("PLATFORM_CONTROL", "PLATFORM_SUPERVISOR", "PLATFORM_OPERATOR"):
            self.assertIn(f"MEMBER_ROLE.ROLNAME = '{role}'", script)
            self.assertIn(f"GRANTED_ROLE.ROLNAME = '{role}'", script)
        self.assertGreaterEqual(script.count("PG_AUTH_MEMBERS"), 6)
        self.assertEqual(
            script.count(
                "JOIN PG_ROLES AS GRANTOR_ROLE ON GRANTOR_ROLE.OID = MEMBERSHIP.GRANTOR"
            ),
            6,
        )
        self.assertEqual(script.count("GRANTED BY %I CASCADE"), 17)
        self.assertGreaterEqual(script.count(" CASCADE"), 5)

    def test_role_script_fails_closed_on_operator_ownership_and_default_authority(self) -> None:
        script = " ".join(self.role_script().upper().split())
        self.assertNotIn("REASSIGN OWNED", script)
        self.assertNotIn("DROP OWNED", script)
        self.assertEqual(
            script.count(
                "OWNER_ROLE.ROLNAME IN ('PLATFORM_CONTROL', 'PLATFORM_SUPERVISOR', "
                "'PLATFORM_OPERATOR')"
            ),
            3,
        )
        default_fragments = (
            "FROM PG_DEFAULT_ACL AS DEFAULT_ACL",
            "JOIN PG_ROLES AS DEFAULT_OWNER_ROLE ON "
            "DEFAULT_OWNER_ROLE.OID = DEFAULT_ACL.DEFACLROLE",
            "CROSS JOIN LATERAL ACLEXPLODE(DEFAULT_ACL.DEFACLACL) AS DEFAULT_PRIVILEGE",
            "DEFAULT_OWNER_ROLE.ROLNAME = 'PLATFORM_OPERATOR'",
            "DEFAULT_PRIVILEGE.GRANTEE = 0",
            "DEFAULT_PRIVILEGE.GRANTEE = ( SELECT OID FROM PG_ROLES WHERE "
            "ROLNAME = 'PLATFORM_OPERATOR' )",
            "RAISE EXCEPTION 'UNSUPPORTED_PLATFORM_OPERATOR_DEFAULT_AUTHORITY'",
        )
        for fragment in default_fragments:
            self.assertIn(fragment, script)

    def test_role_script_grants_exact_operator_table_allowlist(self) -> None:
        script = runtime_contract._active_platform_role_script(self.role_script())
        compact = " ".join(script.split())
        self.assertEqual(
            runtime_contract._role_table_inventory(compact, "OPERATOR_TABLES"),
            [
                "PLATFORM_CATALOG_REVISIONS",
                "ADAPTER_TEMPLATE_REVISIONS",
                "STATE_ALLOCATIONS",
                "SECRET_REFERENCES",
                "RUNTIME_SPEC_REVISIONS",
                "RUNTIME_INSTANCES",
                "RUNTIME_AUDIT_EVENTS",
            ],
        )
        self.assertEqual(
            compact.count(
                "GRANT SELECT, INSERT ON TABLE PUBLIC.%I TO PLATFORM_OPERATOR"
            ),
            1,
        )
        self.assertEqual(
            compact.count("GRANT CONNECT ON DATABASE PLATFORM TO PLATFORM_OPERATOR;"),
            1,
        )
        self.assertEqual(
            compact.count("GRANT USAGE ON SCHEMA PUBLIC TO PLATFORM_OPERATOR;"),
            1,
        )
        operator_tables = set(
            runtime_contract._role_table_inventory(compact, "OPERATOR_TABLES") or []
        )
        self.assertTrue(
            operator_tables.isdisjoint(
                {
                    "SECRET_VERSION_METADATA",
                    "RUNTIME_ATTEMPTS",
                    "RUNTIME_LIFECYCLE_JOBS",
                    "RUNTIME_ENDPOINTS",
                    "RUNTIME_ACCESS_REQUESTS",
                }
            )
        )
        for forbidden in (
            "GRANT UPDATE ON TABLE PUBLIC.%I TO PLATFORM_OPERATOR",
            "GRANT DELETE ON TABLE PUBLIC.%I TO PLATFORM_OPERATOR",
            "GRANT TRUNCATE ON TABLE PUBLIC.%I TO PLATFORM_OPERATOR",
            "GRANT REFERENCES ON TABLE PUBLIC.%I TO PLATFORM_OPERATOR",
            "GRANT TRIGGER ON TABLE PUBLIC.%I TO PLATFORM_OPERATOR",
            "GRANT USAGE ON SEQUENCE PUBLIC.%I TO PLATFORM_OPERATOR",
        ):
            self.assertNotIn(forbidden, compact)

    def test_role_script_clears_residual_column_privileges_before_regrant(self) -> None:
        script = " ".join(self.role_script().upper().split())
        self.assertIn(
            "CROSS JOIN LATERAL ACLEXPLODE(ATTRIBUTE.ATTACL) AS PRIVILEGE",
            script,
        )
        self.assertIn(
            "JOIN PG_ROLES AS COLUMN_GRANTEE_ROLE ON "
            "COLUMN_GRANTEE_ROLE.OID = PRIVILEGE.GRANTEE",
            script,
        )
        self.assertIn(
            "JOIN PG_ROLES AS COLUMN_GRANTOR_ROLE ON "
            "COLUMN_GRANTOR_ROLE.OID = PRIVILEGE.GRANTOR",
            script,
        )
        self.assertIn("FROM %I GRANTED BY %I CASCADE", script)
        set_role = "FORMAT('SET ROLE %I', COLUMN_GRANTOR_ROLE.ROLNAME) AS SET_ROLE"
        revoke = "AS REVOKE_PRIVILEGE"
        reset_role = "'RESET ROLE' AS RESET_ROLE"
        self.assertEqual(script.count(set_role), 1)
        self.assertEqual(script.count(revoke), 1)
        self.assertEqual(script.count(reset_role), 1)
        self.assertLess(script.index(set_role), script.index(revoke))
        self.assertLess(script.index(revoke), script.index(reset_role))
        self.assertIn(
            "PRIVILEGE.PRIVILEGE_TYPE IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')",
            script,
        )
        self.assertIn(
            "COLUMN_GRANTEE_ROLE.ROLNAME IN ('PLATFORM_CONTROL', 'PLATFORM_SUPERVISOR', "
            "'PLATFORM_OPERATOR')",
            script,
        )
        cleanup = script.index("CROSS JOIN LATERAL ACLEXPLODE(ATTRIBUTE.ATTACL)")
        first_grant = script.index("GRANT CONNECT ON DATABASE PLATFORM")
        self.assertLess(cleanup, first_grant)

    def test_role_script_sweeps_all_object_acls_by_original_grantor(self) -> None:
        script = " ".join(self.role_script().upper().split())
        fragments = (
            "ACLEXPLODE(DATABASE.DATACL)",
            "DATABASE.DATNAME = 'PLATFORM'",
            "ACLEXPLODE(NAMESPACE.NSPACL)",
            "ACLEXPLODE(RELATION.RELACL)",
            "RELATION.RELKIND IN ('R', 'P', 'V', 'M', 'F')",
            "RELATION.RELKIND = 'S'",
            "NAMESPACE.NSPNAME <> 'INFORMATION_SCHEMA'",
            "NAMESPACE.NSPNAME !~ '^PG_'",
            "PRIVILEGE.PRIVILEGE_TYPE IN ('CONNECT', 'CREATE', 'TEMPORARY')",
            "PRIVILEGE.PRIVILEGE_TYPE IN ('USAGE', 'CREATE')",
            "PRIVILEGE.PRIVILEGE_TYPE IN ('SELECT', 'INSERT', 'UPDATE', "
            "'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER')",
            "PRIVILEGE.PRIVILEGE_TYPE IN ('USAGE', 'SELECT', 'UPDATE')",
        )
        for fragment in fragments:
            self.assertIn(fragment, script)
        self.assertEqual(script.count("AS OBJECT_SET_ROLE"), 4)
        self.assertEqual(script.count("AS OBJECT_REVOKE_PRIVILEGE"), 4)
        self.assertEqual(script.count("AS OBJECT_RESET_ROLE"), 4)
        self.assertEqual(
            script.count(
                "OBJECT_GRANTEE_ROLE.ROLNAME IN ('PLATFORM_CONTROL', "
                "'PLATFORM_SUPERVISOR', 'PLATFORM_OPERATOR')"
            ),
            4,
        )
        self.assertLess(
            script.index("ACLEXPLODE(DATABASE.DATACL)"),
            script.index("GRANT CONNECT ON DATABASE PLATFORM"),
        )

    def test_role_validator_rejects_object_acl_sweep_mutations(self) -> None:
        script = self.role_script()
        mutations = {
            "missing grantor join": script.replace(
                "JOIN pg_roles AS object_grantor_role ON "
                "object_grantor_role.oid = privilege.grantor\n",
                "",
                1,
            ),
            "missing database catalog": script.replace(
                "CROSS JOIN LATERAL aclexplode(database.datacl) AS privilege",
                "CROSS JOIN LATERAL aclexplode(NULL::aclitem[]) AS privilege",
                1,
            ),
            "public only schema": script.replace(
                "namespace.nspname <> 'information_schema'",
                "namespace.nspname = 'public'",
                1,
            ),
            "missing sequence": script.replace("relation.relkind = 'S'", "FALSE", 1),
            "wrong grantor": script.replace(
                "object_grantor_role.rolname\n    ) AS object_revoke_privilege",
                "object_grantee_role.rolname\n    ) AS object_revoke_privilege",
                1,
            ),
            "wrong grantee": script.replace(
                "        object_grantee_role.rolname,\n"
                "        object_grantor_role.rolname\n"
                "    ) AS object_revoke_privilege",
                "        'PUBLIC',\n"
                "        object_grantor_role.rolname\n"
                "    ) AS object_revoke_privilege",
                1,
            ),
            "interposed statement": script.replace(
                "    ) AS object_revoke_privilege,\n"
                "    'RESET ROLE' AS object_reset_role",
                "    ) AS object_revoke_privilege,\n"
                "    'SELECT 1' AS object_extra_statement,\n"
                "    'RESET ROLE' AS object_reset_role",
                1,
            ),
            "widened table privileges": script.replace(
                "'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER')",
                "'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN')",
                1,
            ),
            "widened relation kinds": script.replace(
                "relation.relkind IN ('r', 'p', 'v', 'm', 'f')",
                "relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'i')",
                1,
            ),
            "omitted non-public schemas": script.replace(
                "  AND namespace.nspname !~ '^pg_'\n",
                "  AND namespace.nspname = 'public'\n",
                1,
            ),
            "comment-only database sweep": script.replace(
                "FROM pg_database AS database\n"
                "CROSS JOIN LATERAL aclexplode(database.datacl) AS privilege\n",
                "FROM pg_database AS database\n"
                "CROSS JOIN LATERAL aclexplode(NULL::aclitem[]) AS privilege\n"
                "-- CROSS JOIN LATERAL aclexplode(database.datacl) AS privilege\n",
                1,
            ),
        }
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                self.assertNotEqual(mutated, script)
                self.assertIn(
                    "platform role initializer residual object cleanup differs",
                    self.role_script_errors(mutated),
                )

    def test_role_validator_rejects_closed_artifact_byte_drift(self) -> None:
        errors = self.role_script_errors(self.role_script() + "\n# harmless byte drift\n")
        self.assertIn("platform role initializer digest differs", errors)

    def test_role_validator_normalizes_crlf_before_hashing(self) -> None:
        crlf_script = self.role_script().replace("\n", "\r\n")
        self.assertEqual(self.role_script_errors(crlf_script), [])

    def test_role_script_byte_normalization_rejects_non_shell_equivalent_bytes(self) -> None:
        lf = self.role_script().encode("utf-8")
        self.assertEqual(runtime_contract._normalize_platform_role_script(lf), lf.decode())
        self.assertEqual(
            runtime_contract._normalize_platform_role_script(lf.replace(b"\n", b"\r\n")),
            lf.decode(),
        )
        mixed = lf.replace(b"\n", b"\r\n", 1)
        self.assertEqual(runtime_contract._normalize_platform_role_script(mixed), lf.decode())

        parts = lf.split(b"\n", 2)
        invalid = {
            "lone CR": parts[0] + b"\r" + parts[1] + b"\n" + parts[2],
            "mixed with lone CR": mixed.replace(b"set -eu", b"set\r-eu", 1),
            "UTF-8 BOM": b"\xef\xbb\xbf" + lf,
            "NUL": lf[:8] + b"\x00" + lf[8:],
            "invalid UTF-8": b"\xff" + lf,
        }
        for name, content in invalid.items():
            with self.subTest(name=name):
                self.assertIsNone(runtime_contract._normalize_platform_role_script(content))

    def test_role_validator_rejects_column_original_grantor_mutations(self) -> None:
        script = self.role_script()
        mutations = {
            "removed grantor join": script.replace(
                "JOIN pg_roles AS column_grantor_role\n"
                "  ON column_grantor_role.oid = privilege.grantor\n",
                "",
            ),
            "current user only revoke": script.replace(
                "FROM %I GRANTED BY %I CASCADE",
                "FROM %I CASCADE",
            ),
            "wrong grantor field": script.replace(
                "        column_grantor_role.rolname\n    ) AS revoke_privilege",
                "        column_grantee_role.rolname\n    ) AS revoke_privilege",
            ),
            "retargeted grantee": script.replace(
                "        column_grantee_role.rolname,\n"
                "        column_grantor_role.rolname",
                "        'PUBLIC',\n        column_grantor_role.rolname",
            ),
        }
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                errors = self.role_script_errors(mutated)
                self.assertIn(
                    "platform role initializer residual column cleanup differs",
                    errors,
                )

    def test_role_validator_rejects_grantor_execution_context_mutations(self) -> None:
        script = self.role_script()
        mutations = {
            "missing set role": script.replace(
                "    format('SET ROLE %I', column_grantor_role.rolname) AS set_role,\n",
                "",
            ),
            "wrong set role source": script.replace(
                "format('SET ROLE %I', column_grantor_role.rolname)",
                "format('SET ROLE %I', column_grantee_role.rolname)",
            ),
            "missing reset role": script.replace(
                "    'RESET ROLE' AS reset_role\n",
                "",
            ),
            "reset before revoke": script.replace(
                "    format(\n"
                "        'REVOKE %s (%I) ON TABLE %I.%I FROM %I GRANTED BY %I CASCADE',\n",
                "    'RESET ROLE' AS reset_role,\n"
                "    format(\n"
                "        'REVOKE %s (%I) ON TABLE %I.%I FROM %I GRANTED BY %I CASCADE',\n",
            ).replace(
                "    ) AS revoke_privilege,\n    'RESET ROLE' AS reset_role\n",
                "    ) AS revoke_privilege\n",
            ),
            "extra statement between revoke and reset": script.replace(
                "    ) AS revoke_privilege,\n    'RESET ROLE' AS reset_role\n",
                "    ) AS revoke_privilege,\n"
                "    'SELECT 1' AS extra_statement,\n"
                "    'RESET ROLE' AS reset_role\n",
            ),
        }
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                errors = self.role_script_errors(mutated)
                self.assertIn(
                    "platform role initializer residual column cleanup differs",
                    errors,
                )

    def test_role_validator_rejects_grant_inventory_and_recipient_mutations(self) -> None:
        script = self.role_script()
        mutations = {
            "narrow extra update": script
            + "\nGRANT UPDATE (desired_state) ON TABLE public.runtime_instances "
            "TO platform_control;\n",
            "retarget control update": script.replace(
                "ON TABLE public.runtime_access_requests TO platform_control'",
                "ON TABLE public.runtime_access_requests TO PUBLIC'",
            ),
            "retarget select": script.replace(
                "TO platform_control, platform_supervisor',\n    table_name",
                "TO platform_control',\n    table_name",
                1,
            ),
            "supervisor extra table": script
            + "\nGRANT INSERT ON TABLE public.platform_catalog_revisions "
            "TO platform_supervisor;\n",
            "required grant only in comment": script.replace(
                "GRANT CONNECT ON DATABASE platform TO platform_control, platform_supervisor;",
                "-- GRANT CONNECT ON DATABASE platform TO platform_control, platform_supervisor;",
            ),
            "duplicate narrow grant": script
            + "\nGRANT UPDATE (status, result_code, completed_at) "
            "ON TABLE public.runtime_access_requests TO platform_control;\n",
        }
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                self.assertNotEqual(mutated, script)
                errors = self.role_script_errors(mutated)
                self.assertIn("platform role initializer grant inventory differs", errors)

    def test_role_validator_rejects_operator_guard_and_allowlist_mutations(self) -> None:
        script = self.role_script()
        mutations = {
            "missing ownership guard": (
                "platform role initializer ownership guard differs",
                script.replace(
                    "('platform_control', 'platform_supervisor', 'platform_operator')",
                    "('platform_control', 'platform_supervisor')",
                    1,
                ),
            ),
            "missing default owner guard": (
                "platform role initializer default authority guard differs",
                script.replace(
                    "default_owner_role.rolname = 'platform_operator'",
                    "FALSE",
                    1,
                ),
            ),
            "missing default grantee guard": (
                "platform role initializer default authority guard differs",
                script.replace(
                    "default_privilege.grantee = (\n"
                    "                SELECT oid FROM pg_roles WHERE "
                    "rolname = 'platform_operator'\n"
                    "            )",
                    "FALSE",
                    1,
                ),
            ),
            "widened update": (
                "platform role initializer grant inventory differs",
                script.replace(
                    "GRANT SELECT, INSERT ON TABLE public.%I TO platform_operator",
                    "GRANT SELECT, INSERT, UPDATE ON TABLE public.%I TO platform_operator",
                    1,
                ),
            ),
            "forbidden lifecycle table": (
                "platform role initializer grant inventory differs",
                script.replace(
                    "    ('runtime_audit_events')\n) AS operator_tables(table_name)",
                    "    ('runtime_audit_events'),\n"
                    "    ('runtime_lifecycle_jobs')\n"
                    ") AS operator_tables(table_name)",
                    1,
                ),
            ),
            "missing operator column sweep": (
                "platform role initializer residual column cleanup differs",
                script.replace(
                    "WHERE column_grantee_role.rolname IN\n"
                    "  ('platform_control', 'platform_supervisor', 'platform_operator')",
                    "WHERE column_grantee_role.rolname IN\n"
                    "  ('platform_control', 'platform_supervisor')",
                    1,
                ),
            ),
        }
        for name, (expected, mutated) in mutations.items():
            with self.subTest(name=name):
                self.assertNotEqual(mutated, script)
                self.assertIn(expected, self.role_script_errors(mutated))

    def test_role_validator_rejects_destructive_owned_commands(self) -> None:
        for command in (
            "REASSIGN OWNED BY platform_operator TO postgres;",
            "DROP OWNED BY platform_operator;",
        ):
            with self.subTest(command=command):
                errors = self.role_script_errors(self.role_script() + "\n" + command + "\n")
                self.assertIn("platform role initializer broadens database authority", errors)

    def test_role_validator_rejects_missing_reconciliation_clauses(self) -> None:
        script = self.role_script()
        mutations = {
            "control hardening": (
                "platform role initializer role hardening differs",
                script.replace(
                    "ALTER ROLE platform_control WITH LOGIN NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L",
                    "ALTER ROLE platform_control WITH LOGIN PASSWORD %L",
                ),
            ),
            "supervisor hardening": (
                "platform role initializer role hardening differs",
                script.replace(
                    "ALTER ROLE platform_supervisor WITH LOGIN NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L",
                    "ALTER ROLE platform_supervisor WITH LOGIN PASSWORD %L",
                ),
            ),
            "operator hardening": (
                "platform role initializer role hardening differs",
                script.replace(
                    "ALTER ROLE platform_operator WITH LOGIN NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L",
                    "ALTER ROLE platform_operator WITH LOGIN PASSWORD %L",
                ),
            ),
            "inbound membership": (
                "platform role initializer membership cleanup differs",
                script.replace("member_role.rolname = 'platform_control'", "FALSE", 1),
            ),
            "outbound membership": (
                "platform role initializer membership cleanup differs",
                script.replace("granted_role.rolname = 'platform_control'", "FALSE", 1),
            ),
            "supervisor inbound membership": (
                "platform role initializer membership cleanup differs",
                script.replace("member_role.rolname = 'platform_supervisor'", "FALSE", 1),
            ),
            "supervisor outbound membership": (
                "platform role initializer membership cleanup differs",
                script.replace("granted_role.rolname = 'platform_supervisor'", "FALSE", 1),
            ),
            "operator inbound membership": (
                "platform role initializer membership cleanup differs",
                script.replace("member_role.rolname = 'platform_operator'", "FALSE", 1),
            ),
            "operator outbound membership": (
                "platform role initializer membership cleanup differs",
                script.replace("granted_role.rolname = 'platform_operator'", "FALSE", 1),
            ),
            "column cleanup": (
                "platform role initializer residual column cleanup differs",
                script.replace(
                    "CROSS JOIN LATERAL aclexplode(attribute.attacl) AS privilege",
                    "CROSS JOIN LATERAL (SELECT NULL) AS privilege",
                ),
            ),
            "sequence revoke": (
                "platform role initializer revocation inventory differs",
                script.replace(
                    "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public "
                    "FROM platform_control, platform_supervisor, platform_operator CASCADE;",
                    "",
                ),
            ),
        }
        for name, (expected, mutated) in mutations.items():
            with self.subTest(name=name):
                errors = self.role_script_errors(mutated)
                self.assertIn(expected, errors)


if __name__ == "__main__":
    unittest.main()
