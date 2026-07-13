from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_NETWORK_BOUNDARY = (
    "Could not load markets, therefore cannot start. "
    "Please investigate the above error for more details."
)
TRADING_STARTUP_MILESTONES = (
    "Starting worker ",
    "Using config: /freqtrade/config/runtime.json ...",
    "Using config: /freqtrade/config/trading-safety.json ...",
    "Runmode set to dry_run.",
    "Using additional Strategy lookup path: /freqtrade/user_data/strategies",
    'Using DB: "sqlite:////freqtrade/state/trades.sqlite"',
    "Using user-data directory: /freqtrade/state ...",
    "Checking exchange...",
    "Instance is running with dry_run enabled",
)
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
LOG_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} - "
    r"(?P<logger>[a-z0-9_.]+) - (?P<level>INFO|WARNING|ERROR) - (?P<message>.+)$"
)
APPROVED_LOG_RECORDS = {
    (
        "freqtrade.configuration.load_config",
        "INFO",
        "Using config: /freqtrade/config/runtime.json ...",
    ),
    (
        "freqtrade.configuration.load_config",
        "INFO",
        "Using config: /freqtrade/config/trading-safety.json ...",
    ),
    ("freqtrade.loggers", "INFO", "Enabling colorized output."),
    ("freqtrade.loggers", "INFO", "Logfile configured"),
    ("freqtrade.loggers", "INFO", "Verbosity set to 0"),
    ("freqtrade.configuration.configuration", "INFO", "Runmode set to dry_run."),
    (
        "freqtrade.configuration.configuration",
        "INFO",
        "Using additional Strategy lookup path: /freqtrade/user_data/strategies",
    ),
    ("freqtrade.configuration.configuration", "INFO", "Parameter --db-url detected ..."),
    ("freqtrade.configuration.configuration", "INFO", "Dry run is enabled"),
    (
        "freqtrade.configuration.configuration",
        "INFO",
        'Using DB: "sqlite:////freqtrade/state/trades.sqlite"',
    ),
    (
        "freqtrade.configuration.configuration",
        "INFO",
        "Using user-data directory: /freqtrade/state ...",
    ),
    (
        "freqtrade.configuration.directory_operations",
        "INFO",
        "Created data directory: None",
    ),
    ("freqtrade.exchange.check_exchange", "INFO", "Checking exchange..."),
    ("freqtrade.configuration.configuration", "INFO", "Using pairlist from configuration."),
    ("freqtrade.exchange.exchange", "INFO", "Instance is running with dry_run enabled"),
    ("freqtrade.exchange.exchange", "ERROR", "Could not load markets."),
    ("freqtrade.freqtradebot", "INFO", "Cleaning up modules ..."),
    (
        "freqtrade.freqtradebot",
        "WARNING",
        "Exception during cleanup: AttributeError type object 'Trade' has no attribute 'session'",
    ),
    ("freqtrade", "ERROR", EXTERNAL_NETWORK_BOUNDARY),
}
APPROVED_LOG_RECORD_PATTERNS = (
    re.compile(r"^freqtrade\|INFO\|freqtrade 2026\.7-dev$"),
    re.compile(r"^numexpr\.utils\|INFO\|Note: NumExpr detected \d+ cores but "
               r'"NUMEXPR_MAX_THREADS" not set, so enforcing safe limit of \d+\.$'),
    re.compile(r"^numexpr\.utils\|INFO\|NumExpr defaulting to \d+ threads\.$"),
    re.compile(r"^freqtrade\.worker\|INFO\|Starting worker 2026\.7-dev$"),
    re.compile(
        r"^freqtrade\.configuration\.environment_vars\|INFO\|Loading variable "
        r"'FREQTRADE__API_SERVER__(?:JWT_SECRET_KEY|PASSWORD|WS_TOKEN)'$"
    ),
    re.compile(
        r"^freqtrade\.configuration\.environment_vars\|INFO\|Key parts: "
        r"\['API_SERVER', '(?:JWT_SECRET_KEY|PASSWORD|WS_TOKEN)'\]$"
    ),
    re.compile(
        r"^freqtrade\.configuration\.configuration\|INFO\|"
        r"Using max_open_trades: [23] \.\.\.$"
    ),
    re.compile(
        r"^freqtrade\.configuration\.configuration\|INFO\|Using data directory: "
        r"/freqtrade/state/data/(?:bitget|okx) \.\.\.$"
    ),
    re.compile(
        r'^freqtrade\.exchange\.check_exchange\|INFO\|Exchange "(?:bitget|okx)" '
        r"is officially supported by the Freqtrade development team\.$"
    ),
    re.compile(r"^freqtrade\.exchange\.exchange\|INFO\|Using CCXT 4\.5\.61$"),
    re.compile(
        r"^freqtrade\.exchange\.exchange\|INFO\|Applying additional ccxt config: "
        r"(?:\{'httpsProxy': 'http://host\.docker\.internal:12639', "
        r"'wsProxy': 'http://host\.docker\.internal:12639',|"
        r"\{'options': \{'defaultType': 'swap', 'fetchMarkets': "
        r"\{'types': \['swap'\]\}\}, 'httpsProxy':)$"
    ),
    re.compile(r'^freqtrade\.exchange\.exchange\|INFO\|Using Exchange "(?:Bitget|OKX)"$'),
    re.compile(
        r"^freqtrade\.exchange\.common\|WARNING\|_load_async_markets\(\) returned "
        r"exception: \"Error in reload_markets due to ExchangeNotAvailable\. "
        r"Message: (?:bitget|okx) GET$"
    ),
)
APPROVED_RAW_LINES = {
    "'options': {'defaultType': 'spot', 'fetchMarkets': {'types': ['spot']}}}",
    "'http://host.docker.internal:12639', 'wsProxy': 'http://host.docker.internal:12639'}",
    "Traceback (most recent call last):",
    "The above exception was the direct cause of the following exception:",
    "    resp = await self._resolver.getaddrinfo(",
    "    ...<5 lines>...",
    "    )",
    "    hosts = await self._resolve_host(host, port, traces=traces)",
    "    return await asyncio.shield(resolved_host_task)",
    "    addrs = await self._resolver.resolve(host, port, family=self._family)",
    "    raise OSError(None, msg) from exc",
    "    async with session_method(yarl.URL(url, encoded=True),",
    "                              data=encoded_body,",
    "                              headers=request_headers,",
    "                              timeout=(self.timeout / 1000),",
    "                              proxy=final_proxy) as response:",
    "    self._resp: _RetType_co = await self._coro",
    "    resp = await handler(req)",
    "    conn = await self._connector.connect(",
    "        req, traces=traces, timeout=real_timeout",
    "    proto = await self._create_connection(req, traces, timeout)",
    "    _, proto = await self._create_proxy_connection(req, traces, timeout)",
    "    transport, proto = await self._create_direct_connection(",
    "        proxy_req, [], timeout, client_error=ClientProxyConnectionError",
    "    raise ClientConnectorDNSError(req.connection_key, exc) from exc",
    "    await self._api_async.load_markets(reload=reload, params={})",
    "    raise e",
    "    result = await self.markets_loading",
    "    currencies = await self.fetch_currencies()",
    "    response = await self.publicSpotGetV2SpotPublicCoins(params)",
    "    markets = await self.fetch_markets(params)",
    "    promises = await asyncio.gather(*promises)",
    "    response = await self.publicGetPublicInstruments(self.extend(request, params))",
    "    return await self.fetch2(path, api, method, params, headers, body, config)",
    "    return await self.fetch(request['url'], request['method'], "
    "request['headers'], request['body'])",
    "    raise ExchangeNotAvailable(details) from e",
    "    retrier(self._load_async_markets, retries=retries)(reload=True)",
    "    return wrapper(*args, **kwargs)",
    "    raise ex",
    "    return f(*args, **kwargs)",
    "    markets = self.loop.run_until_complete(self._api_reload_markets(reload=reload))",
    "    return future.result()",
    "    raise TemporaryError(",
    '        f"Error in reload_markets due to {e.__class__.__name__}. Message: {e}"',
    "    ) from e",
}
APPROVED_RAW_LINE_PATTERNS = (
    re.compile(r"^\s*[\^~]+$"),
    re.compile(
        r'^  File "(?:/home/ftuser/\.local/lib/python3\.14/site-packages/'
        r"(?:aiohttp/(?:resolver|connector|client)\.py|ccxt/async_support/"
        r"(?:base/exchange|bitget|okx)\.py)|/freqtrade/freqtrade/exchange/"
        r"(?:exchange|common)\.py|/usr/local/lib/python3\.14/asyncio/base_events\.py)"
        r'", line \d+, in [a-zA-Z0-9_]+$'
    ),
    re.compile(r"^aiodns\.error\.DNSError: \(11, 'Could not contact DNS servers'\)$"),
    re.compile(r"^OSError: \[Errno None\] Could not contact DNS servers$"),
    re.compile(
        r"^aiohttp\.client_exceptions\.ClientConnectorDNSError: Cannot connect to "
        r"host host\.docker\.internal:12639 ssl:default "
        r"\[Could not contact DNS servers\]$"
    ),
    re.compile(
        r"^(?:https://api\.bitget\.com/api/v2/spot/public/coins|"
        r"https://www\.okx\.com/api/v5/public/instruments\?instType=SWAP)\"\. "
        r"(?:Retrying still for [123] times|Giving up)\.$"
    ),
    re.compile(
        r"^ccxt\.base\.errors\.ExchangeNotAvailable: (?:bitget GET "
        r"https://api\.bitget\.com/api/v2/spot/public/coins|okx GET "
        r"https://www\.okx\.com/api/v5/public/instruments\?instType=SWAP)$"
    ),
    re.compile(
        r"^freqtrade\.exceptions\.TemporaryError: Error in reload_markets due to "
        r"ExchangeNotAvailable\. Message: (?:bitget GET "
        r"https://api\.bitget\.com/api/v2/spot/public/coins|okx GET "
        r"https://www\.okx\.com/api/v5/public/instruments\?instType=SWAP)$"
    ),
)


