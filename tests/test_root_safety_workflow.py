from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "root-safety.yml"
PLATFORM_RUNBOOK_PATH = REPO_ROOT / "docs" / "operations" / "platform-control.md"
SETUP_COMPOSE_ACTION = (
    "docker/setup-compose-action@4eb059ff7f16592f9c84d5ca339c53cb7c5064e2"
)
SETUP_PNPM_ACTION = (
    "pnpm/action-setup@0ebf47130e4866e96fce0953f49152a61190b271"
)
SETUP_PNPM_ACTION_LINE = f"        uses: {SETUP_PNPM_ACTION} # v6.0.9"
PNPM_SETUP_STEP = "Install pnpm"
PNPM_VERSION = "11.9.0"
BACKEND_INSTALL_COMMAND = (
    'uv pip install --python .venv/bin/python -e "./freqtrade[develop,hyperopt]"'
)
BACKEND_INSTALL_STEP = "Install backend development dependencies"
ROOT_UNIT_STEP = "Run standard-library root unit tests"
ROOT_UNIT_COMMAND = 'python -S -m unittest discover -s tests -p "test_*.py" -v'
BOOTSTRAP_STEP = "Bootstrap ephemeral runtime"
FULL_RUNTIME_STEP = "Enforce full runtime contract"
BOOTSTRAPPED_RUNTIME_STEP = "Run bootstrapped runtime root tests"
BOOTSTRAPPED_RUNTIME_COMMAND = (
    "python -S -m unittest "
    "tests.test_trading_config_safety.TradingConfigSafetyTests -v"
)
RUNTIME_READY_ENV_LINE = '          ROOT_RUNTIME_TEST_READY: "1"'
RUNTIME_NOT_READY_ENV_LINE = '          ROOT_RUNTIME_TEST_READY: "0"'
FRONTEND_INSTALL_STEP = "Install FreqUI dependencies"
BACKEND_REGRESSION_STEP = "Run backend P0 regressions"
MARKET_CATALOG_BACKEND_SELECTORS = (
    "tests/markets/test_catalog.py",
    "tests/platform/test_catalog_repository.py",
    "tests/rpc/test_api_catalog.py",
    "tests/research/test_profiles.py",
)
RUNTIME_ROOT_STEP = "Run runtime-dependent root selector"
RUNTIME_ROOT_COMMAND = (
    "python -m unittest "
    "tests.test_trading_config_safety.TradingConfigSafetyTests."
    "test_actual_research_profile_paths_resolve_below_read_only_input -v"
)
BUILD_IMAGE_STEP = "Build integrated image"
PLATFORM_CI_STEPS = (
    "Start platform PostgreSQL",
    "Upgrade platform schema",
    "Run platform PostgreSQL integration tests",
    "Run Phase 2A backend regressions",
    "Verify platform-control least privilege",
    "Clean platform control plane",
)


def named_workflow_step(workflow: str, step_name: str) -> str:
    """Return exactly one six-space-indented GitHub Actions step block."""
    marker = f"      - name: {step_name}"
    lines = workflow.splitlines(keepends=True)
    matches = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n") == marker
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one workflow step named {step_name!r}, found {len(matches)}"
        )
    start = matches[0]
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("      - ")
        ),
        len(lines),
    )
    return "".join(lines[start:end])


def step_has_exact_line(step: str, line: str) -> bool:
    return line in step.splitlines()


def active_step_text(step: str) -> str:
    return "\n".join(
        line for line in step.splitlines() if not line.lstrip().startswith("#")
    )


def step_run_script(workflow: str, step_name: str) -> str:
    step = named_workflow_step(workflow, step_name)
    lines = step.splitlines()
    try:
        start = lines.index("        run: |") + 1
    except ValueError as error:
        raise AssertionError(f"step {step_name!r} must use a literal run script") from error
    script_lines: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith("          "):
            break
        script_lines.append(line[10:] if line.startswith("          ") else "")
    return "\n".join(script_lines) + "\n"


def split_shell_compound(command: str) -> list[str]:
    segments: list[str] = []
    start = 0
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(command):
        character = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        operator_length = 2 if command[index : index + 2] in {"&&", "||"} else 0
        if character == ";" or operator_length:
            segment = command[start:index].strip()
            if segment:
                segments.append(segment)
            index += operator_length or 1
            start = index
            continue
        index += 1
    segment = command[start:].strip()
    if segment:
        segments.append(segment)
    return segments


