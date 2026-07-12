from __future__ import annotations

import copy
import json
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

    def test_platform_compose_has_exact_isolated_inventory(self) -> None:
        self.assertEqual(set(self.compose["services"]), {"platform-postgres", "platform-control"})
        self.assertEqual(
            self.compose["networks"],
            {
                "platform-db": {
                    "name": "freqtrade-cn_platform-db",
                    "ipam": {},
                    "internal": True,
                }
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
                "platform_control_api_password",
                "platform_control_jwt_secret",
            },
        )
        self.assertEqual(self.errors(), [])

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

    def test_platform_control_has_no_docker_or_runtime_state_mount(self) -> None:
        service = self.compose["services"]["platform-control"]
        rendered = json.dumps(service, sort_keys=True)
        self.assertNotIn("docker.sock", rendered)
        self.assertNotIn("ft_userdata/runtime", rendered)
        self.assertNotIn(str(REPO_ROOT), rendered)
        self.assertEqual(service.get("volumes", []), [])
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
        self.assertIn("REVOKE CREATE ON DATABASE platform FROM PUBLIC", script)
        self.assertIn("REVOKE CREATE ON SCHEMA public FROM PUBLIC", script)
        self.assertIn("UPDATE (status, result_code, completed_at)", script)
        self.assertNotIn("ALTER DEFAULT PRIVILEGES", script.upper())
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

    def test_role_validator_requires_exact_public_temporary_revoke(self) -> None:
        safe_script = self.role_script()
        self.assertIn(
            "REVOKE TEMPORARY ON DATABASE platform FROM PUBLIC;", safe_script
        )
        self.assertEqual(self.role_script_errors(safe_script), [])

        mutations = {
            "removed": safe_script.replace(
                "REVOKE TEMPORARY ON DATABASE platform FROM PUBLIC;\n", "", 1
            ),
            "redirected": safe_script.replace(
                "REVOKE TEMPORARY ON DATABASE platform FROM PUBLIC;",
                "REVOKE TEMPORARY ON DATABASE platform FROM platform_control;",
                1,
            ),
        }
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                self.assertIn(
                    "platform role initializer database authority differs",
                    self.role_script_errors(mutated),
                )

    def test_role_password_normalization_removes_only_one_terminal_newline(self) -> None:
        script = self.role_script().lower()
        self.assertNotRegex(script, r"\b(?:btrim|trim)\s*\(")
        self.assertEqual(script.count("right(secret_value, 2) = e'\\r\\n'"), 2)
        self.assertEqual(script.count("left(secret_value, -2)"), 2)
        self.assertEqual(script.count("right(secret_value, 1) = e'\\n'"), 2)
        self.assertEqual(script.count("left(secret_value, -1)"), 2)

    def test_role_script_resets_exact_attributes_and_both_membership_directions(self) -> None:
        script = " ".join(self.role_script().upper().split())
        attributes = (
            "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
            "NOREPLICATION NOBYPASSRLS PASSWORD %L"
        )
        self.assertEqual(script.count(attributes), 2)
        for role in ("PLATFORM_CONTROL", "PLATFORM_SUPERVISOR"):
            self.assertIn(f"MEMBER_ROLE.ROLNAME = '{role}'", script)
            self.assertIn(f"GRANTED_ROLE.ROLNAME = '{role}'", script)
        self.assertGreaterEqual(script.count("PG_AUTH_MEMBERS"), 4)
        self.assertEqual(
            script.count(
                "JOIN PG_ROLES AS GRANTOR_ROLE ON GRANTOR_ROLE.OID = MEMBERSHIP.GRANTOR"
            ),
            4,
        )
        self.assertEqual(script.count("GRANTED BY %I CASCADE"), 5)
        self.assertGreaterEqual(script.count(" CASCADE"), 5)

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
            "COLUMN_GRANTEE_ROLE.ROLNAME IN ('PLATFORM_CONTROL', 'PLATFORM_SUPERVISOR')",
            script,
        )
        cleanup = script.index("CROSS JOIN LATERAL ACLEXPLODE(ATTRIBUTE.ATTACL)")
        first_grant = script.index("GRANT CONNECT ON DATABASE PLATFORM")
        self.assertLess(cleanup, first_grant)

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
                    "FROM platform_control, platform_supervisor CASCADE;",
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