@dataclass(frozen=True)
class StartupExpectation:
    service: str
    command: tuple[str, ...]
    requires_healthcheck: bool
    accepted_network_error_markers: tuple[str, ...]


STARTUP_EXPECTATIONS = {
    "freqtrade": StartupExpectation(
        service="freqtrade",
        command=(),
        requires_healthcheck=False,
        accepted_network_error_markers=(EXTERNAL_NETWORK_BOUNDARY,),
    ),
    "freqtrade-futures": StartupExpectation(
        service="freqtrade-futures",
        command=(),
        requires_healthcheck=False,
        accepted_network_error_markers=(EXTERNAL_NETWORK_BOUNDARY,),
    ),
    "freqtrade-research": StartupExpectation(
        service="freqtrade-research",
        command=(),
        requires_healthcheck=True,
        accepted_network_error_markers=(),
    ),
}

CONFIG_TEMPLATES = {
    "freqtrade": "ft_userdata/user_data/config.example.json",
    "freqtrade-futures": "ft_userdata/user_data/config.volatility.futures.example.json",
    "freqtrade-research": "ft_userdata/user_data/config.research.example.json",
}
SECRET_NAMES = ("api_password", "jwt_secret_key", "ws_token")
SECRET_ENVIRONMENT = {
    "api_password": "FT_API_PASSWORD_FILE",
    "jwt_secret_key": "FT_JWT_SECRET_FILE",
    "ws_token": "FT_WS_TOKEN_FILE",
}
FORBIDDEN_FAILURE_MARKERS = (
    "fatal:",
    "secret file is unavailable",
    "secret does not meet runtime policy",
    "permission denied",
    "impossible to load strategy",
    "unable to open database file",
    "operationalerror",
)


