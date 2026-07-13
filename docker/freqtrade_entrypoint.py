from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping, MutableMapping, NoReturn, Sequence


SENTINEL = "__SET_VIA_SECRET_FILE__"
SECRET_SPECS = (
    ("FT_API_PASSWORD_FILE", "FREQTRADE__API_SERVER__PASSWORD", 24),
    ("FT_JWT_SECRET_FILE", "FREQTRADE__API_SERVER__JWT_SECRET_KEY", 32),
    ("FT_WS_TOKEN_FILE", "FREQTRADE__API_SERVER__WS_TOKEN", 32),
)


class SecretConfigurationError(RuntimeError):
    pass


def _read_secret(path_text: str, label: str, minimum_length: int) -> str:
    path = Path(path_text)
    if not path.is_file():
        raise SecretConfigurationError(f"{label} secret file is unavailable")
    try:
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError) as exc:
        raise SecretConfigurationError(f"{label} secret file cannot be read") from exc
    if "\r" in value or "\n" in value:
        raise SecretConfigurationError(f"{label} secret must be one line")
    if "\x00" in value:
        raise SecretConfigurationError(f"{label} secret must not contain null bytes")
    if len(value) < minimum_length or value == SENTINEL:
        raise SecretConfigurationError(f"{label} secret does not meet runtime policy")
    return value


def load_api_secrets(environ: Mapping[str, str]) -> dict[str, str]:
    loaded: dict[str, str] = {}
    for file_variable, target_variable, minimum_length in SECRET_SPECS:
        path_text = environ.get(file_variable)
        if not path_text:
            raise SecretConfigurationError(f"{file_variable} is required")
        loaded[target_variable] = _read_secret(
            path_text, target_variable, minimum_length
        )
    if len(set(loaded.values())) != len(loaded):
        raise SecretConfigurationError(
            "API password, JWT secret and WS token must be distinct"
        )
    return loaded


def main(
    argv: Sequence[str],
    environ: MutableMapping[str, str] = os.environ,
) -> NoReturn:
    try:
        environ.update(load_api_secrets(environ))
    except SecretConfigurationError as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        raise SystemExit(78) from exc
    os.execvpe("freqtrade", ["freqtrade", *argv], dict(environ))


if __name__ == "__main__":
    main(sys.argv[1:])
