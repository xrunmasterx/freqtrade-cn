from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from docker import freqtrade_entrypoint as entrypoint


class EntrypointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)

    def secret_environment(
        self,
        *,
        api_password: str = "api-password-that-is-long-enough",
        jwt_secret: str = "jwt-secret-that-is-at-least-thirty-two-characters",
        ws_token: str = "ws-token-that-is-at-least-thirty-two-characters",
    ) -> dict[str, str]:
        root = Path(self.temp_directory.name)
        secret_values = {
            "FT_API_PASSWORD_FILE": api_password,
            "FT_JWT_SECRET_FILE": jwt_secret,
            "FT_WS_TOKEN_FILE": ws_token,
        }
        environ: dict[str, str] = {}
        for variable, value in secret_values.items():
            path = root / variable.lower()
            path.write_text(value, encoding="utf-8")
            environ[variable] = str(path)
        return environ

    def test_load_api_secrets_reads_three_distinct_values(self) -> None:
        environ = self.secret_environment()

        loaded = entrypoint.load_api_secrets(environ)

        self.assertEqual(
            set(loaded),
            {
                "FREQTRADE__API_SERVER__PASSWORD",
                "FREQTRADE__API_SERVER__JWT_SECRET_KEY",
                "FREQTRADE__API_SERVER__WS_TOKEN",
            },
        )

    def test_missing_file_environment_variable_fails_closed(self) -> None:
        environ = self.secret_environment()
        del environ["FT_API_PASSWORD_FILE"]

        with self.assertRaisesRegex(
            entrypoint.SecretConfigurationError, "FT_API_PASSWORD_FILE is required"
        ):
            entrypoint.load_api_secrets(environ)

    def test_missing_secret_file_fails_without_value_leak(self) -> None:
        environ = self.secret_environment()
        secret = "api-password-that-must-not-leak"
        Path(environ["FT_API_PASSWORD_FILE"]).write_text(secret, encoding="utf-8")
        Path(environ["FT_API_PASSWORD_FILE"]).unlink()

        with self.assertRaisesRegex(
            entrypoint.SecretConfigurationError, "secret file is unavailable"
        ) as raised:
            entrypoint.load_api_secrets(environ)
        self.assertNotIn(secret, str(raised.exception))

    @mock.patch("pathlib.Path.read_text", side_effect=OSError("private-detail"))
    def test_unreadable_secret_file_fails_without_detail_leak(self, read_text) -> None:
        environ = self.secret_environment()

        with self.assertRaisesRegex(
            entrypoint.SecretConfigurationError, "secret file cannot be read"
        ) as raised:
            entrypoint.load_api_secrets(environ)
        self.assertNotIn("private-detail", str(raised.exception))

    def test_multiline_secret_fails_closed(self) -> None:
        secret = "first-line-is-long-enough-to-pass-policy\nsecond-line-is-secret"
        environ = self.secret_environment(api_password=secret)

        with self.assertRaisesRegex(
            entrypoint.SecretConfigurationError, "secret must be one line"
        ) as raised:
            entrypoint.load_api_secrets(environ)
        self.assertNotIn(secret, str(raised.exception))

    def test_short_placeholder_and_duplicate_values_fail_closed(self) -> None:
        for invalid in ("short", entrypoint.SENTINEL):
            with self.subTest(invalid=invalid):
                environ = self.secret_environment(api_password=invalid)
                with self.assertRaises(entrypoint.SecretConfigurationError) as raised:
                    entrypoint.load_api_secrets(environ)
                self.assertNotIn(invalid, str(raised.exception))

        duplicate = "same-value-that-is-at-least-thirty-two-characters"
        environ = self.secret_environment(
            api_password=duplicate,
            ws_token=duplicate,
        )
        with self.assertRaisesRegex(
            entrypoint.SecretConfigurationError, "must be distinct"
        ) as raised:
            entrypoint.load_api_secrets(environ)
        self.assertNotIn(duplicate, str(raised.exception))

    @mock.patch("docker.freqtrade_entrypoint.os.execvpe")
    def test_main_execs_freqtrade_with_loaded_environment(self, execvpe) -> None:
        environ = self.secret_environment()

        entrypoint.main(["--version"], environ)

        args = execvpe.call_args.args
        self.assertEqual(args[0], "freqtrade")
        self.assertEqual(args[1], ["freqtrade", "--version"])
        self.assertIn("FREQTRADE__API_SERVER__PASSWORD", args[2])

    @mock.patch("docker.freqtrade_entrypoint.os.execvpe")
    def test_main_error_exits_78_without_exec_or_secret_leak(self, execvpe) -> None:
        secret = "api-password-that-must-never-reach-stderr"
        environ = self.secret_environment(api_password=secret)
        Path(environ["FT_API_PASSWORD_FILE"]).unlink()
        stderr = io.StringIO()

        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            entrypoint.main([], environ)

        self.assertEqual(raised.exception.code, 78)
        execvpe.assert_not_called()
        self.assertNotIn(secret, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