def executable_shell_statements(script: str) -> list[str]:
    statements: list[str] = []
    pending = ""
    heredoc_delimiter: str | None = None
    dead_depth = 0
    function_depth = 0
    for raw_line in script.splitlines():
        stripped = raw_line.strip()
        if heredoc_delimiter is not None:
            if stripped == heredoc_delimiter:
                heredoc_delimiter = None
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if function_depth:
            if stripped == "}":
                function_depth -= 1
            elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*\(\) \{$", stripped):
                function_depth += 1
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\(\) \{$", stripped):
            function_depth = 1
            continue
        if re.match(r"^if\s+(?:false|test\s+1\s+-eq\s+0)\s*;?\s*then$", stripped):
            dead_depth += 1
            continue
        if dead_depth:
            if re.match(r"^if\b", stripped):
                dead_depth += 1
            elif stripped == "fi":
                dead_depth -= 1
            continue
        pending = f"{pending} {stripped}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        heredoc = re.search(r"<<-?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*$", pending)
        stop = False
        for segment in split_shell_compound(pending):
            if re.match(r"^exit\s+0(?:\s*(?:#.*)?)?$", segment):
                stop = True
                break
            if re.match(r"^(?:echo|printf)\b", segment):
                continue
            statements.append(segment)
        pending = ""
        if heredoc is not None:
            heredoc_delimiter = heredoc.group(1)
        if stop:
            break
    if pending:
        statements.append(pending)
    return statements


def executable_sql_payloads(script: str) -> list[str]:
    payloads: list[str] = []
    active_statements = executable_shell_statements(script)
    lines = script.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.search(r"<<-?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*$", line)
        if match is None or "psql " not in line:
            index += 1
            continue
        header = line.strip()
        delimiter = match.group(1)
        payload: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip() != delimiter:
            sql_line = lines[index]
            if not sql_line.lstrip().startswith("--"):
                payload.append(sql_line)
            index += 1
        if any(header in statement for statement in active_statements):
            payloads.append("\n".join(payload))
        index += 1
    return payloads


def active_shell_function_bodies(script: str, function_name: str) -> list[str]:
    bodies: list[str] = []
    lines = script.splitlines()
    heredoc_delimiter: str | None = None
    dead_depth = 0
    index = 0
    function_pattern = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\) \{$")
    while index < len(lines):
        stripped = lines[index].strip()
        if heredoc_delimiter is not None:
            if stripped == heredoc_delimiter:
                heredoc_delimiter = None
            index += 1
            continue
        heredoc = re.search(r"<<-?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*$", stripped)
        if heredoc is not None:
            heredoc_delimiter = heredoc.group(1)
            index += 1
            continue
        if re.match(r"^if\s+(?:false|test\s+1\s+-eq\s+0)\s*;?\s*then$", stripped):
            dead_depth += 1
            index += 1
            continue
        if dead_depth:
            if re.match(r"^if\b", stripped):
                dead_depth += 1
            elif stripped == "fi":
                dead_depth -= 1
            index += 1
            continue
        function_match = function_pattern.match(stripped)
        if function_match is None:
            index += 1
            continue
        is_target = function_match.group(1) == function_name
        body: list[str] = []
        function_depth = 1
        index += 1
        while index < len(lines) and function_depth:
            nested = lines[index].strip()
            if function_pattern.match(nested):
                function_depth += 1
            elif nested == "}":
                function_depth -= 1
                if not function_depth:
                    break
            if is_target:
                body.append(lines[index])
            index += 1
        if index == len(lines):
            return []
        if is_target:
            bodies.append("\n".join(body) + "\n")
        index += 1
    return bodies


REVIEWED_DENIAL_HELPER_BODY = (
    '  role_name="$1"\n'
    '  probe_name="$2"\n'
    '  statement="$3"\n'
    "  set +e\n"
    "  docker exec platform-postgres-ci \\\n"
    '    psql --username "${role_name}" --dbname platform --set ON_ERROR_STOP=on \\\n'
    '    --command "BEGIN; ${statement}; ROLLBACK;" \\\n'
    '    >"${platform_ci_dir}/denied-${role_name}-${probe_name}.log" 2>&1\n'
    "  denied_status=$?\n"
    "  set -e\n"
    '  test "${denied_status}" -ne 0\n'
    '  grep --extended-regexp --quiet "permission denied|must be owner of" \\\n'
    '    "${platform_ci_dir}/denied-${role_name}-${probe_name}.log"\n'
)


CONTROL_TOPOLOGY_FRAGMENTS = (
    "docker create",
    "--name platform-control-ci",
    "--network freqtrade-platform-ingress-ci",
    "docker network connect freqtrade-platform-ci platform-control-ci",
    "control_networks=\"$(docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' platform-control-ci | sort | sed '/^$/d')\"",
    "test \"${control_networks}\" = $'freqtrade-platform-ci\\nfreqtrade-platform-ingress-ci'",
    'control_port_mapping="$(docker inspect',
    'test "${control_port_mapping}" = "127.0.0.1|8090"',
    "docker start platform-control-ci",
    'runtime_control_port_mapping="$(docker port platform-control-ci 8090/tcp)"',
    'test "${runtime_control_port_mapping}" = "127.0.0.1:8090"',
    '"http://127.0.0.1:8090/api/v2/ping"',
)


WORKFLOW_EXECUTABLE_CONTRACT = {
    PLATFORM_CI_STEPS[0]: (
        "docker network create --internal freqtrade-platform-ci",
        "docker network create freqtrade-platform-ingress-ci",
        "--publish 127.0.0.1:55432:5432",
        "docker network connect freqtrade-platform-ci platform-postgres-ci",
    ),
    PLATFORM_CI_STEPS[4]: (
        "docker network disconnect bridge platform-postgres-ci",
        "database_networks=\"$(docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' platform-postgres-ci | sort | sed '/^$/d')\"",
        'test "${database_networks}" = "freqtrade-platform-ci"',
        "docker exec platform-postgres-ci sh /docker-entrypoint-initdb.d/init-platform-roles.sh",
        "database_privileges=",
        'test "${database_privileges}" =',
        "schema_privileges=",
        'test "${schema_privileges}" =',
        "undeclared_schema_privilege_count=",
        'test "${undeclared_schema_privilege_count}" = "0"',
        "table_privileges=",
        'test "${table_privileges}" =',
        "undeclared_table_privilege_count=",
        'test "${undeclared_table_privilege_count}" = "0"',
        "column_privileges=",
        'test "${column_privileges}" =',
        "column_acl_inventory=",
        'test "${column_acl_inventory}" =',
        "object_acl_before=",
        'test "${object_acl_before}" = "8"',
        "object_acl_after=",
        'test "${object_acl_after}" = "0"',
        "object_effective_after=",
        'test "${object_effective_after}" = "f|f|f|f|f|f|f|f"',
        "sequence_privilege_count=",
        'test "${sequence_privilege_count}" = "0"',
        "ownership_count=",
        'test "${ownership_count}" = "0"',
        "grantable_count=",
        'test "${grantable_count}" = "0"',
        "acl_inventory_difference_count=",
        'test "${acl_inventory_difference_count}" = "0"',
        "psql --username platform_control --dbname platform",
        "psql --username platform_supervisor --dbname platform",
        'expect_role_denied platform_control temp "CREATE TEMP TABLE',
        'expect_role_denied platform_control create "CREATE TABLE',
        'expect_role_denied platform_control alter "ALTER TABLE',
        'expect_role_denied platform_control drop "DROP TABLE',
        'expect_role_denied platform_control delete "DELETE FROM',
        'expect_role_denied platform_control truncate "TRUNCATE TABLE',
        'expect_role_denied platform_control update "UPDATE runtime_instances',
        'expect_role_denied platform_supervisor temp "CREATE TEMP TABLE',
        'expect_role_denied platform_supervisor create "CREATE TABLE',
        'expect_role_denied platform_supervisor alter "ALTER TABLE',
        'expect_role_denied platform_supervisor drop "DROP TABLE',
        'expect_role_denied platform_supervisor delete "DELETE FROM',
        'expect_role_denied platform_supervisor truncate "TRUNCATE TABLE',
        'expect_role_denied platform_supervisor update "UPDATE platform_catalog_revisions',
        'expect_role_denied platform_control database-create "CREATE SCHEMA',
        'expect_role_denied platform_control delegated-table "DELETE FROM public.platform_ci_acl_table"',
        'expect_role_denied platform_supervisor delegated-sequence "SELECT setval(',
        'query_status="$(curl --config "${platform_ci_dir}/query-rejection.curl")"',
        'grep --quiet --fixed-strings --file "${platform_ci_dir}/query-sentinel"',
        "--user 1000:1000",
        "--read-only",
        "--init",
        "--cap-drop ALL",
        "--security-opt no-new-privileges:true",
        "--publish 127.0.0.1:8090:8090",
        '--mount type=bind,src="${platform_ci_dir}/api_password",dst=/run/secrets/api_password,readonly',
        '--mount type=bind,src="${platform_ci_dir}/jwt_secret_key",dst=/run/secrets/jwt_secret_key,readonly',
        '--mount type=bind,src="${platform_ci_dir}/platform_control_db_password",dst=/run/secrets/database_password,readonly',
        *CONTROL_TOPOLOGY_FRAGMENTS,
    ),
    PLATFORM_CI_STEPS[5]: (
        "docker rm -f platform-control-ci platform-postgres-ci",
        "docker network rm freqtrade-platform-ci",
        "docker network rm freqtrade-platform-ingress-ci",
        "docker ps --all --quiet --filter",
        "docker network inspect freqtrade-platform-ci",
        "docker network inspect freqtrade-platform-ingress-ci",
        "comm -13",
        "docker volume rm",
        'cmp "${platform_ci_dir}/volumes.before" "${platform_ci_dir}/volumes.after"',
        'rm -rf "${platform_ci_dir}"',
        'test ! -e "${platform_ci_dir}"',
        'exit "${cleanup_status}"',
    ),
}


def executable_statement_position(statements: list[str], fragment: str) -> int:
    assignment_fragment = fragment.endswith("=") or fragment.startswith(
        (
            'control_port_mapping="$(docker inspect',
            'control_networks="$(docker inspect',
            'database_networks="$(docker inspect',
            'runtime_control_port_mapping="$(docker port',
        )
    )
    offset = 0
    for statement in statements:
        assignment_only = re.match(
            r"^[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\")$", statement
        )
        if fragment in statement and (assignment_fragment or assignment_only is None):
            return offset + statement.index(fragment)
        offset += len(statement) + 1
    return -1


def validate_root_safety_workflow(workflow: str) -> list[str]:
    errors: list[str] = []
    scripts: dict[str, str] = {}
    for step_name in PLATFORM_CI_STEPS:
        try:
            scripts[step_name] = step_run_script(workflow, step_name)
        except AssertionError as error:
            errors.append(str(error))
    for step_name, fragments in WORKFLOW_EXECUTABLE_CONTRACT.items():
        script = scripts.get(step_name)
        if script is None:
            continue
        statements = executable_shell_statements(script)
        for fragment in fragments:
            position = executable_statement_position(statements, fragment)
            if position < 0:
                errors.append(f"{step_name}: missing executable statement: {fragment}")
        if step_name == PLATFORM_CI_STEPS[4]:
            topology_positions = [
                executable_statement_position(statements, fragment)
                for fragment in CONTROL_TOPOLOGY_FRAGMENTS
            ]
            if all(position >= 0 for position in topology_positions) and topology_positions != sorted(topology_positions):
                errors.append("Verify platform-control least privilege: control topology order differs")
            create_statements = [
                statement
                for statement in executable_shell_statements(script)
                if statement.startswith("docker create ")
            ]
            if (
                len(create_statements) != 1
                or create_statements[0].count("--mount ") != 3
                or create_statements[0].count("--publish ") != 1
                or create_statements[0].count("--network ") != 1
            ):
                errors.append(
                    "Verify platform-control least privilege: control create inventory differs"
                )
            network_mutations = [
                statement
                for statement in statements
                if re.search(
                    r"(?:^|\s)docker\s+network\s+(?:connect|disconnect)\s",
                    statement,
                )
            ]
            if network_mutations != [
                "docker network disconnect bridge platform-postgres-ci",
                "docker network connect freqtrade-platform-ci platform-control-ci",
            ]:
                errors.append(
                    "Verify platform-control least privilege: network mutation inventory differs"
                )
    least_privilege = scripts.get(PLATFORM_CI_STEPS[4], "")
    active_shell = "\n".join(executable_shell_statements(least_privilege))
    active_sql_payload = "\n".join(executable_sql_payloads(least_privilege))
    active_sql_payload = re.sub(r"'(?:''|[^'])*'", "''", active_sql_payload)
    for fragment in (
        "ALTER ROLE platform_control WITH SUPERUSER",
        "GRANT UPDATE (desired_state) ON TABLE public.runtime_instances",
        "GRANT CREATE ON DATABASE platform TO platform_ci_delegate WITH GRANT OPTION",
        "GRANT DELETE ON TABLE public.platform_ci_acl_table",
        "GRANT UPDATE ON SEQUENCE public.platform_ci_acl_sequence",
        "GRANT USAGE ON SCHEMA platform_ci_private",
        "GRANT SELECT ON TABLE platform_ci_private.probe",
    ):
        if fragment not in active_sql_payload:
            errors.append(f"least-privilege SQL payload missing: {fragment}")
    owner_changing_fragments = (
        "ALTER DATABASE platform OWNER",
        "ALTER SCHEMA public OWNER",
    )
    if any(fragment in active_sql_payload for fragment in owner_changing_fragments):
        errors.append("least-privilege contamination changes production owner")
    owner_grant_fragments = (
        "CREATE SCHEMA platform_ci_private AUTHORIZATION platform_ci_owner",
        "GRANT CREATE ON DATABASE platform TO platform_ci_delegate WITH GRANT OPTION",
        "GRANT CREATE ON SCHEMA public TO platform_ci_delegate WITH GRANT OPTION",
        "SET ROLE platform_ci_owner",
    )
    owner_grant_positions = [
        active_sql_payload.find(fragment) for fragment in owner_grant_fragments
    ]
    if (
        any(position < 0 for position in owner_grant_positions)
        or owner_grant_positions[1] >= owner_grant_positions[3]
        or owner_grant_positions[2] >= owner_grant_positions[3]
    ):
        errors.append("least-privilege owner grantor chain differs")
    expected_schema_grantor = (
        "SELECT 'schema', 'public', '', role_name, 'USAGE', "
        "'pg_database_owner', false"
    )
    if least_privilege.count(expected_schema_grantor) != 1:
        errors.append("least-privilege expected ACL grantor differs")
    for fragment in (
        "has_database_privilege(role_name, 'platform', 'TEMPORARY')",
        "has_column_privilege('platform_control'",
    ):
        if fragment not in active_shell:
            errors.append(f"least-privilege executable SQL query missing: {fragment}")

    sentinel_matcher = (
        'grep --quiet --fixed-strings --file "${platform_ci_dir}/query-sentinel"'
    )
    if active_shell.count(sentinel_matcher) != 1:
        errors.append("least-privilege query sentinel matcher differs")

    denial_bodies = active_shell_function_bodies(least_privilege, "expect_role_denied")
    if len(denial_bodies) != 1:
        errors.append("least-privilege active denial helper differs")
    else:
        denial_body = denial_bodies[0].replace("\r\n", "\n")
        denial_statements = executable_shell_statements(denial_body)
        denial_text = "\n".join(denial_statements)
        denial_fragments = (
            'psql --username "${role_name}" --dbname platform --set ON_ERROR_STOP=on',
            "denied_status=$?",
            'test "${denied_status}" -ne 0',
            'grep --extended-regexp --quiet "permission denied|must be owner of"',
        )
        denial_positions = [
            next(
                (
                    index
                    for index, statement in enumerate(denial_statements)
                    if fragment in statement
                ),
                -1,
            )
            for fragment in denial_fragments
        ]
        role_assignments = [
            (index, statement)
            for index, statement in enumerate(denial_statements)
            if re.match(r"^role_name=", statement)
        ]
        if (
            denial_body != REVIEWED_DENIAL_HELPER_BODY
            or any(position < 0 for position in denial_positions)
            or denial_positions != sorted(denial_positions)
            or denial_positions[1] != denial_positions[0] + 1
            or len(role_assignments) != 1
            or role_assignments[0][1] != 'role_name="$1"'
            or role_assignments[0][0] >= denial_positions[0]
            or "psql --username postgres" in denial_text
            or any(
                re.match(r"^return\s+0(?:\s*(?:#.*)?)?$", statement)
                for statement in denial_statements
            )
        ):
            errors.append("least-privilege active denial helper differs")

    contamination = (
        "ALTER ROLE platform_control WITH SUPERUSER CREATEDB CREATEROLE "
        "INHERIT REPLICATION BYPASSRLS;"
    )
    reconciliation = (
        "docker exec platform-postgres-ci sh "
        "/docker-entrypoint-initdb.d/init-platform-roles.sh"
    )
    effective_inventory = "effective_after="
    boundary_positions = [
        least_privilege.find(fragment)
        for fragment in (contamination, reconciliation, effective_inventory)
    ]
    if all(position >= 0 for position in boundary_positions) and (
        boundary_positions != sorted(boundary_positions)
    ):
        errors.append("least-privilege contamination reconciliation order differs")
    denial_call_positions = [
        least_privilege.find(fragment)
        for fragment in WORKFLOW_EXECUTABLE_CONTRACT[PLATFORM_CI_STEPS[4]]
        if fragment.startswith("expect_role_denied ")
    ]
    if (
        all(position >= 0 for position in boundary_positions[:2])
        and all(position >= 0 for position in denial_call_positions)
        and any(
            position <= max(boundary_positions[:2])
            for position in denial_call_positions
        )
    ):
        errors.append("least-privilege fixed-role denial order differs")

    cleanup = scripts.get(PLATFORM_CI_STEPS[5], "")
    cleanup_statements = executable_shell_statements(cleanup)
    drift_line = 'test ! -s "${platform_ci_dir}/volumes.created" || cleanup_status=1'
    drift_check = 'test ! -s "${platform_ci_dir}/volumes.created"'
    drift_indices = [
        index
        for index in range(len(cleanup_statements) - 1)
        if cleanup_statements[index] == drift_check
        and cleanup_statements[index + 1] == "cleanup_status=1"
    ]
    cleanup_order = [
        executable_statement_position(cleanup_statements, fragment)
        for fragment in ("comm -13", drift_check, "docker volume rm")
    ]
    if (
        drift_line not in (line.strip() for line in cleanup.splitlines())
        or len(drift_indices) != 1
        or any(position < 0 for position in cleanup_order)
        or cleanup_order != sorted(cleanup_order)
    ):
        errors.append("cleanup created-volume drift status differs")
    return errors


def run_cleanup_with_stubbed_volumes(
    before: tuple[str, ...],
    detected: tuple[str, ...],
    final: tuple[str, ...],
    *,
    failed_removal: str = "",
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    cleanup_script = step_run_script(workflow, PLATFORM_CI_STEPS[5])

    def inventory(names: tuple[str, ...]) -> str:
        return "".join(f"{name}\n" for name in names)

    stub_environment = {
        "STUB_BEFORE_VOLUMES": inventory(before),
        "STUB_DETECTED_VOLUMES": inventory(detected),
        "STUB_FINAL_VOLUMES": inventory(final),
        "STUB_FAILED_REMOVAL": failed_removal,
    }
    exports = "".join(
        f"export {name}={shlex.quote(value)}\n"
        for name, value in stub_environment.items()
    )
    stub = r"""
RUNNER_TEMP="$(mktemp -d)"
trap 'rm -rf "${RUNNER_TEMP}"' EXIT
platform_ci_dir="${RUNNER_TEMP}/platform-control-ci"
mkdir -p "${platform_ci_dir}"
printf '%s' "${STUB_BEFORE_VOLUMES}" > "${platform_ci_dir}/volumes.before"
STUB_CURRENT_VOLUMES="${RUNNER_TEMP}/current-volumes"
printf '%s' "${STUB_DETECTED_VOLUMES}" > "${STUB_CURRENT_VOLUMES}"

docker() {
  if test "$1" = "rm"; then
    return 0
  fi
  if test "$1" = "network" && test "$2" = "rm"; then
    return 0
  fi
  if test "$1" = "ps"; then
    return 0
  fi
  if test "$1" = "network" && test "$2" = "inspect"; then
    return 1
  fi
  if test "$1" = "volume" && test "$2" = "ls"; then
    cat "${STUB_CURRENT_VOLUMES}"
    return 0
  fi
  if test "$1" = "volume" && test "$2" = "rm"; then
    printf 'STUB_REMOVED:%s\n' "$3" >&2
    if test "$3" = "${STUB_FAILED_REMOVAL}"; then
      return 1
    fi
    printf '%s' "${STUB_FINAL_VOLUMES}" > "${STUB_CURRENT_VOLUMES}"
    return 0
  fi
  return 99
}
"""
    raw_result = subprocess.run(
        [shutil.which("bash") or "bash", "-s"],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        input=(exports + stub + cleanup_script).replace("\r\n", "\n").encode(),
        capture_output=True,
        check=False,
    )
    stderr = raw_result.stderr.decode()
    removed = [
        line.removeprefix("STUB_REMOVED:")
        for line in stderr.splitlines()
        if line.startswith("STUB_REMOVED:")
    ]
    result = subprocess.CompletedProcess(
        raw_result.args,
        raw_result.returncode,
        raw_result.stdout.decode(),
        stderr,
    )
    return result, removed


class RootSafetyWorkflowTests(unittest.TestCase):
    def test_github_expression_run_blocks_stay_below_service_limit(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        literal_run_blocks = re.findall(
            r"(?ms)^        run: \|\r?\n(.*?)(?=^      - |\Z)",
            workflow,
        )

        self.assertTrue(literal_run_blocks)
        for run_block in literal_run_blocks:
            if "${{" in run_block:
                self.assertLessEqual(len(run_block), 21_000)

    @unittest.skipIf(
        os.environ.get("ROOT_STDLIB_CHILD") == "1",
        "avoid recursively spawning the isolated import check",
    )
    def test_workflow_test_module_imports_with_standard_library_only(self) -> None:
        environment = os.environ.copy()
        environment["ROOT_STDLIB_CHILD"] = "1"
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-m",
                "unittest",
                "tests.test_root_safety_workflow",
                "-v",
            ],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_named_workflow_step_requires_exactly_one_peer_marker(self) -> None:
        workflow = (
            "steps:\n"
            "      - name: Target\n"
            "        run: python target.py\n"
            "\n"
            "      - name: Peer\n"
            "        run: python peer.py\n"
        )

        self.assertEqual(
            named_workflow_step(workflow, "Target"),
            "      - name: Target\n        run: python target.py\n\n",
        )
        with self.assertRaisesRegex(AssertionError, "found 0"):
            named_workflow_step(workflow, "Missing")
        with self.assertRaisesRegex(AssertionError, "found 2"):
            named_workflow_step(workflow + workflow, "Target")

    def test_root_unit_gate_precedes_bootstrap_and_all_dependency_installs(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        root_unit_step = named_workflow_step(workflow, ROOT_UNIT_STEP)

        self.assertTrue(
            step_has_exact_line(root_unit_step, f"        run: {ROOT_UNIT_COMMAND}")
        )
        self.assertTrue(step_has_exact_line(root_unit_step, RUNTIME_NOT_READY_ENV_LINE))
        root_unit_index = workflow.index(root_unit_step)
        for later_step_name in (
            BOOTSTRAP_STEP,
            BACKEND_INSTALL_STEP,
            PNPM_SETUP_STEP,
            FRONTEND_INSTALL_STEP,
        ):
            with self.subTest(later_step=later_step_name):
                later_step = named_workflow_step(workflow, later_step_name)
                self.assertLess(root_unit_index, workflow.index(later_step))

    def test_rejects_root_gate_command_in_comment_or_unrelated_step(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        mutated_workflow = workflow.replace(
            f"        run: {ROOT_UNIT_COMMAND}",
            "        run: python -m unittest tests.test_root_safety_workflow -v\n"
            f"        # run: {ROOT_UNIT_COMMAND}\n\n"
            "      - name: Unrelated root tests\n"
            f"        run: {ROOT_UNIT_COMMAND}",
            1,
        )
        root_unit_step = named_workflow_step(mutated_workflow, ROOT_UNIT_STEP)

        self.assertFalse(
            step_has_exact_line(root_unit_step, f"        run: {ROOT_UNIT_COMMAND}")
        )

    def test_runtime_dependent_selector_follows_backend_regressions(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        full_runtime = named_workflow_step(workflow, FULL_RUNTIME_STEP)
        install = named_workflow_step(workflow, BACKEND_INSTALL_STEP)
        regressions = named_workflow_step(workflow, BACKEND_REGRESSION_STEP)
        runtime_selector = named_workflow_step(workflow, RUNTIME_ROOT_STEP)
        frontend_setup = named_workflow_step(workflow, PNPM_SETUP_STEP)

        self.assertTrue(
            step_has_exact_line(
                runtime_selector,
                f"        run: {RUNTIME_ROOT_COMMAND}",
            )
        )
        self.assertTrue(step_has_exact_line(runtime_selector, RUNTIME_READY_ENV_LINE))
        self.assertLess(workflow.index(full_runtime), workflow.index(install))
        self.assertLess(workflow.index(install), workflow.index(regressions))
        self.assertLess(workflow.index(regressions), workflow.index(runtime_selector))
        self.assertLess(workflow.index(runtime_selector), workflow.index(frontend_setup))

    def test_bootstrapped_runtime_class_runs_before_backend_install(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        bootstrap = named_workflow_step(workflow, BOOTSTRAP_STEP)
        full_runtime = named_workflow_step(workflow, FULL_RUNTIME_STEP)
        runtime_class = named_workflow_step(workflow, BOOTSTRAPPED_RUNTIME_STEP)
        install = named_workflow_step(workflow, BACKEND_INSTALL_STEP)

        self.assertTrue(
            step_has_exact_line(
                runtime_class,
                f"        run: {BOOTSTRAPPED_RUNTIME_COMMAND}",
            )
        )
        self.assertTrue(step_has_exact_line(runtime_class, RUNTIME_READY_ENV_LINE))
        self.assertLess(workflow.index(bootstrap), workflow.index(full_runtime))
        self.assertLess(workflow.index(full_runtime), workflow.index(runtime_class))
        self.assertLess(workflow.index(runtime_class), workflow.index(install))

    def test_installs_backend_test_runtime_dependencies(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        install_step = named_workflow_step(workflow, BACKEND_INSTALL_STEP)

        self.assertTrue(
            step_has_exact_line(install_step, f"          {BACKEND_INSTALL_COMMAND}")
        )

    def test_backend_regressions_execute_market_catalog_selectors(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = named_workflow_step(workflow, BACKEND_REGRESSION_STEP)
        pytest_command, separator, _ = step.partition("          ruff check \\\n")

        self.assertTrue(separator)

        for selector in MARKET_CATALOG_BACKEND_SELECTORS:
            with self.subTest(selector=selector):
                self.assertIn(f"            {selector} \\\n", pytest_command)

    def test_rejects_market_catalog_selector_only_present_in_comment(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        selector = MARKET_CATALOG_BACKEND_SELECTORS[0]
        mutated = workflow.replace(
            f"            {selector} \\\n",
            f"            # {selector} \\\n",
            1,
        )
        step = named_workflow_step(mutated, BACKEND_REGRESSION_STEP)
        pytest_command, separator, _ = step.partition("          ruff check \\\n")

        self.assertTrue(separator)
        self.assertNotIn(f"            {selector} \\\n", pytest_command)

    def test_rejects_backend_dependency_command_only_present_in_comment(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        mutated_workflow = workflow.replace(
            BACKEND_INSTALL_COMMAND,
            'uv pip install --python .venv/bin/python -e "./freqtrade[develop]"\n'
            f"          # {BACKEND_INSTALL_COMMAND}",
            1,
        )
        install_step = named_workflow_step(mutated_workflow, BACKEND_INSTALL_STEP)

        self.assertFalse(
            step_has_exact_line(install_step, f"          {BACKEND_INSTALL_COMMAND}")
        )

    def test_pins_compatible_compose_before_first_compose_consumer(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        setup = (
            f"- uses: {SETUP_COMPOSE_ACTION} # v2.3.0\n"
            "        with:\n"
            "          version: v5.1.4"
        )

        self.assertIn(setup, workflow)
        self.assertLess(workflow.index(setup), workflow.index(ROOT_UNIT_STEP))

    def test_installs_declared_pnpm_with_pinned_action(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        setup = named_workflow_step(workflow, PNPM_SETUP_STEP)

        self.assertTrue(step_has_exact_line(setup, SETUP_PNPM_ACTION_LINE))
        self.assertTrue(step_has_exact_line(setup, f"          version: {PNPM_VERSION}"))

    def test_rejects_pnpm_version_only_present_in_comment(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        mutated_workflow = workflow.replace(
            f"          version: {PNPM_VERSION}",
            "          version: 10.32.1\n"
            f"          # version: {PNPM_VERSION}",
            1,
        )
        setup = named_workflow_step(mutated_workflow, PNPM_SETUP_STEP)

        self.assertFalse(
            step_has_exact_line(setup, f"          version: {PNPM_VERSION}")
        )

    def test_rejects_pinned_action_only_present_in_unrelated_step(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        mutated_workflow = workflow.replace(
            f"      - name: {PNPM_SETUP_STEP}\n"
            f"{SETUP_PNPM_ACTION_LINE}",
            "      - name: Unrelated pnpm setup\n"
            f"{SETUP_PNPM_ACTION_LINE}\n"
            "        with:\n"
            f"          version: {PNPM_VERSION}\n\n"
            f"      - name: {PNPM_SETUP_STEP}\n"
            "        uses: pnpm/action-setup@unpinned # v6.0.9",
            1,
        )
        setup = named_workflow_step(mutated_workflow, PNPM_SETUP_STEP)

        self.assertFalse(step_has_exact_line(setup, SETUP_PNPM_ACTION_LINE))

    def test_platform_ci_steps_are_unique_and_follow_the_image_build_in_order(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        previous_position = workflow.index(named_workflow_step(workflow, BUILD_IMAGE_STEP))

        for step_name in PLATFORM_CI_STEPS:
            with self.subTest(step=step_name):
                step = named_workflow_step(workflow, step_name)
                position = workflow.index(step)
                self.assertLess(previous_position, position)
                previous_position = position

    def test_platform_ci_cleanup_is_unconditional(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cleanup = named_workflow_step(workflow, PLATFORM_CI_STEPS[-1])

        self.assertTrue(step_has_exact_line(cleanup, "        if: always()"))

    def test_platform_workflow_satisfies_reusable_executable_contract(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertEqual(validate_root_safety_workflow(workflow), [])

    def test_reusable_platform_contract_rejects_dead_echoed_and_missing_commands(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        mutations = {
            "echoed control connect": workflow.replace(
                "docker network connect freqtrade-platform-ci platform-control-ci",
                "echo 'docker network connect freqtrade-platform-ci platform-control-ci'",
                1,
            ),
            "quoted control connect": workflow.replace(
                "docker network connect freqtrade-platform-ci platform-control-ci",
                "dead_text='docker network connect freqtrade-platform-ci platform-control-ci'",
                1,
            ),
            "removed control ingress": workflow.replace(
                "--network freqtrade-platform-ingress-ci",
                "--network removed-platform-ingress",
                1,
            ),
            "unreachable control create": workflow.replace(
                "          docker create \\",
                "          exit 0\n          docker create \\",
                1,
            ),
            "compound unreachable control create": workflow.replace(
                "          docker create \\",
                "          echo harmless; exit 0\n          docker create \\",
                1,
            ),
            "removed postgres transition": workflow.replace(
                "docker network disconnect bridge platform-postgres-ci",
                "removed-postgres-transition",
                1,
            ),
            "removed control port assertion": workflow.replace(
                'test "${control_port_mapping}" = "127.0.0.1|8090"',
                "removed-control-port-assertion",
                1,
            ),
            "removed ACL reconciliation": "removed-role-reconciliation".join(
                workflow.rsplit(
                    "docker exec platform-postgres-ci sh /docker-entrypoint-initdb.d/init-platform-roles.sh",
                    1,
                )
            ),
            "quoted ACL contamination": workflow.replace(
                "ALTER ROLE platform_control WITH SUPERUSER CREATEDB CREATEROLE INHERIT REPLICATION BYPASSRLS;",
                "SELECT 'ALTER ROLE platform_control WITH SUPERUSER CREATEDB CREATEROLE INHERIT REPLICATION BYPASSRLS';",
                1,
            ),
            "removed effective deny": workflow.replace(
                'expect_role_denied platform_control temp "CREATE TEMP TABLE',
                'removed-deny platform_control temp "CREATE TEMP TABLE',
                1,
            ),
            "admin fixed-role substitution": workflow.replace(
                "psql --username platform_control --dbname platform",
                "psql --username postgres --dbname platform",
                1,
            ),
            "removed targeted volume deletion": workflow.replace(
                "docker volume rm",
                "removed-volume-delete",
                1,
            ),
            "removed volume equality": workflow.replace(
                'cmp "${platform_ci_dir}/volumes.before" "${platform_ci_dir}/volumes.after"',
                "removed-volume-equality",
                1,
            ),
            "removed artifact assertion": workflow.replace(
                'test ! -e "${platform_ci_dir}"',
                "removed-artifact-assertion",
                1,
            ),
        }
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                self.assertNotEqual(mutated, workflow)
                self.assertTrue(validate_root_safety_workflow(mutated))

    def test_reusable_platform_contract_rejects_compound_safety_text(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        required_command = (
            "docker network connect freqtrade-platform-ci platform-control-ci"
        )
        mutations = {
            "semicolon echo": workflow.replace(
                required_command,
                f":; echo '{required_command}'",
                1,
            ),
            "and printf": workflow.replace(
                required_command,
                f"true && printf '%s\\n' '{required_command}'",
                1,
            ),
        }

        for name, mutated in mutations.items():
            with self.subTest(name=name):
                self.assertNotEqual(mutated, workflow)
                self.assertTrue(validate_root_safety_workflow(mutated))

    def test_reusable_platform_contract_validates_active_denial_helper(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        least_privilege_step = named_workflow_step(workflow, PLATFORM_CI_STEPS[4])
        helper = re.search(
            r"(?ms)^          expect_role_denied\(\) \{\n.*?^          \}\n",
            least_privilege_step,
        )
        self.assertIsNotNone(helper)
        helper_text = helper.group(0) if helper is not None else ""
        probe_anchor = "            set +e\n            docker exec platform-postgres-ci \\\n"
        mutations = {
            "postgres substitution": workflow.replace(
                'psql --username "${role_name}" --dbname platform',
                "psql --username postgres --dbname platform",
                1,
            ),
            "unconditional true": workflow.replace(
                helper_text,
                "          expect_role_denied() {\n            true\n          }\n",
                1,
            ),
            "unconditional return": workflow.replace(
                helper_text,
                "          expect_role_denied() {\n            return 0\n          }\n",
                1,
            ),
            "uncalled wrapper": workflow.replace(
                helper_text,
                "          uncalled_denial_helper() {\n"
                + "".join(f"  {line}\n" for line in helper_text.splitlines())
                + "          }\n",
                1,
            ),
            "second role assignment": workflow.replace(
                'role_name="$1"',
                'role_name="$1"\n            role_name=postgres',
                1,
            ),
            "compound role assignment": workflow.replace(
                'role_name="$1"',
                'role_name="$1"; role_name=postgres',
                1,
            ),
            "defaulted role assignment": workflow.replace(
                'role_name="$1"',
                'role_name="${1:-postgres}"',
                1,
            ),
            "role reassignment before probe": workflow.replace(
                probe_anchor,
                "            set +e\n"
                "            role_name=platform_supervisor\n"
                "            docker exec platform-postgres-ci \\",
                1,
            ),
            **{
                f"{statement.split()[0]} role mutation": workflow.replace(
                    probe_anchor,
                    "            set +e\n"
                    f"            {statement}\n"
                    "            docker exec platform-postgres-ci \\",
                    1,
                )
                for statement in (
                    "local role_name=postgres",
                    "export role_name=postgres",
                    "declare role_name=postgres",
                    "typeset role_name=postgres",
                    "readonly role_name=postgres",
                    "eval role_name=postgres",
                )
            },
        }

        for name, mutated in mutations.items():
            with self.subTest(name=name):
                self.assertNotEqual(mutated, workflow)
                self.assertIn(
                    "least-privilege active denial helper differs",
                    validate_root_safety_workflow(mutated),
                )

    def test_denial_helper_pin_ignores_inactive_text_outside_helper(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        marker = "          docker create \\\n"
        mutated = workflow.replace(
            marker,
            "          # role_name=postgres outside the reviewed helper\n"
            "          python - <<'PY'\n"
            "          role_name=postgres\n"
            "          PY\n"
            "          if false; then\n"
            "            role_name=postgres\n"
            "          fi\n"
            + marker,
            1,
        )

        self.assertNotEqual(mutated, workflow)
        self.assertEqual(validate_root_safety_workflow(mutated), [])

    def test_reusable_platform_contract_rejects_privilege_boundary_reordering(
        self,
    ) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = named_workflow_step(workflow, PLATFORM_CI_STEPS[4])
        reconciliation = (
            "          docker exec platform-postgres-ci sh "
            "/docker-entrypoint-initdb.d/init-platform-roles.sh\n"
        )
        after_effective_inventory = '          test "${effective_after}" = "f|f"\n'
        reordered_reconciliation = step.replace(reconciliation, "", 1).replace(
            after_effective_inventory,
            after_effective_inventory + reconciliation,
            1,
        )

        helper_start = step.index("          expect_role_denied() {\n")
        denial_end_marker = (
            '          expect_role_denied platform_supervisor update "UPDATE '
            'platform_catalog_revisions SET payload = payload"\n'
        )
        helper_end = step.index(denial_end_marker, helper_start) + len(
            denial_end_marker
        )
        denial_block = step[helper_start:helper_end]
        without_denials = step[:helper_start] + step[helper_end:]
        contamination_boundary = without_denials.index(
            "          docker exec --interactive platform-postgres-ci \\\n"
        )
        reordered_denials = (
            without_denials[:contamination_boundary]
            + denial_block
            + without_denials[contamination_boundary:]
        )
        mutations = (
            workflow.replace(step, reordered_reconciliation, 1),
            workflow.replace(step, reordered_denials, 1),
        )

        for mutated in mutations:
            with self.subTest(order=mutated.index("expect_role_denied()")):
                self.assertNotEqual(mutated, workflow)
                self.assertTrue(validate_root_safety_workflow(mutated))

    def test_reusable_platform_contract_rejects_all_deny_and_identity_mutations(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        deny_fragments = tuple(
            fragment
            for fragment in WORKFLOW_EXECUTABLE_CONTRACT[PLATFORM_CI_STEPS[4]]
            if fragment.startswith("expect_role_denied ")
        )
        identity_fragments = (
            "psql --username platform_control --dbname platform",
            "psql --username platform_supervisor --dbname platform",
        )
        for fragment in (*deny_fragments, *identity_fragments):
            with self.subTest(fragment=fragment):
                mutated = workflow.replace(fragment, "removed-fixed-role-probe", 1)
                self.assertNotEqual(mutated, workflow)
                self.assertTrue(validate_root_safety_workflow(mutated))

    def test_reusable_platform_contract_rejects_transition_and_cleanup_mutations(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        fragments = (
            *WORKFLOW_EXECUTABLE_CONTRACT[PLATFORM_CI_STEPS[0]],
            *WORKFLOW_EXECUTABLE_CONTRACT[PLATFORM_CI_STEPS[5]],
        )
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                mutated = workflow.replace(fragment, "removed-transition-or-cleanup", 1)
                self.assertNotEqual(mutated, workflow)
                self.assertTrue(validate_root_safety_workflow(mutated))

    def test_reusable_platform_contract_ignores_heredoc_and_uncalled_function_text(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        marker = "docker network connect freqtrade-platform-ci platform-control-ci"
        removed = workflow.replace(marker, "removed-control-connect", 1)
        mutations = (
            removed.replace(
                "          docker create \\",
                "          python - <<'PY'\n"
                f"          {marker}\n"
                "          PY\n"
                "          docker create \\",
                1,
            ),
            removed.replace(
                "          docker create \\",
                "          dead_contract_text() {\n"
                f"            {marker}\n"
                "          }\n"
                "          docker create \\",
                1,
            ),
        )
        for mutated in mutations:
            with self.subTest(kind="non-executable text"):
                self.assertTrue(validate_root_safety_workflow(mutated))

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_platform_run_scripts_pass_bash_syntax_validation(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        for step_name in PLATFORM_CI_STEPS:
            script = step_run_script(workflow, step_name)
            expanded = re.sub(r"\$\{\{.*?\}\}", "reviewed-ci-value", script)
            with self.subTest(step=step_name):
                result = subprocess.run(
                    [shutil.which("bash") or "bash", "-n"],
                    input=expanded.encode("utf-8"),
                    capture_output=True,
                    check=False,
                )
                output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
                self.assertEqual(result.returncode, 0, output)

    def test_platform_postgres_step_is_file_secreted_loopback_and_volume_free(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[0]))
        required = (
            'platform_ci_dir="${RUNNER_TEMP}/platform-control-ci"',
            'install -d -m 0700 "${platform_ci_dir}"',
            "postgres_admin_password \\",
            "platform_control_db_password \\",
            "platform_supervisor_db_password \\",
            "api_password \\",
            "jwt_secret_key",
            '"ft_userdata/secrets/platform/${secret_name}"',
            'docker volume ls --quiet | sort > "${platform_ci_dir}/volumes.before"',
            "docker network create --internal freqtrade-platform-ci",
            "docker network create freqtrade-platform-ingress-ci",
            "--name platform-postgres-ci",
            "--publish 127.0.0.1:55432:5432",
            "--tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=512m",
            "POSTGRES_PASSWORD_FILE=/run/secrets/postgres_admin_password",
            "postgres:17.10-alpine",
            "docker network connect freqtrade-platform-ci platform-postgres-ci",
            "for attempt in $(seq 1 60); do",
            "CREATE DATABASE platform_test_ci",
            'PGPASSFILE=${platform_ci_dir}/pgpass',
            "PLATFORM_TEST_POSTGRES_URL=postgresql+psycopg://postgres@127.0.0.1:55432/platform_test_ci",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, step)
        self.assertNotIn("POSTGRES_PASSWORD=", step)
        self.assertNotIn("docker compose", step)
        self.assertNotIn("docker network disconnect bridge platform-postgres-ci", step)

    def test_platform_upgrade_and_backend_selectors_are_executable(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        upgrade = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[1]))
        postgres = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[2]))
        regressions = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[3]))

        for fragment in (
            "PlatformDatabaseSettings",
            "settings.sqlalchemy_url()",
            'command.upgrade(config, "head")',
            "ScriptDirectory.from_config(config).get_current_head()",
            "SqlCatalogRepository",
            "default_catalog_snapshot",
            "docker exec platform-postgres-ci sh /docker-entrypoint-initdb.d/init-platform-roles.sh",
        ):
            self.assertIn(fragment, upgrade)
        for selector in (
            "tests/platform/test_platform_migrations.py",
            "tests/platform/test_runtime_repository.py",
        ):
            self.assertIn(selector, postgres)
        for selector in (
            "tests/markets/test_catalog.py",
            "tests/platform/test_database.py",
            "tests/platform/test_catalog_repository.py",
            "tests/platform/test_runtime_domain.py",
            "tests/platform/test_runtime_service.py",
            "tests/platform_control",
            "tests/rpc/test_api_catalog.py",
        ):
            self.assertIn(selector, regressions)
        self.assertIn("ruff check \\", regressions)

    def test_least_privilege_step_reconciles_roles_and_probes_hardened_http(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[4]))
        required = (
            "ALTER ROLE platform_control WITH SUPERUSER CREATEDB CREATEROLE INHERIT REPLICATION BYPASSRLS",
            "ALTER ROLE platform_supervisor WITH SUPERUSER CREATEDB CREATEROLE INHERIT REPLICATION BYPASSRLS",
            "column_grantor_role.rolname",
            "ORDER BY column_grantor_role.rolname",
            "object_acl_before=",
            'test "${object_acl_before}" = "8"',
            "object_acl_after=",
            'test "${object_acl_after}" = "0"',
            "object_effective_after=",
            'test "${object_effective_after}" = "f|f|f|f|f|f|f|f"',
            "expect_role_denied platform_control update",
            "expect_role_denied platform_control database-create",
            "expect_role_denied platform_supervisor delegated-sequence",
            "docker network disconnect bridge platform-postgres-ci",
            "database_networks=\"$(docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' platform-postgres-ci | sort | sed '/^$/d')\"",
            'printf \'platform PostgreSQL networks after isolation: %s\\n\' "${database_networks}"',
            'test "${database_networks}" = "freqtrade-platform-ci"',
            "--name platform-control-ci",
            "--user 1000:1000",
            "--read-only",
            "--init",
            "--cap-drop ALL",
            "--security-opt no-new-privileges:true",
            "REVIEWED_IMAGE_ID: ${{ steps.reviewed-image.outputs.image_id }}",
            '"${REVIEWED_IMAGE_ID}"',
            "--network freqtrade-platform-ingress-ci",
            "docker network connect freqtrade-platform-ci platform-control-ci",
            "--publish 127.0.0.1:8090:8090",
            "--netrc-file",
            '"http://127.0.0.1:8090/api/v2/ping"',
            '"http://127.0.0.1:8090/api/v2/catalog"',
            '"http://127.0.0.1:8090/api/v2/runtime-instances"',
            'query_status="$(curl --config "${platform_ci_dir}/query-rejection.curl")"',
            'grep --quiet --fixed-strings --file "${platform_ci_dir}/query-sentinel"',
            "sentinel = secrets.token_urlsafe(32)",
            "os.chmod(sentinel_file, 0o600)",
            "os.chmod(config_file, 0o600)",
            '{"detail": "unexpected_query_parameters"}',
            '"/openapi.json"',
            '"/docs"',
            '"/api/v2/runtime-instances/ci-instance/start"',
            '"/api/v2/runtime-access/ci-instance"',
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, step)
        self.assertLess(
            step.index("SET ROLE platform_ci_delegate"),
            step.index("ALTER ROLE platform_control WITH SUPERUSER"),
        )
        self.assertLess(
            step.index("GRANT UPDATE (desired_state) ON TABLE public.runtime_instances\n"
                       "            TO platform_ci_downstream"),
            step.index("ALTER ROLE platform_control WITH SUPERUSER"),
        )
        for forbidden in ("docker.sock", "ft_userdata/runtime", "docker compose"):
            self.assertNotIn(forbidden, step)

    def test_contamination_preserves_production_owners_and_postgres_grantor(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[4]))

        self.assertNotIn("ALTER DATABASE platform OWNER", step)
        self.assertNotIn("ALTER SCHEMA public OWNER", step)
        self.assertIn(
            "CREATE SCHEMA platform_ci_private AUTHORIZATION platform_ci_owner",
            step,
        )
        database_grant = (
            "GRANT CREATE ON DATABASE platform TO platform_ci_delegate WITH GRANT OPTION"
        )
        schema_grant = (
            "GRANT CREATE ON SCHEMA public TO platform_ci_delegate WITH GRANT OPTION"
        )
        self.assertIn(database_grant, step)
        self.assertIn(schema_grant, step)
        self.assertLess(step.index(database_grant), step.index("SET ROLE platform_ci_owner"))
        self.assertLess(step.index(schema_grant), step.index("SET ROLE platform_ci_owner"))
        self.assertIn("'CONNECT', 'postgres', false", step)
        self.assertIn("'USAGE', 'pg_database_owner', false", step)
        self.assertNotIn("'schema', 'public', '', role_name, 'USAGE', 'postgres'", step)

        for owner_change in (
            "ALTER DATABASE platform OWNER TO platform_ci_owner;",
            "ALTER SCHEMA public OWNER TO platform_ci_owner;",
        ):
            mutated = workflow.replace(
                "CREATE ROLE platform_ci_delegate NOLOGIN;",
                f"CREATE ROLE platform_ci_delegate NOLOGIN;\n          {owner_change}",
                1,
            )
            self.assertIn(
                "least-privilege contamination changes production owner",
                validate_root_safety_workflow(mutated),
            )
        wrong_grantor = workflow.replace(
            "'USAGE', 'pg_database_owner', false",
            "'USAGE', 'postgres', false",
            1,
        )
        self.assertIn(
            "least-privilege expected ACL grantor differs",
            validate_root_safety_workflow(wrong_grantor),
        )

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_query_sentinel_matcher_is_quiet_and_non_reflective(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        script = step_run_script(workflow, PLATFORM_CI_STEPS[4])
        lines = script.splitlines()
        start = next(
            index
            for index, line in enumerate(lines)
            if line.startswith("if grep ") and "query-sentinel" in line
        )
        end = next(
            index for index in range(start + 1, len(lines)) if lines[index] == "fi"
        )
        checker = "\n".join(lines[start : end + 1]) + "\n"

        self.assertIn("grep --quiet --fixed-strings --file", checker)
        sentinel = "synthetic-private-sentinel-value"

        def run_checker(log_content: str) -> subprocess.CompletedProcess[bytes]:
            setup = (
                'platform_ci_dir="$(mktemp -d)"\n'
                'trap \'rm -rf "${platform_ci_dir}"\' EXIT\n'
                "umask 077\n"
                f"printf %s {shlex.quote(sentinel)} > \"${{platform_ci_dir}}/query-sentinel\"\n"
                f"printf %s {shlex.quote(log_content)} > \"${{platform_ci_dir}}/query-container.log\"\n"
                'test "$(stat -c %a "${platform_ci_dir}/query-sentinel")" = "600"\n'
            )
            return subprocess.run(
                [shutil.which("bash") or "bash", "-s"],
                input=(setup + checker).encode(),
                capture_output=True,
                check=False,
            )

        matched = run_checker(f"prefix {sentinel} suffix\n")
        self.assertNotEqual(matched.returncode, 0)
        self.assertEqual(matched.stdout, b"")
        self.assertEqual(matched.stderr, b"")
        self.assertNotIn(sentinel, checker)

        unmatched = run_checker("no matching content\n")
        self.assertEqual(unmatched.returncode, 0)
        self.assertEqual(unmatched.stdout, b"")
        self.assertEqual(unmatched.stderr, b"")

        mutated = workflow.replace(
            "grep --quiet --fixed-strings --file",
            "grep --fixed-strings --file",
            1,
        )
        self.assertIn(
            "least-privilege query sentinel matcher differs",
            validate_root_safety_workflow(mutated),
        )

    def test_control_final_topology_is_exact_and_mutation_resistant(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertEqual(validate_root_safety_workflow(workflow), [])
        for fragment in CONTROL_TOPOLOGY_FRAGMENTS:
            with self.subTest(removed=fragment):
                mutated = workflow.replace(
                    fragment, "removed-control-topology-command", 1
                )
                self.assertNotEqual(mutated, workflow)
                self.assertTrue(validate_root_safety_workflow(mutated))

        first, second = CONTROL_TOPOLOGY_FRAGMENTS[:2]
        reordered = workflow.replace(first, "control-topology-placeholder", 1)
        reordered = reordered.replace(second, first, 1)
        reordered = reordered.replace("control-topology-placeholder", second, 1)
        self.assertIn(
            "Verify platform-control least privilege: control topology order differs",
            validate_root_safety_workflow(reordered),
        )

        network_mutations = (
            workflow.replace(
                "          control_port_mapping=",
                "          docker network connect bridge platform-control-ci\n"
                "          control_port_mapping=",
                1,
            ),
            workflow.replace(
                '          test "${runtime_control_port_mapping}" = "127.0.0.1:8090"\n\n'
                "          ready=0",
                '          test "${runtime_control_port_mapping}" = "127.0.0.1:8090"\n'
                "          docker network connect rogue-network platform-control-ci\n"
                "          ready=0",
                1,
            ),
        )
        for mutated in network_mutations:
            with self.subTest(kind="network mutation after exact assertion"):
                self.assertIn(
                    "Verify platform-control least privilege: network mutation inventory differs",
                    validate_root_safety_workflow(mutated),
                )

    def test_platform_cleanup_removes_exact_resources_and_asserts_no_volume_drift(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cleanup = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[5]))

        for fragment in (
            "docker rm -f platform-control-ci platform-postgres-ci",
            "docker network rm freqtrade-platform-ci",
            "docker network rm freqtrade-platform-ingress-ci",
            'docker volume ls --quiet | sort > "${platform_ci_dir}/volumes.after"',
            'cmp "${platform_ci_dir}/volumes.before" "${platform_ci_dir}/volumes.after"',
            'rm -rf "${platform_ci_dir}"',
        ):
            self.assertIn(fragment, cleanup)

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_platform_cleanup_preserves_created_volume_drift_failure(self) -> None:
        no_drift, no_drift_removed = run_cleanup_with_stubbed_volumes(
            ("existing-a", "existing-b"),
            ("existing-a", "existing-b"),
            ("existing-a", "existing-b"),
        )
        self.assertEqual(no_drift.returncode, 0, no_drift.stdout + no_drift.stderr)
        self.assertEqual(no_drift_removed, [])

        cleaned_drift, cleaned_drift_removed = run_cleanup_with_stubbed_volumes(
            ("existing-a", "existing-b"),
            ("created-one", "existing-a", "existing-b"),
            ("existing-a", "existing-b"),
        )
        self.assertNotEqual(cleaned_drift.returncode, 0)
        self.assertEqual(cleaned_drift_removed, ["created-one"])

        failed_delete, failed_delete_removed = run_cleanup_with_stubbed_volumes(
            ("existing-a", "existing-b"),
            ("created-one", "existing-a", "existing-b"),
            ("created-one", "existing-a", "existing-b"),
            failed_removal="created-one",
        )
        self.assertNotEqual(failed_delete.returncode, 0)
        self.assertEqual(failed_delete_removed, ["created-one"])

    def test_reusable_contract_requires_created_volume_drift_status(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        marker = 'test ! -s "${platform_ci_dir}/volumes.created" || cleanup_status=1'
        self.assertIn(marker, workflow)
        mutated = workflow.replace(marker, "removed-created-volume-drift-status", 1)
        self.assertTrue(validate_root_safety_workflow(mutated))

    def test_platform_contract_text_in_comments_or_unrelated_steps_is_rejected(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        marker = "--security-opt no-new-privileges:true"
        step = named_workflow_step(workflow, PLATFORM_CI_STEPS[4])
        mutated_step = step.replace(marker, f"# {marker}", 1)
        mutated = workflow.replace(step, mutated_step, 1)
        mutated += f"\n      - name: Unrelated platform text\n        run: echo '{marker}'\n"
        self.assertTrue(validate_root_safety_workflow(mutated))

    def test_platform_runbook_keeps_production_start_fail_closed(self) -> None:
        self.assertTrue(PLATFORM_RUNBOOK_PATH.is_file())
        runbook = PLATFORM_RUNBOOK_PATH.read_text(encoding="utf-8")

        for statement in (
            "Production platform start/stop is not exposed in Phase 2A.",
            "Raw `docker compose up` is unsupported and bypasses review gates.",
            "`compose_runtime` remains platform config-only.",
            "A Supervisor or dedicated infrastructure launcher must land before production use.",
        ):
            self.assertIn(statement, runbook)


if __name__ == "__main__":
    unittest.main()
