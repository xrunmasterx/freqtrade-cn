from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import compose_runtime


class ComposeRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        (self.root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        override = self.root / "ft_userdata/runtime/compose.identity.yml"
        override.parent.mkdir(parents=True)
        override.write_text('{"services": {}}\n', encoding="utf-8")

    def test_run_verifies_then_uses_literal_override_and_clean_environment(self) -> None:
        manifest = {"services": []}
        completed = subprocess.CompletedProcess([], 17, "", "")
        events = []

        def verify(root: Path, loaded_manifest: object) -> None:
            events.append(("verify", root, loaded_manifest))

        def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
            events.append(("run", command, options))
            return completed

        with (
            mock.patch.object(compose_runtime, "load_runtime_manifest", return_value=manifest),
            mock.patch.object(compose_runtime, "verify_runtime", side_effect=verify),
            mock.patch.object(compose_runtime.subprocess, "run", side_effect=run),
            mock.patch.dict(
                os.environ,
                {
                    "KEEP_ME": "yes",
                    "FREQTRADE_RUNTIME_UID": "0",
                    "FREQTRADE_RUNTIME_GID": "0",
                },
                clear=True,
            ),
        ):
            result = compose_runtime.run_compose(
                ["--profile", "trading", "config"],
                root=self.root,
            )

        self.assertIs(result, completed)
        self.assertEqual(events[0], ("verify", self.root.resolve(), manifest))
        command = events[1][1]
        self.assertEqual(
            command,
            [
                "docker",
                "compose",
                "-f",
                str(self.root / "docker-compose.yml"),
                "-f",
                str(self.root / "ft_userdata/runtime/compose.identity.yml"),
                "--profile",
                "trading",
                "config",
            ],
        )
        options = events[1][2]
        self.assertNotIn("shell", options)
        self.assertEqual(options["cwd"], self.root.resolve())
        self.assertEqual(options["env"], {"KEEP_ME": "yes"})

    def test_render_compose_parses_wrapper_output(self) -> None:
        completed = subprocess.CompletedProcess(
            [],
            0,
            json.dumps({"services": {"freqtrade": {"user": "1001:1002"}}}),
            "",
        )
        with mock.patch.object(compose_runtime, "run_compose", return_value=completed):
            rendered = compose_runtime.render_compose(root=self.root)
        self.assertEqual(rendered["services"]["freqtrade"]["user"], "1001:1002")

    def test_main_returns_fixed_error_without_leaking_details(self) -> None:
        secret = "detail-that-must-not-leak"
        with (
            mock.patch.object(
                compose_runtime,
                "run_compose",
                side_effect=ValueError(secret),
            ),
            mock.patch("sys.stderr") as stderr,
        ):
            result = compose_runtime.main(["config"])
        self.assertEqual(result, 78)
        message = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertEqual(message, "compose runtime: verification failed\n")
        self.assertNotIn(secret, message)


if __name__ == "__main__":
    unittest.main()
