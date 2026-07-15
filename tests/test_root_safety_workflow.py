from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
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
BUILD_OPERATOR_IMAGE_STEP = "Build platform operator image"
PLATFORM_CI_STEPS = (
    "Start platform PostgreSQL",
    "Upgrade platform schema",
    "Run platform PostgreSQL integration tests",
    "Run Phase 2B backend regressions",
    "Verify platform-control least privilege",
    "Clean platform control plane",
)
OPERATOR_CI_STEPS = (
    "Run platform-operator CLI acceptance",
    "Verify platform-operator least privilege",
)
ALL_PLATFORM_CI_STEPS = (
    *PLATFORM_CI_STEPS[:4],
    *OPERATOR_CI_STEPS,
    *PLATFORM_CI_STEPS[4:],
)
SECRET_SCAN_STEP = "Scan current committed trees for secrets"
GITLEAKS_IMAGE = (
    "ghcr.io/gitleaks/gitleaks:v8.27.2@sha256:"
    "ebfeb6fd4f2c37fa371d3731ebfa662fdf80f93cd37d3b4771bb82263edff8d0"
)
REVIEWED_SECRET_SCAN_SCRIPT = "\n".join(
    (
        "set -euo pipefail",
        'scan_root="${RUNNER_TEMP}/current-trees"',
        'audit_root="${RUNNER_TEMP}/gitleaks-audit"',
        "export scan_root",
        'export checkout_root="${GITHUB_WORKSPACE}"',
        'mkdir -p "${scan_root}" "${audit_root}"',
        'git archive HEAD | tar -x -C "${scan_root}"',
        "git submodule foreach --recursive '",
        '  relative_path="$(realpath --relative-to="${checkout_root}" "${PWD}")"',
        '  destination="${scan_root}/${relative_path}"',
        '  mkdir -p "${destination}"',
        '  git archive HEAD | tar -x -C "${destination}"',
        "'",
        'mv "${scan_root}/.gitleaksignore" "${audit_root}/expected-ignore"',
        ': > "${audit_root}/empty-ignore"',
        "set +e",
        "docker run --rm \\",
        '  -v "${scan_root}:/repo:ro" \\',
        '  -v "${audit_root}:/audit" \\',
        "  --workdir /repo \\",
        f"  {GITLEAKS_IMAGE} \\",
        "  dir . --redact --no-banner \\",
        "  --gitleaks-ignore-path /audit/empty-ignore \\",
        "  --report-format json --report-path /audit/findings.json",
        "unfiltered_status=$?",
        "set -e",
        'test "${unfiltered_status}" -eq 1',
        "python tools/gitleaks_fingerprint_audit.py \\",
        '  "${audit_root}/findings.json" "${audit_root}/expected-ignore"',
        'mv "${audit_root}/expected-ignore" "${scan_root}/.gitleaksignore"',
        "set +e",
        "docker run --rm \\",
        '  -v "${scan_root}:/repo:ro" \\',
        "  --workdir /repo \\",
        f"  {GITLEAKS_IMAGE} \\",
        "  dir . --redact --no-banner \\",
        "  --gitleaks-ignore-path /repo/.gitleaksignore",
        "filtered_status=$?",
        "set -e",
        'test "${filtered_status}" -eq 0',
        'mutation_path="${scan_root}/.ci-gitleaks-mutation"',
        'printf \'api_key = "%s"\\n\' '
        '"$(head -c 48 /dev/urandom | base64 | tr -d \'\\n\')" '
        '> "${mutation_path}"',
        "set +e",
        "docker run --rm \\",
        '  -v "${scan_root}:/repo:ro" \\',
        "  --workdir /repo \\",
        f"  {GITLEAKS_IMAGE} \\",
        "  dir . --redact --no-banner \\",
        "  --gitleaks-ignore-path /repo/.gitleaksignore",
        "mutation_status=$?",
        "set -e",
        'rm -f "${mutation_path}"',
        'test "${mutation_status}" -eq 1',
        "",
    )
)
REVIEWED_SECRET_SCAN_STEP = (
    f"      - name: {SECRET_SCAN_STEP}\n"
    "        shell: bash\n"
    "        run: |\n"
    + "".join(
        f"          {line}\n" for line in REVIEWED_SECRET_SCAN_SCRIPT.splitlines()
    )
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


def operator_output_validator_script(workflow: str) -> str:
    script = step_run_script(workflow, OPERATOR_CI_STEPS[0])
    start_marker = '  "${GITHUB_SHA}" <<\'PY\'\n'
    if script.count(start_marker) != 1:
        raise AssertionError("expected exactly one operator output validator")
    validator = script.split(start_marker, 1)[1]
    end_marker = "\nPY\n"
    if end_marker not in validator:
        raise AssertionError("operator output validator is not terminated")
    return validator.split(end_marker, 1)[0] + "\n"


def canonical_operator_documents() -> tuple[str, list[dict[str, object]]]:
    root_commit = "a" * 40
    component_commit = "b" * 40
    digest = "c" * 64
    template_revision = f"template-{digest}"
    registration: dict[str, object] = {
        "adapter_template_revision_id": template_revision,
        "catalog_revision_id": "builtin-market-catalog-v2",
        "desired_state": "stopped",
        "instance_id": "phase2-spot-paper-probe",
        "lifecycle_status": "registered",
        "runtime_spec_revision_id": f"runtime-spec-{digest}",
        "secret_reference_ids": [
            "secret-phase2-spot-paper-probe-api-password-v1",
            "secret-phase2-spot-paper-probe-jwt-secret-v1",
            "secret-phase2-spot-paper-probe-ws-token-v1",
        ],
        "state_allocation_id": "state-phase2-spot-paper-probe-v1",
    }
    validate: dict[str, object] = {
        "backend_commit": component_commit,
        "config_blob_digest": digest,
        "frontend_commit": component_commit,
        "root_commit": root_commit,
        "safety_policy_digest": digest,
        "status": "valid",
        "strategies_commit": component_commit,
        "strategy_class_name": "SampleStrategy",
        "strategy_digest": digest,
        "template_id": "freqtrade-paper-probe-v1",
        "template_payload_digest": digest,
    }
    publish: dict[str, object] = {
        "adapter_template_revision_id": template_revision,
        "backend_commit": component_commit,
        "frontend_commit": component_commit,
        "root_commit": root_commit,
        "status": "active",
        "strategies_commit": component_commit,
        "template_id": "freqtrade-paper-probe-v1",
        "template_payload_digest": digest,
    }
    return root_commit, [validate, publish, registration, registration, registration]


def run_operator_output_validator(
    documents: list[dict[str, object]], root_commit: str
) -> subprocess.CompletedProcess[str]:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    validator = operator_output_validator_script(workflow)
    with tempfile.TemporaryDirectory() as temporary_directory:
        paths = []
        for index, document in enumerate(documents):
            path = Path(temporary_directory) / f"operator-{index}.json"
            path.write_text(
                json.dumps(
                    document,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            paths.append(str(path))
        return subprocess.run(
            [sys.executable, "-", *paths, root_commit],
            cwd=REPO_ROOT,
            input=validator,
            text=True,
            capture_output=True,
            check=False,
        )


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
    OPERATOR_CI_STEPS[0]: (
        "operator_database_networks_before=",
        "git clone --no-local --no-checkout",
        "git checkout --detach",
        "submodule update --init --recursive",
        'sudo chown 1000:1000 "${operator_checkout}"',
        'sudo chown -R 1000:1000 "${operator_checkout}/.git"',
        "validate_first=",
        "validate_second=",
        "publish_first=",
        "publish_second=",
        "register_first=",
        "register_second=",
        "compile_first=",
        "compile_second=",
        "status_first=",
        "status_second=",
        "docker network connect --alias platform-postgres freqtrade-cn_platform-db platform-postgres-ci",
        "docker network disconnect freqtrade-cn_platform-db platform-postgres-ci",
        "docker network rm freqtrade-cn_platform-db",
        "operator_database_networks=",
        'test "${operator_database_networks}" = "${operator_database_networks_before}"',
        "sudo rm -rf",
    ),
    OPERATOR_CI_STEPS[1]: (
        "operator_pgpass=",
        "role_state=",
        'test "${role_state}" = "t|f|f|f|f|f|f"',
        "database_schema_state=",
        'test "${database_schema_state}" = "t|f|f|t|f"',
        "operator_table_state=",
        'test "${operator_table_state}" = "0"',
        "direct_operator_table_acl=",
        'test "${direct_operator_table_acl}" = "14|14|0"',
        "direct_column_acl_count=",
        'test "${direct_column_acl_count}" = "0"',
        "operator_membership_count=",
        'test "${operator_membership_count}" = "0"',
        "operator_default_acl_count=",
        'test "${operator_default_acl_count}" = "0"',
        "direct_operator_database_acl_difference=",
        'test "${direct_operator_database_acl_difference}" = "0"',
        "direct_operator_schema_acl_difference=",
        'test "${direct_operator_schema_acl_difference}" = "0"',
        "direct_operator_relation_acl_difference=",
        'test "${direct_operator_relation_acl_difference}" = "0"',
        "direct_operator_sequence_acl_count=",
        'test "${direct_operator_sequence_acl_count}" = "0"',
        "direct_operator_routine_acl_count=",
        'test "${direct_operator_routine_acl_count}" = "0"',
        'expect_operator_denied temp "CREATE TEMP TABLE',
        'expect_operator_denied create "CREATE SCHEMA',
        'expect_operator_denied update "UPDATE runtime_instances',
        'expect_operator_denied delete "DELETE FROM runtime_instances"',
        'expect_operator_denied truncate "TRUNCATE TABLE runtime_instances"',
        'expect_operator_denied secret-version "SELECT * FROM secret_version_metadata"',
        'expect_operator_denied lifecycle "SELECT * FROM runtime_lifecycle_jobs"',
        "owner_reconcile_status=$?",
        'test "${owner_reconcile_status}" -ne 0',
        "null_acl_effective=",
        'test "${null_acl_effective}" = "t|t"',
        "residual_operator_authority=",
        'test "${residual_operator_authority}" = "f|f|f|f|f|f"',
        "public_default_acl_count=",
        'test "${public_default_acl_count}" = "0"',
        "public_effective_acl_count=",
        'test "${public_effective_acl_count}" = "0"',
        "expect_operator_denied sequence",
        "expect_operator_denied routine",
        'expect_operator_denied maintain "REINDEX TABLE public.runtime_instances"',
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
        'if ! platform_containers="$(docker ps --all --quiet',
        "verify_network_absent freqtrade-platform-ci",
        "verify_network_absent freqtrade-platform-ingress-ci",
        "comm -13",
        "docker volume rm",
        'cmp "${platform_ci_dir}/volumes.before" "${platform_ci_dir}/volumes.after"',
        'rm -rf "${platform_ci_dir}"',
        'test ! -e "${platform_ci_dir}"',
        'docker image rm "${operator_tag}"',
        'docker tag "${operator_id}" "${operator_tag}"',
        'remove_operator_image_id "${reviewed_operator_image_id}"',
        'cmp "${operator_image_baseline}" "${operator_image_current}"',
        'exit "${cleanup_status}"',
    ),
    SECRET_SCAN_STEP: (
        'git archive HEAD | tar -x -C "${scan_root}"',
        "git submodule foreach --recursive",
        'mv "${scan_root}/.gitleaksignore" "${audit_root}/expected-ignore"',
        GITLEAKS_IMAGE,
        "dir . --redact --no-banner",
        "unfiltered_status=$?",
        'test "${unfiltered_status}" -eq 1',
        "python tools/gitleaks_fingerprint_audit.py",
        "filtered_status=$?",
        'test "${filtered_status}" -eq 0',
        "mutation_path=",
        "mutation_status=$?",
        'test "${mutation_status}" -eq 1',
    ),
}

OPERATOR_OUTPUT_CONTRACT = (
    "forbidden_field_names = {",
    "def exposes_forbidden_data(value):",
    "key.casefold() in forbidden_field_names",
    're.search(r"/(?:opt|run)/", value, re.I)',
    "if exposes_forbidden_data(document):",
    "validate_keys = {",
    "publish_keys = {",
    "registration_keys = {",
    "if set(validate) != validate_keys",
    "if set(publish) != publish_keys",
    "if set(register) != registration_keys",
    'validate["strategy_class_name"] != "SampleStrategy"',
    'register["catalog_revision_id"] != "builtin-market-catalog-v2"',
    'register["state_allocation_id"] != "state-phase2-spot-paper-probe-v1"',
    'runtime_spec_revision_id.startswith("runtime-spec-")',
    "secret-phase2-spot-paper-probe-api-password-v1",
    "secret-phase2-spot-paper-probe-jwt-secret-v1",
    "secret-phase2-spot-paper-probe-ws-token-v1",
    "commit_pattern.fullmatch",
)


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
    for step_name in (*ALL_PLATFORM_CI_STEPS, SECRET_SCAN_STEP):
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
        if step_name == SECRET_SCAN_STEP:
            if named_workflow_step(workflow, step_name) != REVIEWED_SECRET_SCAN_STEP:
                errors.append("secret scan reviewed step differs")
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

    operator_privilege = scripts.get(OPERATOR_CI_STEPS[1], "")
    operator_sql_payload = "\n".join(executable_sql_payloads(operator_privilege))
    for fragment in (
        "CREATE FUNCTION public.platform_operator_owned_probe()",
        "OWNER TO platform_operator",
        "GRANT EXECUTE ON FUNCTION public.platform_operator_owned_probe()",
        "GRANT MAINTAIN ON TABLE public.runtime_instances TO platform_operator",
        "GRANT TEMPORARY, CREATE ON DATABASE platform TO PUBLIC",
        "GRANT CREATE ON SCHEMA public TO PUBLIC",
        "GRANT SELECT ON TABLE public.runtime_instances TO PUBLIC",
        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres",
    ):
        if fragment not in operator_sql_payload:
            errors.append(f"operator least-privilege SQL payload missing: {fragment}")
    operator_psql_bodies = active_shell_function_bodies(
        operator_privilege, "operator_psql"
    )
    if len(operator_psql_bodies) != 1 or any(
        fragment not in operator_psql_bodies[0]
        for fragment in (
            'PGPASSFILE="${operator_pgpass}"',
            "--host 127.0.0.1",
            "--port 55432",
            "--username platform_operator",
            "--dbname platform",
        )
    ):
        errors.append("operator login helper differs")
    operator_denial_bodies = active_shell_function_bodies(
        operator_privilege, "expect_operator_denied"
    )
    if len(operator_denial_bodies) != 1 or any(
        fragment not in operator_denial_bodies[0]
        for fragment in (
            "operator_psql --command",
            "denied_status=$?",
            'test "${denied_status}" -ne 0',
            "permission denied|must be owner of",
        )
    ):
        errors.append("operator denial helper differs")
    default_acl = operator_sql_payload.find(
        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres"
    )
    null_probe = operator_sql_payload.find(
        "CREATE FUNCTION public.platform_operator_public_null_probe()"
    )
    if default_acl < 0 or null_probe < 0 or default_acl >= null_probe:
        errors.append("operator null ACL contamination order differs")
    operator_acceptance = scripts.get(OPERATOR_CI_STEPS[0], "")
    for fragment in OPERATOR_OUTPUT_CONTRACT:
        if fragment not in operator_acceptance:
            errors.append(f"operator output contract missing: {fragment}")
    topology_fragments = (
        "operator_database_networks_before=",
        "docker network connect --alias platform-postgres",
        "docker network disconnect freqtrade-cn_platform-db",
        "operator_database_networks=",
        'test "${operator_database_networks}" = "${operator_database_networks_before}"',
    )
    topology_positions = [operator_acceptance.find(value) for value in topology_fragments]
    if any(position < 0 for position in topology_positions) or topology_positions != sorted(topology_positions):
        errors.append("operator database topology restoration order differs")

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
    cleanup_script = cleanup_script.replace(
        "${{ steps.reviewed-operator-image.outputs.image_id }}",
        "reviewed-operator-image-id",
    )

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
    printf 'Error response from daemon: No such network: %s\n' "$3" >&2
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


def run_cleanup_with_stubbed_docker_failure(
    failure: str,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    cleanup_script = step_run_script(workflow, PLATFORM_CI_STEPS[5]).replace(
        "${{ steps.reviewed-operator-image.outputs.image_id }}",
        "",
    )
    export_failure = f"export STUB_DOCKER_FAILURE={shlex.quote(failure)}\n"
    stub = r'''
RUNNER_TEMP="$(mktemp -d)"
baseline_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
printf 'freqtrade-cn-operator:preexisting|%s\n' "${baseline_id}" \
  > "${RUNNER_TEMP}/platform-operator-images.before"
printf '%s\n' "${baseline_id}" \
  > "${RUNNER_TEMP}/platform-operator-image-ids.before"
printf 'ready\n' > "${RUNNER_TEMP}/platform-operator-images.ready"
image_mutations="${RUNNER_TEMP}/image-mutations"
: > "${image_mutations}"
cleanup_actions="${RUNNER_TEMP}/cleanup-actions"
: > "${cleanup_actions}"
image_list_count_file="${RUNNER_TEMP}/image-list-count"
image_inspect_count_file="${RUNNER_TEMP}/image-inspect-count"
docker_ps_count_file="${RUNNER_TEMP}/docker-ps-count"
printf '0\n' > "${image_list_count_file}"
printf '0\n' > "${image_inspect_count_file}"
printf '0\n' > "${docker_ps_count_file}"
trap 'cat "${image_mutations}"; cat "${cleanup_actions}"; rm -rf "${RUNNER_TEMP}"' EXIT

docker() {
  if test "$1" = "ps"; then
    docker_ps_count="$(( $(cat "${docker_ps_count_file}") + 1 ))"
    printf '%s\n' "${docker_ps_count}" > "${docker_ps_count_file}"
    if test "${STUB_DOCKER_FAILURE}" = "docker-ps" \
      || { test "${STUB_DOCKER_FAILURE}" = "docker-ps-final" \
        && test "${docker_ps_count}" -ge 2; }; then
      printf 'docker daemon unavailable\n' >&2
      return 125
    fi
    return 0
  fi
  if test "$1" = "rm"; then
    printf 'cleanup:%s\n' "$*" >> "${cleanup_actions}"
    return 0
  fi
  if test "$1" = "network" && test "$2" = "disconnect"; then return 0; fi
  if test "$1" = "network" && test "$2" = "rm"; then return 0; fi
  if test "$1" = "network" && test "$2" = "inspect"; then
    if test "${STUB_DOCKER_FAILURE}" = "network-inspect"; then
      printf 'docker daemon unavailable\n' >&2
      return 125
    fi
    printf 'Error response from daemon: No such network: %s\n' "$3" >&2
    return 1
  fi
  if test "$1" = "image" && test "$2" = "ls"; then
    image_list_count="$(( $(cat "${image_list_count_file}") + 1 ))"
    printf '%s\n' "${image_list_count}" > "${image_list_count_file}"
    if test "${STUB_DOCKER_FAILURE}" = "image-list" \
      || { test "${STUB_DOCKER_FAILURE}" = "image-list-final" \
        && test "${image_list_count}" -ge 2; }; then
      printf 'docker daemon unavailable\n' >&2
      return 125
    fi
    printf '%s\n' 'freqtrade-cn-operator:preexisting'
    return 0
  fi
  if test "$1" = "image" && test "$2" = "inspect"; then
    if test "$3" = "--format"; then
      image_inspect_count="$(( $(cat "${image_inspect_count_file}") + 1 ))"
      printf '%s\n' "${image_inspect_count}" > "${image_inspect_count_file}"
    else
      image_inspect_count="0"
    fi
    if test "${STUB_DOCKER_FAILURE}" = "image-inspect" \
      || { test "${STUB_DOCKER_FAILURE}" = "image-inspect-final" \
        && test "${image_inspect_count}" -ge 2; }; then
      printf 'docker daemon unavailable\n' >&2
      return 125
    fi
    if test "$3" = "--format"; then
      printf '%s\n' "${baseline_id}"
      return 0
    fi
    printf 'Error response from daemon: No such image: %s\n' "$3" >&2
    return 1
  fi
  if test "$1" = "image" && test "$2" = "rm"; then
    printf 'image-rm:%s\n' "$*" >> "${image_mutations}"
    return 0
  fi
  if test "$1" = "tag"; then
    printf 'tag:%s\n' "$*" >> "${image_mutations}"
    return 0
  fi
  return 99
}
'''
    raw_result = subprocess.run(
        [shutil.which("bash") or "bash", "-s"],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        input=(export_failure + stub + cleanup_script).encode(),
        capture_output=True,
        check=False,
    )
    stdout = raw_result.stdout.decode()
    result = subprocess.CompletedProcess(
        raw_result.args,
        raw_result.returncode,
        stdout,
        raw_result.stderr.decode(),
    )
    events = [
        line
        for line in stdout.splitlines()
        if line.startswith(("image-rm:", "tag:", "cleanup:"))
    ]
    return result, events


def run_cleanup_with_stateful_images(
    scenario: str,
) -> tuple[subprocess.CompletedProcess[str], list[str], str, int]:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    new_id = "sha256:" + "b" * 64
    reviewed_id = "" if scenario == "empty" else new_id
    cleanup_script = step_run_script(workflow, PLATFORM_CI_STEPS[5]).replace(
        "${{ steps.reviewed-operator-image.outputs.image_id }}",
        reviewed_id,
    )
    export_scenario = f"export STUB_IMAGE_SCENARIO={shlex.quote(scenario)}\n"
    stub = r'''
RUNNER_TEMP="$(mktemp -d)"
old_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
new_id="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
baseline="${RUNNER_TEMP}/platform-operator-images.before"
baseline_ids="${RUNNER_TEMP}/platform-operator-image-ids.before"
state="${RUNNER_TEMP}/image-state"
image_ids="${RUNNER_TEMP}/image-ids"
events="${RUNNER_TEMP}/image-events"
image_list_count_file="${RUNNER_TEMP}/image-list-count"
: > "${events}"
printf '0\n' > "${image_list_count_file}"
case "${STUB_IMAGE_SCENARIO}" in
  restore)
    printf 'freqtrade-cn-operator:preexisting|%s\n' "${old_id}" > "${baseline}"
    printf '%s\n' "${old_id}" > "${baseline_ids}"
    printf 'freqtrade-cn-operator:created|%s\n' "${new_id}" > "${state}"
    printf 'freqtrade-cn-operator:preexisting|%s\n' "${new_id}" >> "${state}"
    printf '%s\n%s\n' "${old_id}" "${new_id}" > "${image_ids}"
    ;;
  reviewed-membership-error)
    printf 'freqtrade-cn-operator:preexisting|%s\n' "${old_id}" > "${baseline}"
    printf '%s\n' "${old_id}" > "${baseline_ids}"
    : > "${state}"
    printf '%s\n%s\n' "${old_id}" "${new_id}" > "${image_ids}"
    ;;
  empty)
    : > "${baseline}"
    : > "${baseline_ids}"
    : > "${state}"
    : > "${image_ids}"
    ;;
  *) exit 97 ;;
esac
printf 'ready\n' > "${RUNNER_TEMP}/platform-operator-images.ready"
trap '
  status=$?
  printf "IMAGE_LIST_COUNT:%s\n" "$(cat "${image_list_count_file}")"
  sed "s/^/EVENT:/" "${events}"
  if test -f "${RUNNER_TEMP}/platform-operator-images.current"; then
    sed "s/^/FINAL:/" "${RUNNER_TEMP}/platform-operator-images.current"
  fi
  rm -rf "${RUNNER_TEMP}"
  exit "${status}"
' EXIT

grep() {
  if test "${STUB_IMAGE_SCENARIO}" = "reviewed-membership-error" \
    && test "${*: -1}" = "${baseline_ids}" \
    && printf '%s\n' "$*" | command grep --fixed-strings --quiet "${new_id}"; then
    return 2
  fi
  command grep "$@"
}
remove_state_tag() {
  removed_tag="$1"
  : > "${state}.next"
  while IFS='|' read -r tag image_id; do
    test "${tag}" = "${removed_tag}" || printf '%s|%s\n' "${tag}" "${image_id}" \
      >> "${state}.next"
  done < "${state}"
  mv "${state}.next" "${state}"
}
remove_image_id() {
  removed_id="$1"
  : > "${image_ids}.next"
  while IFS= read -r image_id; do
    test "${image_id}" = "${removed_id}" || printf '%s\n' "${image_id}" \
      >> "${image_ids}.next"
  done < "${image_ids}"
  mv "${image_ids}.next" "${image_ids}"
  : > "${state}.next"
  while IFS='|' read -r tag image_id; do
    test "${image_id}" = "${removed_id}" || printf '%s|%s\n' "${tag}" "${image_id}" \
      >> "${state}.next"
  done < "${state}"
  mv "${state}.next" "${state}"
}
docker() {
  if test "$1" = "ps"; then return 0; fi
  if test "$1" = "rm"; then return 0; fi
  if test "$1" = "network" && test "$2" = "disconnect"; then return 0; fi
  if test "$1" = "network" && test "$2" = "rm"; then return 0; fi
  if test "$1" = "network" && test "$2" = "inspect"; then
    printf 'Error response from daemon: No such network: %s\n' "$3" >&2
    return 1
  fi
  if test "$1" = "image" && test "$2" = "ls"; then
    image_list_count="$(( $(cat "${image_list_count_file}") + 1 ))"
    printf '%s\n' "${image_list_count}" > "${image_list_count_file}"
    while IFS='|' read -r tag image_id; do
      test -n "${tag}" && printf '%s\n' "${tag}"
    done < "${state}"
    return 0
  fi
  if test "$1" = "image" && test "$2" = "inspect" && test "$3" = "--format"; then
    inspected_tag="$5"
    while IFS='|' read -r tag image_id; do
      if test "${tag}" = "${inspected_tag}"; then
        printf '%s\n' "${image_id}"
        return 0
      fi
    done < "${state}"
    printf 'Error response from daemon: No such image: %s\n' "${inspected_tag}" >&2
    return 1
  fi
  if test "$1" = "image" && test "$2" = "inspect"; then
    inspected_id="$3"
    if command grep --fixed-strings --line-regexp --quiet "${inspected_id}" "${image_ids}"; then
      return 0
    fi
    printf 'Error response from daemon: No such image: %s\n' "${inspected_id}" >&2
    return 1
  fi
  if test "$1" = "image" && test "$2" = "rm"; then
    printf 'image-rm:%s\n' "$*" >> "${events}"
    if test "$3" = "--force"; then
      removed_id="$4"
      if ! command grep --fixed-strings --line-regexp --quiet "${removed_id}" "${image_ids}"; then
        printf 'Error response from daemon: No such image: %s\n' "${removed_id}" >&2
        return 1
      fi
      remove_image_id "${removed_id}"
    else
      remove_state_tag "$3"
    fi
    return 0
  fi
  if test "$1" = "tag"; then
    tagged_id="$2"
    tagged_name="$3"
    printf 'tag:%s\n' "$*" >> "${events}"
    remove_state_tag "${tagged_name}"
    printf '%s|%s\n' "${tagged_name}" "${tagged_id}" >> "${state}"
    command sort --output="${state}" "${state}"
    return 0
  fi
  return 99
}
'''
    raw_result = subprocess.run(
        [shutil.which("bash") or "bash", "-s"],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        input=(export_scenario + stub + cleanup_script).encode(),
        capture_output=True,
        check=False,
    )
    stdout = raw_result.stdout.decode()
    result = subprocess.CompletedProcess(
        raw_result.args,
        raw_result.returncode,
        stdout,
        raw_result.stderr.decode(),
    )
    events = [line.removeprefix("EVENT:") for line in stdout.splitlines() if line.startswith("EVENT:")]
    final_mapping = "\n".join(
        line.removeprefix("FINAL:")
        for line in stdout.splitlines()
        if line.startswith("FINAL:")
    )
    count_line = next(
        line for line in stdout.splitlines() if line.startswith("IMAGE_LIST_COUNT:")
    )
    return result, events, final_mapping, int(count_line.rsplit(":", 1)[1])


def run_operator_image_build_with_stubbed_inventory(
    failure: str,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    build_script = step_run_script(workflow, BUILD_OPERATOR_IMAGE_STEP)
    export_failure = f"export STUB_BUILD_FAILURE={shlex.quote(failure)}\n"
    stub = r'''
RUNNER_TEMP="$(mktemp -d)"
GITHUB_OUTPUT="${RUNNER_TEMP}/github-output"
export RUNNER_TEMP GITHUB_OUTPUT
events="${RUNNER_TEMP}/events"
sort_count_file="${RUNNER_TEMP}/sort-count"
printf '0\n' > "${sort_count_file}"
: > "${events}"
trap '
  if test -f "${RUNNER_TEMP}/platform-operator-images.ready"; then
    printf "ready\n" >> "${events}"
  fi
  cat "${events}"
  rm -rf "${RUNNER_TEMP}"
' EXIT

python() {
  printf 'build\n' >> "${events}"
  printf '%s\n' 'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
}
sort() {
  sort_count="$(( $(cat "${sort_count_file}") + 1 ))"
  printf '%s\n' "${sort_count}" > "${sort_count_file}"
  if test "${STUB_BUILD_FAILURE}" = "sort" && test "${sort_count}" -eq 1; then
    printf 'sort failed\n' >&2
    return 2
  fi
  command sort "$@"
}
docker() {
  if test "$1" = "image" && test "$2" = "ls"; then
    if test "${STUB_BUILD_FAILURE}" = "image-list" && test "$3" = "--format"; then
      printf 'docker daemon unavailable\n' >&2
      return 125
    fi
    if test "$3" = "--format"; then
      if test "${STUB_BUILD_FAILURE}" != "zero-match"; then
        printf '%s\n' 'freqtrade-cn-operator:preexisting'
      fi
    else
      printf '%s\n' 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    fi
    return 0
  fi
  if test "$1" = "image" && test "$2" = "inspect"; then
    if test "${STUB_BUILD_FAILURE}" = "image-inspect" \
      && test "$5" = "freqtrade-cn-operator:preexisting"; then
      printf 'docker daemon unavailable\n' >&2
      return 125
    fi
    if test "${STUB_BUILD_FAILURE}" = "image-id-empty" \
      && test "$5" = "freqtrade-cn-operator:preexisting"; then
      return 0
    fi
    if test "$5" = "freqtrade-cn-operator:local"; then
      printf '%s\n' 'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
    else
      printf '%s\n' 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    fi
    return 0
  fi
  if test "$1" = "tag"; then return 0; fi
  return 99
}
'''
    raw_result = subprocess.run(
        [shutil.which("bash") or "bash", "-s"],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        input=(export_failure + stub + build_script).encode(),
        capture_output=True,
        check=False,
    )
    stdout = raw_result.stdout.decode()
    result = subprocess.CompletedProcess(
        raw_result.args,
        raw_result.returncode,
        stdout,
        raw_result.stderr.decode(),
    )
    return result, [line for line in stdout.splitlines() if line in {"build", "ready"}]


def run_operator_status_with_stubbed_docker(
    scenario: str,
) -> subprocess.CompletedProcess[str]:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    script = step_run_script(workflow, OPERATOR_CI_STEPS[0])
    lines = script.splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if line.lstrip().startswith("status_first=")
        or line.lstrip().startswith("if ! status_first=")
    )
    end = next(
        index
        for index, line in enumerate(lines[start:], start)
        if 'operator-status.json"' in line
    )
    status_script = "\n".join(lines[start : end + 1])
    setup = f"export STUB_STATUS_SCENARIO={shlex.quote(scenario)}\n" + r'''
set -euo pipefail
RUNNER_TEMP="$(mktemp -d)"
trap 'rm -rf "${RUNNER_TEMP}"' EXIT
platform_ci_dir="${RUNNER_TEMP}/platform-control-ci"
mkdir -p "${platform_ci_dir}"
status_call_count="${RUNNER_TEMP}/status-call-count"
printf '0\n' > "${status_call_count}"

docker() {
  call_count="$(( $(cat "${status_call_count}") + 1 ))"
  printf '%s\n' "${call_count}" > "${status_call_count}"
  printf 'upstream-status-call-%s\n' "${call_count}" >&2
  case "${STUB_STATUS_SCENARIO}:${call_count}" in
    first-fail:1|second-fail:2)
      printf '%s\n' 'SENSITIVE_STATUS_SENTINEL'
      return 7
      ;;
    mismatch:1)
      printf '%s\n' '{"state":"first"}'
      ;;
    mismatch:2)
      printf '%s\n' '{"state":"second"}'
      ;;
    *)
      printf '%s\n' '{"state":"stable"}'
      ;;
  esac
}
'''
    raw_result = subprocess.run(
        [shutil.which("bash") or "bash", "-s"],
        cwd=REPO_ROOT,
        input=(
            setup
            + status_script
            + "\nprintf 'STUB_ARTIFACT:'\n"
            + 'cat "${platform_ci_dir}/operator-status.json"\n'
        ).encode(),
        capture_output=True,
        check=False,
    )
    return subprocess.CompletedProcess(
        raw_result.args,
        raw_result.returncode,
        raw_result.stdout.decode(errors="replace"),
        raw_result.stderr.decode(errors="replace"),
    )


def run_operator_invalid_probe_with_stubbed_docker(
    scenario: str,
) -> subprocess.CompletedProcess[str]:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    script = step_run_script(workflow, OPERATOR_CI_STEPS[0])
    lines = script.splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if line.lstrip().startswith("status_first=")
        or line.lstrip().startswith("if ! status_first=")
    )
    loop_start = next(
        index
        for index, line in enumerate(lines[start:], start)
        if line.lstrip().startswith("for invalid_arguments in")
    )
    end = next(
        index
        for index, line in enumerate(lines[loop_start:], loop_start)
        if "operator_invalid_arguments_phase_complete" in line
    )
    probe_script = "\n".join(lines[start : end + 1])
    setup = f"export STUB_INVALID_SCENARIO={shlex.quote(scenario)}\n" + r'''
set -euo pipefail
export GITHUB_RUN_ID=123456
export GITHUB_RUN_ATTEMPT=2
RUNNER_TEMP="$(mktemp -d)"
platform_ci_dir="${RUNNER_TEMP}/platform-control-ci"
mkdir -p "${platform_ci_dir}"
docker_call_count="${RUNNER_TEMP}/docker-call-count"
printf '0\n' > "${docker_call_count}"
docker_container_state="${RUNNER_TEMP}/docker-container-state"
docker_operation_trace="${RUNNER_TEMP}/docker-operation-trace"
: > "${docker_operation_trace}"
stub_container_id="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
stub_foreign_id="ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
if test "${STUB_INVALID_SCENARIO}" = "create-fail-foreign-container"; then
  printf '%s\n' "${stub_foreign_id}" > "${docker_container_state}"
fi

stub_finish() {
  cat "${docker_operation_trace}"
  if test -s "${docker_container_state}"; then
    printf 'STUB_STATE:'
    cat "${docker_container_state}"
  else
    printf '%s\n' 'STUB_STATE:absent'
  fi
  rm -rf "${RUNNER_TEMP}"
}
trap stub_finish EXIT

record_docker_operation() {
  printf '%s:%s\n' "$1" "$2" >> "${docker_operation_trace}"
}

docker() {
  call_count="$(( $(cat "${docker_call_count}") + 1 ))"
  printf '%s\n' "${call_count}" > "${docker_call_count}"
  if test "$1" = "compose" && printf '%s\n' "$*" | grep -q -- '--instance-id phase2-spot-paper-probe'; then
    printf '%s\n' '{"state":"stable"}'
    return 0
  fi

  if test "$1" = "compose"; then
    printf '%s\n' 'SENSITIVE_COMPOSE_SENTINEL' >&2
    if test "${STUB_INVALID_SCENARIO}" = "create-fail-foreign-container"; then
      record_docker_operation compose no-id
      return 125
    fi
    if test "${STUB_INVALID_SCENARIO}" = "invalid-container-id"; then
      record_docker_operation compose invalid-id
      printf '%s\n' 'SENSITIVE_CONTAINER_ID_SENTINEL'
      return 0
    fi
    printf '%s\n' "${stub_container_id}" > "${docker_container_state}"
    record_docker_operation compose "${stub_container_id}"
    printf '%s\n' "${stub_container_id}"
    return 0
  fi

  if test "$1" = "wait"; then
    record_docker_operation wait "$2"
    if test "${STUB_INVALID_SCENARIO}" = "wrong-status"; then
      printf '%s\n' '7'
    else
      printf '%s\n' '2'
    fi
    return 0
  fi

  if test "$1" = "logs"; then
    record_docker_operation logs "$2"
    if test "${STUB_INVALID_SCENARIO}" = "contaminated-app-output"; then
      printf '%s\n' 'SENSITIVE_INVALID_SENTINEL'
    fi
    printf '%s\n' 'invalid_arguments'
    return 0
  fi

  if test "$1" = "rm"; then
    record_docker_operation rm "$2"
    rm -f "${docker_container_state}"
    return 0
  fi

  if test "$1" = "container" && test "$2" = "ls"; then
    filter_value="$7"
    filtered_container="${filter_value#id=}"
    record_docker_operation container-list "${filtered_container}"
    if test -s "${docker_container_state}"; then
      printf '%s\n' 'stub-container-id'
    fi
    return 0
  fi

  case "${STUB_INVALID_SCENARIO}" in
    *)
      printf '%s\n' 'invalid_arguments'
      return 125
      ;;
  esac
}
'''
    raw_result = subprocess.run(
        [shutil.which("bash") or "bash", "-s"],
        cwd=REPO_ROOT,
        input=(
            setup
            + probe_script
            + "\nprintf '%s\\n' 'STUB_CONTINUED'\n"
            + "printf 'STUB_CALLS:'\n"
            + 'cat "${docker_call_count}"\n'
        ).encode(),
        capture_output=True,
        check=False,
    )
    return subprocess.CompletedProcess(
        raw_result.args,
        raw_result.returncode,
        raw_result.stdout.decode(errors="replace"),
        raw_result.stderr.decode(errors="replace"),
    )


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

    def test_secret_scan_step_satisfies_executable_contract(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        script = step_run_script(workflow, SECRET_SCAN_STEP)

        self.assertIn("python tools/gitleaks_fingerprint_audit.py", script)
        self.assertIn('test "${filtered_status}" -eq 0', script)
        self.assertEqual(validate_root_safety_workflow(workflow), [])

    def test_secret_scan_contract_rejects_security_mutations(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        secret_step = named_workflow_step(workflow, SECRET_SCAN_STEP)

        def mutate_secret_step(old: str, new: str) -> str:
            mutated_step = secret_step.replace(old, new, 1)
            self.assertNotEqual(mutated_step, secret_step)
            return workflow.replace(secret_step, mutated_step, 1)

        mutations = {
            "non-recursive submodules": workflow.replace(
                "git submodule foreach --recursive",
                "git submodule foreach",
                1,
            ),
            "unpinned scanner": workflow.replace(
                GITLEAKS_IMAGE,
                "ghcr.io/gitleaks/gitleaks:v8.27.2",
                1,
            ),
            "unredacted scanner": workflow.replace(
                "dir . --redact --no-banner",
                "dir . --no-banner",
                1,
            ),
            "unfiltered zero accepted": workflow.replace(
                'test "${unfiltered_status}" -eq 1',
                'test "${unfiltered_status}" -eq 0',
                1,
            ),
            "filtered finding accepted": workflow.replace(
                'test "${filtered_status}" -eq 0',
                'test "${filtered_status}" -eq 1',
                1,
            ),
            "fingerprint audit bypassed": workflow.replace(
                "python tools/gitleaks_fingerprint_audit.py",
                "true # fingerprint audit bypassed",
                1,
            ),
            "mutation not detected": workflow.replace(
                'test "${mutation_status}" -eq 1',
                'test "${mutation_status}" -eq 0',
                1,
            ),
            "unfiltered status forged": mutate_secret_step(
                "          unfiltered_status=$?\n",
                "          false\n          unfiltered_status=$?\n",
            ),
            "filtered status forged": mutate_secret_step(
                "          filtered_status=$?\n",
                "          true\n          filtered_status=$?\n",
            ),
            "mutation status forged": mutate_secret_step(
                "          mutation_status=$?\n",
                "          false\n          mutation_status=$?\n",
            ),
            "unfiltered errexit capture removed": mutate_secret_step(
                "          set +e\n",
                "          : # set +e removed\n",
            ),
            "unfiltered errexit restore removed": mutate_secret_step(
                "          unfiltered_status=$?\n          set -e\n",
                "          unfiltered_status=$?\n          set +e\n",
            ),
            "mutation writer removed": mutate_secret_step(
                "          printf 'api_key = \"%s\"\\n' \"$(head -c 48 /dev/urandom | base64 | tr -d '\\n')\" > \"${mutation_path}\"\n",
                "          : # mutation writer removed\n",
            ),
            "audit failure masked": mutate_secret_step(
                '          "${audit_root}/findings.json" "${audit_root}/expected-ignore"\n',
                '          "${audit_root}/findings.json" "${audit_root}/expected-ignore" || true\n',
            ),
            "audit errexit disabled": mutate_secret_step(
                "          python tools/gitleaks_fingerprint_audit.py \\\n",
                "          set +e\n          python tools/gitleaks_fingerprint_audit.py \\\n",
            ),
            "filtered gate failure masked": mutate_secret_step(
                '          test "${filtered_status}" -eq 0\n',
                '          test "${filtered_status}" -eq 0 || true\n',
            ),
            "mutation gate failure masked": mutate_secret_step(
                '          test "${mutation_status}" -eq 1\n',
                '          test "${mutation_status}" -eq 1 || true\n',
            ),
            "filtered scanner failure masked": mutate_secret_step(
                "            --gitleaks-ignore-path /repo/.gitleaksignore\n          filtered_status=$?\n",
                "            --gitleaks-ignore-path /repo/.gitleaksignore || true\n          filtered_status=$?\n",
            ),
            "filtered status forged by ignored printf": mutate_secret_step(
                "          filtered_status=$?\n",
                "          printf x >/dev/null\n          filtered_status=$?\n",
            ),
            "mutation status forged by failing printf": mutate_secret_step(
                "          mutation_status=$?\n",
                "          printf x >/missing/status-probe\n          mutation_status=$?\n",
            ),
            "filtered status forged by function definition": mutate_secret_step(
                "          filtered_status=$?\n",
                "          status_reset() {\n            return 0\n          }\n          filtered_status=$?\n",
            ),
            "filtered status forged by dead if": mutate_secret_step(
                "          filtered_status=$?\n",
                "          if false; then\n            :\n          fi\n          filtered_status=$?\n",
            ),
            "initial errexit removed": mutate_secret_step(
                "          set -euo pipefail\n",
                "          set -uo pipefail\n",
            ),
            "initial pipefail removed": mutate_secret_step(
                "          set -euo pipefail\n",
                "          set -eu\n",
            ),
            "root archive failure masked": mutate_secret_step(
                '          git archive HEAD | tar -x -C "${scan_root}"\n',
                '          git archive HEAD | tar -x -C "${scan_root}" || true\n',
            ),
            "submodule archive removed": mutate_secret_step(
                '            git archive HEAD | tar -x -C "${destination}"\n',
                "            : # submodule archive removed\n",
            ),
            "submodule archive failure masked": mutate_secret_step(
                '            git archive HEAD | tar -x -C "${destination}"\n',
                '            git archive HEAD | tar -x -C "${destination}" || true\n',
            ),
            "expected ignore move failure masked": mutate_secret_step(
                '          mv "${scan_root}/.gitleaksignore" "${audit_root}/expected-ignore"\n',
                '          mv "${scan_root}/.gitleaksignore" "${audit_root}/expected-ignore" || true\n',
            ),
            "empty ignore removed": mutate_secret_step(
                '          : > "${audit_root}/empty-ignore"\n',
                "          : # empty ignore removed\n",
            ),
            "step condition skips scan": mutate_secret_step(
                f"      - name: {SECRET_SCAN_STEP}\n",
                f"      - name: {SECRET_SCAN_STEP}\n        if: ${{{{ false }}}}\n",
            ),
            "step failure tolerated": mutate_secret_step(
                f"      - name: {SECRET_SCAN_STEP}\n",
                f"      - name: {SECRET_SCAN_STEP}\n        continue-on-error: true\n",
            ),
            "custom shell masks failure": mutate_secret_step(
                "        shell: bash\n",
                "        shell: bash {0} || true\n",
            ),
            "step environment added": mutate_secret_step(
                "        shell: bash\n",
                "        env:\n          BASH_ENV: /tmp/unreviewed\n        shell: bash\n",
            ),
            "duplicate run added": mutate_secret_step(
                "        run: |\n",
                "        run: echo bypass\n        run: |\n",
            ),
            "duplicate shell added": mutate_secret_step(
                "        shell: bash\n",
                "        shell: sh\n        shell: bash\n",
            ),
            "working directory added": mutate_secret_step(
                "        run: |\n",
                "        working-directory: /tmp\n        run: |\n",
            ),
        }

        for name, mutated in mutations.items():
            with self.subTest(name=name):
                self.assertNotEqual(mutated, workflow)
                self.assertTrue(validate_root_safety_workflow(mutated))

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
    def test_reviewed_run_scripts_pass_bash_syntax_validation(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        for step_name in (*ALL_PLATFORM_CI_STEPS, SECRET_SCAN_STEP):
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

    def test_platform_postgres_readiness_requires_pid_one_before_pg_isready(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = step_run_script(workflow, PLATFORM_CI_STEPS[0])
        probe = (
            "docker exec platform-postgres-ci sh -c '\n"
            "    postmaster_pid=\n"
            '    read -r postmaster_pid < "${PGDATA}/postmaster.pid" &&\n'
            '      test "${postmaster_pid}" = "1" &&\n'
            "      exec pg_isready --username postgres --dbname platform\n"
            "  ' >/dev/null 2>&1"
        )

        self.assertIn(probe, step)
        self.assertNotIn(
            "docker exec platform-postgres-ci pg_isready ",
            step,
        )
        self.assertIn("for attempt in $(seq 1 60); do", step)
        self.assertIn("sleep 1", step)
        self.assertIn('test "${ready}" -eq 1', step)
        self.assertLess(step.index("read -r postmaster_pid"), step.index("exec pg_isready"))
        self.assertLess(
            step.index('test "${ready}" -eq 1'),
            step.index("CREATE DATABASE platform_test_ci"),
        )

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_platform_postgres_readiness_waits_for_final_postmaster_and_fails_closed(
        self,
    ) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        script_lines = step_run_script(workflow, PLATFORM_CI_STEPS[0]).splitlines()
        loop_start = script_lines.index("ready=0")
        loop_end = script_lines.index('test "${ready}" -eq 1', loop_start) + 1
        readiness_loop = "\n".join(script_lines[loop_start:loop_end]) + "\n"
        harness = r'''set -u
fixture_root="$(mktemp -d)"
trap 'rm -rf "${fixture_root}"' EXIT
mkdir -p "${fixture_root}/bin" "${fixture_root}/pgdata"
printf '%s\n' '#!/bin/sh' 'test "$*" = "--username postgres --dbname platform"' \
  > "${fixture_root}/bin/pg_isready"
chmod +x "${fixture_root}/bin/pg_isready"
printf '0\n' > "${fixture_root}/attempt"

docker() {
  test "$#" -eq 5 || return 91
  test "$1" = "exec" || return 92
  test "$2" = "platform-postgres-ci" || return 93
  test "$3" = "sh" || return 94
  test "$4" = "-c" || return 95
  probe_script="$5"
  attempt="$(( $(cat "${fixture_root}/attempt") + 1 ))"
  printf '%s\n' "${attempt}" > "${fixture_root}/attempt"
  case "${PROBE_SCENARIO}:${attempt}" in
    temp-gap-final:1|temp-only:*)
      printf '42\n' > "${fixture_root}/pgdata/postmaster.pid"
      ;;
    temp-gap-final:2)
      rm -f "${fixture_root}/pgdata/postmaster.pid"
      ;;
    temp-gap-final:3)
      printf '1\n' > "${fixture_root}/pgdata/postmaster.pid"
      ;;
    *)
      return 96
      ;;
  esac
  env PGDATA="${fixture_root}/pgdata" PATH="${fixture_root}/bin:${PATH}" \
    sh -c "${probe_script}"
}

seq() {
  test "$1" = "1" && test "$2" = "60" || return 97
  printf '1\n2\n3\n'
}

sleep() {
  test "$1" = "1"
}
'''

        def run_scenario(scenario: str) -> subprocess.CompletedProcess[bytes]:
            assertions = (
                'loop_status=$?\n'
                'test "$(cat "${fixture_root}/attempt")" = "3"\n'
                'exit "${loop_status}"\n'
            )
            return subprocess.run(
                [shutil.which("bash") or "bash", "-s"],
                input=(
                    f"PROBE_SCENARIO={shlex.quote(scenario)}\n"
                    + harness
                    + readiness_loop
                    + assertions
                ).encode(),
                capture_output=True,
                check=False,
            )

        final_ready = run_scenario("temp-gap-final")
        self.assertEqual(final_ready.returncode, 0, final_ready.stderr.decode())
        self.assertEqual(final_ready.stdout, b"")
        self.assertEqual(final_ready.stderr, b"")

        temporary_only = run_scenario("temp-only")
        self.assertNotEqual(temporary_only.returncode, 0)
        self.assertEqual(temporary_only.stdout, b"")
        self.assertEqual(temporary_only.stderr, b"")

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

    def test_operator_image_is_built_from_reviewed_provenance_and_alias_verified(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, BUILD_OPERATOR_IMAGE_STEP))
        for fragment in (
            "id: reviewed-operator-image",
            "python tools/image_provenance.py build-operator --print-image-id",
            'echo "image_id=${image_id}" >> "${GITHUB_OUTPUT}"',
            'docker tag "${image_id}" freqtrade-cn-operator:local',
            "docker image inspect --format '{{.Id}}' freqtrade-cn-operator:local",
            'test "${alias_id}" = "${image_id}"',
        ):
            self.assertIn(fragment, step)
        self.assertNotIn("docker pull", step)
        self.assertLess(
            workflow.index(f"      - name: {BUILD_IMAGE_STEP}"),
            workflow.index(f"      - name: {BUILD_OPERATOR_IMAGE_STEP}"),
        )

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_operator_image_build_rejects_untrusted_baseline_inventory(self) -> None:
        for failure in ("image-list", "sort", "image-inspect"):
            with self.subTest(failure=failure):
                result, events = run_operator_image_build_with_stubbed_inventory(failure)
                self.assertNotEqual(
                    result.returncode,
                    0,
                    result.stdout + result.stderr,
                )
                self.assertEqual(events, [])

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_operator_image_build_rejects_an_empty_inspected_id(self) -> None:
        result, events = run_operator_image_build_with_stubbed_inventory(
            "image-id-empty"
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(events, [])

    def test_operator_image_build_uses_explicit_checked_inventory_files(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        build = step_run_script(workflow, BUILD_OPERATOR_IMAGE_STEP)
        self.assertNotIn("done < <(", build)
        self.assertNotIn("| sort --unique || true", build)
        for fragment in (
            'operator_image_tags_raw_tmp="${operator_image_baseline}.tags.raw.tmp"',
            'operator_image_tags_tmp="${operator_image_baseline}.tags.tmp"',
            'docker image ls --format \'{{.Repository}}:{{.Tag}}\' > "${operator_image_tags_raw_tmp}"',
            'sort --unique "${operator_image_tags_tmp}"',
            'test -n "${operator_id}"',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, build)

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_operator_image_build_accepts_an_empty_tag_inventory(self) -> None:
        result, events = run_operator_image_build_with_stubbed_inventory("zero-match")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(events, ["build", "ready"])

    def test_operator_steps_have_fixed_order_after_phase2b_regressions(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        positions = [
            workflow.index(f"      - name: {name}")
            for name in ALL_PLATFORM_CI_STEPS
        ]
        self.assertEqual(positions, sorted(positions))

    def test_postgres_provisions_operator_secret_and_runs_zero_skip_selectors(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        start = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[0]))
        self.assertIn("platform_operator_db_password \\", start)
        self.assertIn(
            '--mount type=bind,src="${platform_ci_dir}/platform_operator_db_password",dst=/run/secrets/platform_operator_db_password,readonly',
            start,
        )
        postgres = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[2]))
        for selector in (
            "tests/platform/test_template_repository_postgres.py",
            "tests/platform/test_runtime_registration_repository_postgres.py",
        ):
            self.assertIn(selector, postgres)
        self.assertIn("if skipped:", postgres)
        self.assertIn("platform PostgreSQL selectors skipped tests", postgres)

    def test_operator_acceptance_uses_normal_local_checkout_and_repeats_typed_commands(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, OPERATOR_CI_STEPS[0]))
        required = (
            'operator_root="${RUNNER_TEMP}/platform-operator"',
            'operator_checkout="${operator_root}/freqtrade-cn"',
            'git clone --no-local --no-checkout "${GITHUB_WORKSPACE}" "${operator_checkout}"',
            'git checkout --detach "${GITHUB_SHA}"',
            "protocol.file.allow=always",
            "submodule update --init --recursive",
            'test -z "$(git status --porcelain --untracked-files=no)"',
            'sudo chown 1000:1000 "${operator_checkout}"',
            'sudo chown -R 1000:1000 "${operator_checkout}/.git"',
            'sudo chown -R 1000:1000 "${operator_checkout}/ops/adapter-templates"',
            'sudo chown -R 1000:1000 "${operator_checkout}/ops/runtime-policies"',
            "docker compose --profile platform-operator run --rm --no-deps -T platform-operator runtime-template validate",
            "docker network inspect --format '{{.Internal}}' freqtrade-cn_platform-db",
            "docker network connect --alias platform-postgres freqtrade-cn_platform-db platform-postgres-ci",
            "runtime-template publish --actor platform-operator",
            "runtime-registry register-paper-probe --actor platform-operator",
            "runtime-registry compile --actor platform-operator",
            "runtime-registry status --instance-id phase2-spot-paper-probe",
            "runtime-registry status --image forbidden",
            'test "${invalid_status}" = "2"',
            'test "${invalid_output}" = "invalid_arguments"',
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, step)
        for prefix in ("validate", "publish", "register", "compile"):
            self.assertIn(
                f'test "${{{prefix}_first}}" = "${{{prefix}_second}}"',
                step,
            )
        self.assertIn('if test "${status_first}" != "${status_second}"; then', step)
        self.assertNotIn('chown -R 1000:1000 "${GITHUB_WORKSPACE}"', step)
        self.assertNotIn('chown -R 1000:1000 "${operator_root}"', step)
        self.assertNotIn('"${operator_root}/validate.json"', step)
        self.assertNotIn("--project-directory", step)
        self.assertNotIn("COMPOSE_FILE=", step)
        self.assertNotIn("git@", step)
        self.assertNotIn("https://", step)

    def test_operator_acceptance_restores_the_observed_database_network_baseline(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, OPERATOR_CI_STEPS[0]))
        before = 'operator_database_networks_before="$(docker inspect'
        connect = "docker network connect --alias platform-postgres"
        disconnect = "docker network disconnect freqtrade-cn_platform-db"
        after = 'operator_database_networks="$(docker inspect'
        equality = 'test "${operator_database_networks}" = "${operator_database_networks_before}"'
        for fragment in (before, connect, disconnect, after, equality):
            self.assertIn(fragment, step)
        positions = [step.index(fragment) for fragment in (before, connect, disconnect, after, equality)]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('test "${operator_database_networks}" = "freqtrade-platform-ci"', step)
        reordered = workflow.replace(before, "topology-baseline-placeholder", 1)
        reordered = reordered.replace(connect, before, 1)
        reordered = reordered.replace("topology-baseline-placeholder", connect, 1)
        self.assertIn(
            "operator database topology restoration order differs",
            validate_root_safety_workflow(reordered),
        )

    def test_operator_cleanup_restores_postgres_topology_and_removes_temp_resources(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        acceptance = active_step_text(named_workflow_step(workflow, OPERATOR_CI_STEPS[0]))
        for fragment in (
            "docker network disconnect freqtrade-cn_platform-db platform-postgres-ci",
            "docker network rm freqtrade-cn_platform-db",
            'rm -rf "${operator_root}"',
            'test ! -e "${operator_root}"',
        ):
            self.assertIn(fragment, acceptance)
        cleanup = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[-1]))
        for fragment in (
            "--filter label=com.docker.compose.service=platform-operator",
            "docker network disconnect freqtrade-cn_platform-db platform-postgres-ci",
            "docker network rm freqtrade-cn_platform-db",
            'operator_root="${RUNNER_TEMP}/platform-operator"',
            'sudo rm -rf "${operator_root}"',
        ):
            self.assertIn(fragment, cleanup)

    def test_operator_privilege_gate_uses_real_login_and_reconciles_contamination(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, OPERATOR_CI_STEPS[1]))
        for fragment in (
            'operator_pgpass="${platform_ci_dir}/operator.pgpass"',
            'PGPASSFILE="${operator_pgpass}"',
            "--host 127.0.0.1 --port 55432",
            "--username platform_operator --dbname platform",
            "adapter_template_revisions",
            "state_allocations",
            "secret_references",
            "runtime_spec_revisions",
            "runtime_audit_events",
            "has_table_privilege(",
            "'MAINTAIN'",
            "CREATE FUNCTION public.platform_operator_owned_probe()",
            "OWNER TO platform_operator",
            'test "${owner_reconcile_status}" -ne 0',
            "ALTER FUNCTION public.platform_operator_owned_probe() OWNER TO postgres",
            "CREATE FUNCTION public.platform_operator_public_null_probe()",
            "GRANT EXECUTE ON FUNCTION public.platform_operator_owned_probe()",
            "GRANT MAINTAIN ON TABLE public.runtime_instances TO platform_operator",
            "GRANT TEMPORARY, CREATE ON DATABASE platform TO PUBLIC",
            "ALTER DEFAULT PRIVILEGES FOR ROLE postgres",
            "direct_operator_table_acl=",
            "direct_column_acl_count=",
            "public_effective_acl_count=",
            'test "${null_acl_effective}" = "t|t"',
            'test "${residual_operator_authority}" = "f|f|f|f|f|f"',
            'test "${public_default_acl_count}" = "0"',
            'expect_operator_denied maintain "REINDEX TABLE public.runtime_instances"',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, step)
        self.assertNotIn("SET ROLE platform_operator", step)
        self.assertNotIn("PGPASSWORD", step)
        self.assertNotIn("operator_password=", step)
        self.assertNotIn("docker exec --env", step)
        self.assertNotIn("does not exist", step)
        self.assertNotIn("FROM secret_versions", step)
        self.assertNotIn("VACUUM public.runtime_instances", step)
        self.assertIn("SELECT * FROM secret_version_metadata", step)
        self.assertIn("direct_operator_table_acl=", step)
        self.assertIn('test "${direct_operator_table_acl}" = "14|14|0"', step)
        self.assertIn('test "${direct_column_acl_count}" = "0"', step)
        self.assertIn("public_effective_acl_count=", step)
        self.assertIn('test "${public_effective_acl_count}" = "0"', step)
        self.assertLess(
            step.index("ALTER DEFAULT PRIVILEGES FOR ROLE postgres"),
            step.index("CREATE FUNCTION public.platform_operator_public_null_probe()"),
        )

    def test_operator_privilege_gate_reports_fixed_post_reconcile_checkpoints(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, OPERATOR_CI_STEPS[1]))
        checkpoints = (
            (
                'test "${operator_membership_count}" = "0"',
                "operator_membership_checkpoint_complete",
                "operator_default_acl_count=",
            ),
            (
                'test "${operator_default_acl_count}" = "0"',
                "operator_default_acl_checkpoint_complete",
                "direct_operator_database_acl_difference=",
            ),
            (
                'test "${direct_operator_database_acl_difference}" = "0"',
                "operator_database_acl_checkpoint_complete",
                "direct_operator_schema_acl_difference=",
            ),
            (
                'test "${direct_operator_schema_acl_difference}" = "0"',
                "operator_schema_acl_checkpoint_complete",
                "direct_operator_relation_acl_difference=",
            ),
            (
                'test "${direct_operator_relation_acl_difference}" = "0"',
                "operator_relation_acl_checkpoint_complete",
                "direct_operator_sequence_acl_count=",
            ),
            (
                'test "${direct_operator_sequence_acl_count}" = "0"',
                "operator_sequence_acl_checkpoint_complete",
                "direct_operator_column_acl_count=",
            ),
            (
                'test "${direct_operator_column_acl_count}" = "0"',
                "operator_column_acl_checkpoint_complete",
                "direct_operator_routine_acl_count=",
            ),
            (
                'test "${direct_operator_routine_acl_count}" = "0"',
                "operator_routine_acl_checkpoint_complete",
                "residual_operator_authority=",
            ),
            (
                'test "${residual_operator_authority}" = "f|f|f|f|f|f"',
                "operator_residual_authority_checkpoint_complete",
                "public_default_acl_count=",
            ),
            (
                'test "${public_default_acl_count}" = "0"',
                "operator_public_default_acl_checkpoint_complete",
                "public_effective_acl_count=",
            ),
            (
                'test "${public_effective_acl_count}" = "0"',
                "operator_public_effective_acl_checkpoint_complete",
                "expect_operator_denied sequence",
            ),
        )

        for assertion, marker, next_gate in checkpoints:
            with self.subTest(marker=marker):
                self.assertEqual(step.count(marker), 1)
                marker_line = next(line for line in step.splitlines() if marker in line)
                self.assertEqual(
                    marker_line.strip(),
                    f"printf '%s\\n' '{marker}' >&2",
                )
                self.assertNotIn("${", marker_line)
                self.assertLess(step.index(assertion), step.index(marker))
                self.assertLess(step.index(marker), step.index(next_gate))

        denial_marker = "operator_final_denial_probes_complete"
        self.assertEqual(step.count(denial_marker), 1)
        denial_marker_line = next(
            line for line in step.splitlines() if denial_marker in line
        )
        self.assertEqual(
            denial_marker_line.strip(),
            f"printf '%s\\n' '{denial_marker}' >&2",
        )
        self.assertNotIn("${", denial_marker_line)
        for denial_probe in (
            "expect_operator_denied sequence",
            "expect_operator_denied routine",
            'expect_operator_denied maintain "REINDEX TABLE public.runtime_instances"',
            'expect_operator_denied secret-version-after "SELECT * FROM secret_version_metadata"',
            'expect_operator_denied lifecycle-after "SELECT * FROM runtime_lifecycle_jobs"',
        ):
            with self.subTest(denial_probe=denial_probe):
                self.assertLess(step.index(denial_probe), step.index(denial_marker))

    def test_operator_login_uses_a_private_cleaned_libpq_passfile(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, OPERATOR_CI_STEPS[1]))
        for fragment in (
            'operator_pgpass="${platform_ci_dir}/operator.pgpass"',
            'Path(sys.argv[1]).read_text(encoding="utf-8")',
            "os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)",
            'test "$(stat --format \'%a\' "${operator_pgpass}")" = "600"',
            "cleanup_operator_pgpass() {",
            'rm -f "${operator_pgpass}"',
            "trap cleanup_operator_pgpass EXIT",
            'PGPASSFILE="${operator_pgpass}" psql',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, step)
        for forbidden in (
            "PGPASSWORD",
            "operator_password=",
            "--env PGPASSWORD",
            '$(cat "${platform_ci_dir}/platform_operator_db_password")',
            '$(tr -d \'\\r\\n\' < "${platform_ci_dir}/platform_operator_db_password")',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, step)

    def test_operator_privilege_gate_has_exact_catalog_authority_inventories(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, OPERATOR_CI_STEPS[1]))
        required = (
            "operator_membership_count=",
            "pg_auth_members",
            'test "${operator_membership_count}" = "0"',
            "operator_default_acl_count=",
            "pg_default_acl",
            'test "${operator_default_acl_count}" = "0"',
            "direct_operator_database_acl_difference=",
            "direct_operator_schema_acl_difference=",
            "direct_operator_relation_acl_difference=",
            "direct_operator_sequence_acl_count=",
            "direct_operator_routine_acl_count=",
            "EXCEPT ALL",
            "'platform'",
            "'CONNECT'",
            "'public'",
            "'USAGE'",
            'test "${direct_operator_database_acl_difference}" = "0"',
            'test "${direct_operator_schema_acl_difference}" = "0"',
            'test "${direct_operator_relation_acl_difference}" = "0"',
            'test "${direct_operator_sequence_acl_count}" = "0"',
            'test "${direct_operator_routine_acl_count}" = "0"',
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, step)

    def test_operator_acceptance_requires_exact_output_schemas_and_fixed_ids(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, OPERATOR_CI_STEPS[0]))
        for fragment in (
            "validate_keys = {",
            "publish_keys = {",
            "registration_keys = {",
            "if set(validate) != validate_keys",
            "if set(publish) != publish_keys",
            "if set(register) != registration_keys",
            'validate["strategy_class_name"] != "SampleStrategy"',
            'register["catalog_revision_id"] != "builtin-market-catalog-v2"',
            'register["state_allocation_id"] != "state-phase2-spot-paper-probe-v1"',
            'f"template-{validate[\'template_payload_digest\']}"',
            'runtime_spec_revision_id.removeprefix("runtime-spec-")',
            'runtime_spec_revision_id.startswith("runtime-spec-")',
            "secret-phase2-spot-paper-probe-api-password-v1",
            "secret-phase2-spot-paper-probe-jwt-secret-v1",
            "secret-phase2-spot-paper-probe-ws-token-v1",
            "commit_pattern.fullmatch",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, step)
        for fragment in OPERATOR_OUTPUT_CONTRACT:
            with self.subTest(mutation=fragment):
                mutated = workflow.replace(fragment, "removed-output-contract", 1)
                self.assertNotEqual(mutated, workflow)
                self.assertTrue(validate_root_safety_workflow(mutated))

    def test_operator_output_validator_accepts_canonical_public_metadata(self) -> None:
        root_commit, documents = canonical_operator_documents()

        result = run_operator_output_validator(documents, root_commit)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_operator_output_validator_rejects_sensitive_fields_and_paths_without_reflection(
        self,
    ) -> None:
        root_commit, canonical_documents = canonical_operator_documents()
        forbidden_fields = (
            "password",
            "secret_value",
            "dsn",
            "timestamp",
            "created_at",
            "updated_at",
        )
        for forbidden_field in forbidden_fields:
            with self.subTest(forbidden_field=forbidden_field):
                documents = json.loads(json.dumps(canonical_documents))
                documents[0]["nested"] = {forbidden_field: "private-sentinel"}

                result = run_operator_output_validator(documents, root_commit)

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(
                    result.stderr,
                    "operator output exposes forbidden data\n",
                )
                self.assertNotIn("private-sentinel", result.stderr)

        for forbidden_path in ("/opt/private-sentinel", "/run/private-sentinel"):
            with self.subTest(forbidden_path=forbidden_path):
                documents = json.loads(json.dumps(canonical_documents))
                documents[0]["nested"] = [{"safe_key": forbidden_path}]

                result = run_operator_output_validator(documents, root_commit)

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(
                    result.stderr,
                    "operator output exposes forbidden data\n",
                )
                self.assertNotIn("private-sentinel", result.stderr)

    def test_operator_status_gate_has_fixed_safe_diagnostics(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, OPERATOR_CI_STEPS[0]))

        normalized_step = "\n".join(line.strip() for line in step.splitlines())
        guards = (
            (
                'if ! status_first="$(docker compose --profile platform-operator run --rm --no-deps -T platform-operator runtime-registry status --instance-id phase2-spot-paper-probe)"; then',
                "operator_status_first_query_failed",
            ),
            (
                'if ! status_second="$(docker compose --profile platform-operator run --rm --no-deps -T platform-operator runtime-registry status --instance-id phase2-spot-paper-probe)"; then',
                "operator_status_second_query_failed",
            ),
            (
                'if test "${status_first}" != "${status_second}"; then',
                "operator_status_output_not_deterministic",
            ),
        )
        for guard_line, diagnostic in guards:
            with self.subTest(diagnostic=diagnostic):
                guard = "\n".join(
                    (
                        guard_line,
                        f"printf '%s\\n' '{diagnostic}' >&2",
                        "exit 1",
                        "fi",
                    )
                )
                self.assertEqual(step.count(diagnostic), 1)
                self.assertIn(guard, normalized_step)
                diagnostic_line = next(
                    line for line in step.splitlines() if diagnostic in line
                )
                self.assertEqual(
                    diagnostic_line.strip(),
                    f"printf '%s\\n' '{diagnostic}' >&2",
                )
                self.assertNotIn("${", diagnostic_line)

    def test_operator_invalid_probe_gate_has_fixed_safe_diagnostics(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, OPERATOR_CI_STEPS[0]))
        normalized_step = "\n".join(line.strip() for line in step.splitlines())

        tokens = (
            "operator_status_phase_complete",
            "operator_invalid_arguments_create_failed",
            "operator_invalid_arguments_container_id_contract_failed",
            "operator_invalid_arguments_wait_failed",
            "operator_invalid_arguments_log_capture_failed",
            "operator_invalid_arguments_cleanup_failed",
            "operator_invalid_arguments_absence_check_failed",
            "operator_invalid_arguments_cleanup_incomplete",
            "operator_invalid_arguments_exit_status_failed",
            "operator_invalid_arguments_output_contract_failed",
            "operator_invalid_arguments_phase_complete",
        )
        for token in tokens:
            with self.subTest(token=token):
                self.assertEqual(step.count(token), 1)
                diagnostic_line = next(
                    line for line in step.splitlines() if token in line
                )
                self.assertEqual(
                    diagnostic_line.strip(),
                    f"printf '%s\\n' '{token}' >&2",
                )
                self.assertNotIn("${", diagnostic_line)

        for status_name, diagnostic in (
            ("invalid_create_status", "operator_invalid_arguments_create_failed"),
            ("invalid_wait_status", "operator_invalid_arguments_wait_failed"),
            ("invalid_log_status", "operator_invalid_arguments_log_capture_failed"),
            ("invalid_cleanup_status", "operator_invalid_arguments_cleanup_failed"),
            ("invalid_absence_status", "operator_invalid_arguments_absence_check_failed"),
        ):
            self.assertIn(
                f'if ! test "${{{status_name}}}" -eq 0; then\n'
                f"printf '%s\\n' '{diagnostic}' >&2\nexit 1\nfi",
                normalized_step,
            )

        self.assertIn(
            "\n".join(
                (
                    'if ! test "${invalid_status}" = "2"; then',
                    "printf '%s\\n' 'operator_invalid_arguments_exit_status_failed' >&2",
                    "exit 1",
                    "fi",
                )
            ),
            normalized_step,
        )
        self.assertIn(
            "docker compose --profile platform-operator run --detach --name",
            normalized_step,
        )
        self.assertIn(
            'invalid_container="platform-operator-invalid-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-${invalid_probe_index}-ci"',
            step,
        )
        self.assertEqual(
            step.count(
                'docker container ls --all --quiet --no-trunc --filter "id=${invalid_container_id}"'
            ),
            1,
        )
        self.assertIn(
            'invalid_status="$(docker wait "${invalid_container_id}" 2>/dev/null)"',
            step,
        )
        self.assertIn(
            'invalid_output="$(docker logs "${invalid_container_id}" 2>&1)"',
            step,
        )
        self.assertIn('docker rm "${invalid_container_id}" >/dev/null 2>&1', step)
        self.assertIn(
            '[[ ! "${invalid_container_id}" =~ ^[0-9a-f]{64}$ ]]',
            step,
        )
        self.assertNotIn("invalid_existing=", step)
        self.assertNotIn('name=^/${invalid_container}$', step)
        self.assertNotIn(
            "run --rm --no-deps -T platform-operator ${invalid_arguments}",
            step,
        )
        self.assertLess(
            step.index('docker rm "${invalid_container_id}"'),
            step.index("operator_invalid_arguments_exit_status_failed"),
        )
        self.assertLess(
            step.index('docker rm "${invalid_container_id}"'),
            step.index("operator_invalid_arguments_output_contract_failed"),
        )
        self.assertIn(
            "\n".join(
                (
                    'if ! test "${invalid_output}" = "invalid_arguments"; then',
                    "printf '%s\\n' 'operator_invalid_arguments_output_contract_failed' >&2",
                    "exit 1",
                    "fi",
                )
            ),
            normalized_step,
        )
        self.assertLess(
            step.index('operator-status.json"'),
            step.index("operator_status_phase_complete"),
        )
        self.assertLess(
            step.index("operator_status_phase_complete"),
            step.index("for invalid_arguments in"),
        )
        self.assertLess(
            step.index("operator_invalid_arguments_exit_status_failed"),
            step.index("operator_invalid_arguments_output_contract_failed"),
        )
        self.assertLess(
            step.index("operator_invalid_arguments_output_contract_failed"),
            step.index("operator_invalid_arguments_phase_complete"),
        )
        self.assertLess(
            step.index("operator_invalid_arguments_phase_complete"),
            step.index("python - "),
        )

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_operator_invalid_probe_gate_classifies_failures_without_reflection(
        self,
    ) -> None:
        scenarios = (
            (
                "create-fail-foreign-container",
                1,
                (
                    "operator_status_phase_complete",
                    "operator_invalid_arguments_create_failed",
                ),
            ),
            (
                "invalid-container-id",
                1,
                (
                    "operator_status_phase_complete",
                    "operator_invalid_arguments_container_id_contract_failed",
                ),
            ),
            (
                "wrong-status",
                1,
                (
                    "operator_status_phase_complete",
                    "operator_invalid_arguments_exit_status_failed",
                ),
            ),
            (
                "contaminated-app-output",
                1,
                (
                    "operator_status_phase_complete",
                    "operator_invalid_arguments_output_contract_failed",
                ),
            ),
            (
                "compose-noise-exact-app-output",
                0,
                (
                    "operator_status_phase_complete",
                    "operator_invalid_arguments_phase_complete",
                ),
            ),
        )
        all_tokens = {
            "operator_status_phase_complete",
            "operator_invalid_arguments_create_failed",
            "operator_invalid_arguments_container_id_contract_failed",
            "operator_invalid_arguments_wait_failed",
            "operator_invalid_arguments_log_capture_failed",
            "operator_invalid_arguments_cleanup_failed",
            "operator_invalid_arguments_absence_check_failed",
            "operator_invalid_arguments_cleanup_incomplete",
            "operator_invalid_arguments_exit_status_failed",
            "operator_invalid_arguments_output_contract_failed",
            "operator_invalid_arguments_phase_complete",
        }
        for scenario, returncode, expected_stderr in scenarios:
            with self.subTest(scenario=scenario):
                result = run_operator_invalid_probe_with_stubbed_docker(scenario)
                self.assertEqual(
                    result.returncode,
                    returncode,
                    result.stdout + result.stderr,
                )
                self.assertNotIn("SENSITIVE_INVALID_SENTINEL", result.stdout)
                self.assertNotIn("SENSITIVE_INVALID_SENTINEL", result.stderr)
                self.assertNotIn("SENSITIVE_COMPOSE_SENTINEL", result.stdout)
                self.assertNotIn("SENSITIVE_COMPOSE_SENTINEL", result.stderr)
                self.assertNotIn("SENSITIVE_CONTAINER_ID_SENTINEL", result.stdout)
                self.assertNotIn("SENSITIVE_CONTAINER_ID_SENTINEL", result.stderr)
                self.assertEqual(
                    tuple(
                        line
                        for line in result.stderr.splitlines()
                        if line in all_tokens
                    ),
                    expected_stderr,
                )
                self.assertEqual("STUB_CONTINUED" in result.stdout, returncode == 0)
                trace = tuple(
                    line
                    for line in result.stdout.splitlines()
                    if line.startswith(
                        ("container-list:", "compose:", "wait:", "logs:", "rm:")
                    )
                )
                expected_container_id = (
                    "0123456789abcdef0123456789abcdef"
                    "0123456789abcdef0123456789abcdef"
                )
                if scenario in ("wrong-status", "contaminated-app-output"):
                    self.assertEqual(
                        trace,
                        (
                            f"compose:{expected_container_id}",
                            f"wait:{expected_container_id}",
                            f"logs:{expected_container_id}",
                            f"rm:{expected_container_id}",
                            f"container-list:{expected_container_id}",
                        ),
                    )
                if scenario == "create-fail-foreign-container":
                    self.assertEqual(trace, ("compose:no-id",))
                    self.assertIn(
                        "STUB_STATE:ffffffffffffffffffffffffffffffff"
                        "ffffffffffffffffffffffffffffffff\n",
                        result.stdout,
                    )
                if scenario == "invalid-container-id":
                    self.assertEqual(trace, ("compose:invalid-id",))
                if returncode == 0:
                    self.assertIn("STUB_CALLS:17\n", result.stdout)

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_operator_status_gate_classifies_failures_without_reflecting_output(
        self,
    ) -> None:
        scenarios = (
            (
                "first-fail",
                1,
                "operator_status_first_query_failed",
                ("upstream-status-call-1",),
            ),
            (
                "second-fail",
                1,
                "operator_status_second_query_failed",
                ("upstream-status-call-1", "upstream-status-call-2"),
            ),
            (
                "mismatch",
                1,
                "operator_status_output_not_deterministic",
                ("upstream-status-call-1", "upstream-status-call-2"),
            ),
        )
        diagnostics = {
            "operator_status_first_query_failed",
            "operator_status_second_query_failed",
            "operator_status_output_not_deterministic",
        }
        for scenario, returncode, diagnostic, upstream_lines in scenarios:
            with self.subTest(scenario=scenario):
                result = run_operator_status_with_stubbed_docker(scenario)
                self.assertEqual(result.returncode, returncode)
                self.assertNotIn("SENSITIVE_STATUS_SENTINEL", result.stdout)
                self.assertNotIn("SENSITIVE_STATUS_SENTINEL", result.stderr)
                stderr_lines = result.stderr.splitlines()
                self.assertEqual(
                    [line for line in stderr_lines if line in diagnostics],
                    [diagnostic],
                )
                self.assertEqual(
                    [line for line in stderr_lines if line.startswith("upstream-")],
                    list(upstream_lines),
                )

        success = run_operator_status_with_stubbed_docker("success")
        self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
        self.assertEqual(
            success.stdout,
            'STUB_ARTIFACT:{"state":"stable"}\n',
        )
        self.assertFalse(diagnostics.intersection(success.stderr.splitlines()))
        self.assertEqual(
            [
                line
                for line in success.stderr.splitlines()
                if line.startswith("upstream-")
            ],
            ["upstream-status-call-1", "upstream-status-call-2"],
        )

    def test_operator_cleanup_removes_all_reviewed_image_tags_and_asserts_absence(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cleanup = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[-1]))
        for fragment in (
            'reviewed_operator_image_id="${{ steps.reviewed-operator-image.outputs.image_id }}"',
            "--format '{{.Repository}}:{{.Tag}}'",
            "grep --extended-regexp '^freqtrade-cn-operator:'",
            'docker image rm "${operator_tag}"',
            'docker tag "${operator_id}" "${operator_tag}"',
            'docker image rm --force "${operator_id}"',
            'docker image inspect "${operator_id}"',
            'remove_operator_image_id "${reviewed_operator_image_id}"',
            'cmp "${operator_image_baseline}" "${operator_image_current}"',
        ):
            self.assertIn(fragment, cleanup)

    def test_operator_image_cleanup_uses_prebuild_baseline_when_output_is_empty(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        build = active_step_text(named_workflow_step(workflow, BUILD_OPERATOR_IMAGE_STEP))
        cleanup = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[-1]))
        baseline = '${RUNNER_TEMP}/platform-operator-images.before'
        self.assertIn(baseline, build)
        self.assertLess(
            build.index(baseline),
            build.index("python tools/image_provenance.py build-operator"),
        )
        for fragment in (
            'operator_image_baseline_tmp="${operator_image_baseline}.tmp"',
            'operator_image_ids_baseline_tmp="${operator_image_ids_baseline}.tmp"',
            "platform-operator-images.ready",
            'mv "${operator_image_baseline_tmp}" "${operator_image_baseline}"',
            'mv "${operator_image_ids_baseline_tmp}" "${operator_image_ids_baseline}"',
            'mv "${operator_image_baseline_ready_tmp}" "${operator_image_baseline_ready}"',
        ):
            self.assertIn(fragment, build)
        for fragment in (
            baseline,
            "platform-operator-images.ready",
            "platform-operator-images.current",
            "platform-operator-images.created",
            "platform-operator-image-ids.created",
            "comm -13",
            "docker image rm \"${operator_tag}\"",
            'docker image rm --force "${operator_id}"',
            "cmp",
        ):
            self.assertIn(fragment, cleanup)
        baseline_branch = cleanup.index('if test -f "${operator_image_baseline}"')
        self.assertIn('test -f "${operator_image_ids_baseline}"', cleanup)
        self.assertIn('test -f "${operator_image_baseline_ready}"', cleanup)
        membership_branch = cleanup.index("reviewed_id_membership_status=0")
        mutation_branch = cleanup.index('docker image rm "${operator_tag}"')
        self.assertLess(baseline_branch, membership_branch)
        self.assertLess(membership_branch, mutation_branch)

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_operator_image_cleanup_ignores_incomplete_baseline(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cleanup = step_run_script(workflow, PLATFORM_CI_STEPS[-1]).replace(
            "${{ steps.reviewed-operator-image.outputs.image_id }}", ""
        )
        stub = r'''
RUNNER_TEMP="$(mktemp -d)"
trap 'rm -rf "${RUNNER_TEMP}"' EXIT
baseline_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
printf 'freqtrade-cn-operator:preexisting|%s\n' "${baseline_id}" \
  > "${RUNNER_TEMP}/platform-operator-images.before"
image_mutations="${RUNNER_TEMP}/image-mutations"
: > "${image_mutations}"

docker() {
  if test "$1" = "ps"; then return 0; fi
  if test "$1" = "rm"; then return 0; fi
  if test "$1" = "network" && test "$2" = "disconnect"; then return 0; fi
  if test "$1" = "network" && test "$2" = "rm"; then return 0; fi
  if test "$1" = "network" && test "$2" = "inspect"; then
    printf 'Error response from daemon: No such network: %s\n' "$3" >&2
    return 1
  fi
  if test "$1" = "image" && test "$2" = "ls"; then
    printf '%s\n' 'freqtrade-cn-operator:preexisting'
    return 0
  fi
  if test "$1" = "image" && test "$2" = "inspect"; then
    printf '%s\n' "${baseline_id}"
    return 0
  fi
  if test "$1" = "image" && test "$2" = "rm"; then
    printf 'image-rm:%s\n' "$*" >> "${image_mutations}"
    return 0
  fi
  if test "$1" = "tag"; then
    printf 'tag:%s\n' "$*" >> "${image_mutations}"
    return 0
  fi
  return 99
}
'''
        result = subprocess.run(
            [shutil.which("bash") or "bash", "-s"],
            cwd=REPO_ROOT,
            input=(stub + cleanup + 'test ! -s "${image_mutations}"\n').encode(),
            capture_output=True,
            check=False,
        )
        output = (result.stdout + result.stderr).decode(errors="replace")
        self.assertEqual(result.returncode, 0, output)

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_operator_cleanup_fails_closed_when_docker_queries_fail(self) -> None:
        for failure in (
            "docker-ps",
            "docker-ps-final",
            "network-inspect",
            "image-list",
            "image-list-final",
            "image-inspect",
            "image-inspect-final",
        ):
            with self.subTest(failure=failure):
                result, events = run_cleanup_with_stubbed_docker_failure(failure)
                self.assertNotEqual(
                    result.returncode,
                    0,
                    result.stdout + result.stderr,
                )
                self.assertTrue(
                    any(event.startswith("cleanup:rm") for event in events),
                    events,
                )
                if failure in {"image-list", "image-inspect"}:
                    image_mutations = [
                        event
                        for event in events
                        if event.startswith(("image-rm:", "tag:"))
                    ]
                    self.assertEqual(image_mutations, [])

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_operator_cleanup_restores_a_complete_image_baseline(self) -> None:
        result, events, final_mapping, image_list_count = (
            run_cleanup_with_stateful_images("restore")
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        old_id = "sha256:" + "a" * 64
        new_id = "sha256:" + "b" * 64
        self.assertIn(
            "image-rm:image rm freqtrade-cn-operator:created",
            events,
        )
        self.assertIn(f"tag:tag {old_id} freqtrade-cn-operator:preexisting", events)
        self.assertIn(f"image-rm:image rm --force {new_id}", events)
        self.assertEqual(
            final_mapping,
            f"freqtrade-cn-operator:preexisting|{old_id}",
        )
        self.assertEqual(image_list_count, 2)

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_operator_cleanup_rejects_reviewed_id_membership_query_errors_before_mutation(
        self,
    ) -> None:
        result, events, final_mapping, image_list_count = (
            run_cleanup_with_stateful_images("reviewed-membership-error")
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(events, [])
        self.assertEqual(final_mapping, "")
        self.assertEqual(image_list_count, 1)

    @unittest.skipUnless(shutil.which("bash"), "Bash is unavailable")
    def test_operator_cleanup_accepts_empty_docker_query_results(self) -> None:
        result, events, final_mapping, image_list_count = (
            run_cleanup_with_stateful_images("empty")
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(events, [])
        self.assertEqual(final_mapping, "")
        self.assertEqual(image_list_count, 2)

    def test_operator_contract_rejects_missing_executable_and_sql_evidence(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        fragments = (
            *WORKFLOW_EXECUTABLE_CONTRACT[OPERATOR_CI_STEPS[0]],
            *WORKFLOW_EXECUTABLE_CONTRACT[OPERATOR_CI_STEPS[1]],
            "CREATE FUNCTION public.platform_operator_owned_probe()",
            "GRANT MAINTAIN ON TABLE public.runtime_instances TO platform_operator",
            "ALTER DEFAULT PRIVILEGES FOR ROLE postgres",
        )
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                mutated = workflow.replace(fragment, "removed-operator-contract", 1)
                self.assertNotEqual(mutated, workflow)
                self.assertTrue(validate_root_safety_workflow(mutated))

    def test_operator_contract_rejects_comment_and_dead_branch_substitution(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        marker = "docker network connect --alias platform-postgres freqtrade-cn_platform-db platform-postgres-ci"
        step = named_workflow_step(workflow, OPERATOR_CI_STEPS[0])
        commented_step = step.replace(marker, f"# {marker}", 1)
        commented = workflow.replace(step, commented_step, 1)
        self.assertTrue(validate_root_safety_workflow(commented))

        removed = workflow.replace(marker, "removed-operator-network-connect", 1)
        dead = removed.replace(
            '          platform_ci_dir="${RUNNER_TEMP}/platform-control-ci"',
            '          if false; then\n'
            f'            {marker}\n'
            '          fi\n'
            '          platform_ci_dir="${RUNNER_TEMP}/platform-control-ci"',
            1,
        )
        self.assertTrue(validate_root_safety_workflow(dead))

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