def formal_command(compose: Mapping[str, Any], service: str) -> tuple[str, ...]:
    try:
        command = compose["services"][service]["command"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{service} formal command is unavailable") from exc
    if not isinstance(command, list) or not command or not all(
        isinstance(argument, str) and argument for argument in command
    ):
        raise ValueError(f"{service} formal command is invalid")
    return tuple(command)


def _mount(source: Path, target: str, *, read_only: bool) -> str:
    option = f"type=bind,source={source.resolve()},target={target}"
    return f"{option},readonly" if read_only else option


def build_offline_docker_command(
    *,
    image: str,
    expectation: StartupExpectation,
    runtime_uid: int,
    runtime_gid: int,
    repo_root: Path,
    probe_root: Path,
) -> list[str]:
    if runtime_uid <= 0 or runtime_gid <= 0 or runtime_uid == 1000 or runtime_gid == 1000:
        raise ValueError("formal startup requires a dynamic non-root identity")

    command = ["docker", "run"]
    if expectation.requires_healthcheck:
        command.extend(["--detach", "--cidfile", str((probe_root / "container.cid").resolve())])
    else:
        command.extend(
            [
                "--detach",
                "--cidfile",
                str((probe_root / "container.cid").resolve()),
            ]
        )
    command.extend(
        [
            "--network",
            "none",
            "--user",
            f"{runtime_uid}:{runtime_gid}",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev",
            "--env",
            "HOME=/freqtrade/state/home",
        ]
    )
    for secret_name in SECRET_NAMES:
        target = f"/run/secrets/{secret_name}"
        command.extend(["--env", f"{SECRET_ENVIRONMENT[secret_name]}={target}"])
    command.extend(
        [
            "--mount",
            _mount(probe_root / "state", "/freqtrade/state", read_only=False),
            "--mount",
            _mount(
                probe_root / "config" / "runtime.json",
                "/freqtrade/config/runtime.json",
                read_only=True,
            ),
            "--mount",
            _mount(
                repo_root / "ops" / "config" / "trading-safety.json",
                "/freqtrade/config/trading-safety.json",
                read_only=True,
            ),
            "--mount",
            _mount(
                repo_root / "ft_userdata" / "user_data" / "strategies",
                "/freqtrade/user_data/strategies",
                read_only=True,
            ),
        ]
    )
    if expectation.service == "freqtrade-research":
        command.extend(
            [
                "--mount",
                _mount(
                    repo_root / "ft_userdata" / "user_data" / "research_data",
                    "/freqtrade/user_data/research_data",
                    read_only=True,
                ),
            ]
        )
    for secret_name in SECRET_NAMES:
        command.extend(
            [
                "--mount",
                _mount(
                    probe_root / "secrets" / secret_name,
                    f"/run/secrets/{secret_name}",
                    read_only=True,
                ),
            ]
        )
    command.extend([image, *expectation.command])
    return command


def verify_startup_result(
    expectation: StartupExpectation,
    completed: subprocess.CompletedProcess[str],
) -> None:
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    normalized = output.casefold()
    if any(marker in normalized for marker in FORBIDDEN_FAILURE_MARKERS):
        raise RuntimeError(f"{expectation.service} formal startup verification failed")
    if expectation.requires_healthcheck:
        if completed.returncode == 0:
            return
    elif _is_expected_trading_boundary(expectation, completed.returncode, output):
        return
    raise RuntimeError(f"{expectation.service} formal startup verification failed")


def _is_expected_trading_boundary(
    expectation: StartupExpectation, returncode: int, output: str
) -> bool:
    if returncode == 0 or len(expectation.accepted_network_error_markers) != 1:
        return False
    boundary = expectation.accepted_network_error_markers[0]
    lines = [
        ANSI_ESCAPE.sub("", line).rstrip()
        for line in output.splitlines()
        if ANSI_ESCAPE.sub("", line).strip()
    ]
    if not lines or not all(_is_approved_trading_line(line) for line in lines):
        return False
    final_record = LOG_LINE.fullmatch(lines[-1])
    if final_record is None or (
        final_record.group("logger"),
        final_record.group("level"),
        final_record.group("message"),
    ) != ("freqtrade", "ERROR", boundary):
        return False
    normalized_output = "\n".join(lines)
    search_from = 0
    for milestone in (*TRADING_STARTUP_MILESTONES, boundary):
        position = normalized_output.find(milestone, search_from)
        if position < 0:
            return False
        search_from = position + len(milestone)
    return True


def _is_approved_trading_line(line: str) -> bool:
    log_record = LOG_LINE.fullmatch(line)
    if log_record is not None:
        record = (
            log_record.group("logger"),
            log_record.group("level"),
            log_record.group("message"),
        )
        if record in APPROVED_LOG_RECORDS:
            return True
        encoded = "|".join(record)
        return any(pattern.fullmatch(encoded) for pattern in APPROVED_LOG_RECORD_PATTERNS)
    if line in APPROVED_RAW_LINES:
        return True
    return any(pattern.fullmatch(line) for pattern in APPROVED_RAW_LINE_PATTERNS)


def verify_formal_startup(
    service: str,
    *,
    image: str,
    repo_root: Path,
    runtime_uid: int = 12345,
    runtime_gid: int = 12345,
    timeout_seconds: int = 45,
) -> None:
    if service not in STARTUP_EXPECTATIONS:
        raise ValueError("unsupported formal service")
    rendered = subprocess.run(
        [
            "docker",
            "compose",
            "--profile",
            "trading",
            "--profile",
            "research",
            "config",
            "--format",
            "json",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if rendered.returncode != 0:
        raise RuntimeError(f"{service} formal startup verification failed")
    try:
        compose = json.loads(rendered.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{service} formal startup verification failed") from exc
    expectation = replace(
        STARTUP_EXPECTATIONS[service], command=formal_command(compose, service)
    )

    with tempfile.TemporaryDirectory(prefix=f"formal-startup-{service}-") as temporary:
        probe_root = Path(temporary)
        _prepare_probe(expectation, repo_root=repo_root, probe_root=probe_root)
        command = build_offline_docker_command(
            image=image,
            expectation=expectation,
            runtime_uid=runtime_uid,
            runtime_gid=runtime_gid,
            repo_root=repo_root,
            probe_root=probe_root,
        )
        cid_path = probe_root / "container.cid"
        verification_succeeded = False
        try:
            if expectation.requires_healthcheck:
                _verify_research_startup(
                    expectation,
                    command=command,
                    cid_path=cid_path,
                    timeout_seconds=timeout_seconds,
                )
            else:
                _verify_trading_startup(
                    expectation,
                    command=command,
                    cid_path=cid_path,
                    timeout_seconds=timeout_seconds,
                )
            verification_succeeded = True
        finally:
            if cid_path.is_file():
                container_id = cid_path.read_text(encoding="utf-8").strip()
                if container_id:
                    try:
                        _cleanup_container(expectation.service, container_id)
                    except RuntimeError:
                        if verification_succeeded:
                            raise


def _cleanup_container(service: str, container_id: str) -> None:
    failed = False
    commands = (
        ["docker", "stop", "--time", "5", container_id],
        ["docker", "rm", "--force", container_id],
    )
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            failed = True
        else:
            failed = failed or completed.returncode != 0
    if failed:
        raise RuntimeError(f"{service} formal startup verification failed")


def _prepare_probe(
    expectation: StartupExpectation, *, repo_root: Path, probe_root: Path
) -> None:
    config_directory = probe_root / "config"
    secret_directory = probe_root / "secrets"
    state_root = probe_root / "state"
    config_directory.mkdir()
    secret_directory.mkdir()
    for relative in ("", "home", "logs", "data", "backtest_results"):
        directory = state_root / relative
        directory.mkdir(exist_ok=True)
        os.chmod(directory, 0o707)

    template = repo_root / CONFIG_TEMPLATES[expectation.service]
    runtime_config = config_directory / "runtime.json"
    shutil.copyfile(template, runtime_config)
    config = json.loads(runtime_config.read_text(encoding="utf-8"))
    safety = json.loads(
        (repo_root / "ops" / "config" / "trading-safety.json").read_text(
            encoding="utf-8"
        )
    )
    if config.get("dry_run") is not True or safety.get("dry_run") is not True:
        raise RuntimeError(f"{expectation.service} formal startup verification failed")

    for secret_name in SECRET_NAMES:
        secret_path = secret_directory / secret_name
        secret_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        os.chmod(secret_path, 0o604)


def _verify_research_startup(
    expectation: StartupExpectation,
    *,
    command: list[str],
    cid_path: Path,
    timeout_seconds: int,
) -> None:
    launched = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    verify_startup_result(expectation, launched)
    if not cid_path.is_file():
        raise RuntimeError(f"{expectation.service} formal startup verification failed")
    container_id = cid_path.read_text(encoding="utf-8").strip()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        ping = subprocess.run(
            [
                "docker",
                "exec",
                container_id,
                "curl",
                "-fsS",
                "http://127.0.0.1:8080/api/v1/ping",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        if ping.returncode == 0:
            break
        time.sleep(0.5)
    else:
        raise RuntimeError(f"{expectation.service} formal startup verification failed")

def _verify_trading_startup(
    expectation: StartupExpectation,
    *,
    command: list[str],
    cid_path: Path,
    timeout_seconds: int,
) -> None:
    launched = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    if launched.returncode != 0 or not cid_path.is_file():
        raise RuntimeError(f"{expectation.service} formal startup verification failed")
    container_id = cid_path.read_text(encoding="utf-8").strip()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        logs = subprocess.run(
            ["docker", "logs", container_id],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        output = f"{logs.stdout or ''}\n{logs.stderr or ''}"
        if any(marker in output.casefold() for marker in FORBIDDEN_FAILURE_MARKERS):
            raise RuntimeError(f"{expectation.service} formal startup verification failed")
        if any(marker in output for marker in expectation.accepted_network_error_markers):
            verify_startup_result(
                expectation, subprocess.CompletedProcess([], 2, output, "")
            )
            break
        running = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container_id],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        if running.returncode != 0 or running.stdout.strip() != "true":
            raise RuntimeError(f"{expectation.service} formal startup verification failed")
        time.sleep(0.5)
    else:
        raise RuntimeError(f"{expectation.service} formal startup verification failed")

def main(arguments: Sequence[str] | None = None) -> int:
    supplied = list(arguments if arguments is not None else sys.argv[1:])
    if len(supplied) != 3 or supplied[:2] != ["verify-all", "--image"]:
        sys.stderr.write("formal startup: unsupported arguments\n")
        return 64
    image = supplied[2]
    try:
        for service in STARTUP_EXPECTATIONS:
            verify_formal_startup(service, image=image, repo_root=REPO_ROOT)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        sys.stderr.write("formal startup: verification failed\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
