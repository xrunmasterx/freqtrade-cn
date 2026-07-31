from __future__ import annotations

import json
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tools.committed_build import CommitIdentity
from tools import image_provenance


IDENTITY = CommitIdentity("a" * 40, "b" * 40, "c" * 40)
REPO_ROOT = Path(__file__).resolve().parents[1]


class ImageProvenanceTests(unittest.TestCase):
    def test_tag_contains_three_short_committed_revisions(self) -> None:
        self.assertEqual(
            image_provenance.provenance_tag(IDENTITY),
            f"freqtrade-cn:p0-{'a' * 12}-{'b' * 12}-{'c' * 12}",
        )

    def test_build_uses_committed_context_revision_and_complete_labels(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "docker progress", "private detail")
        with tempfile.TemporaryDirectory() as directory:
            context = Path(directory)
            with mock.patch.object(
                image_provenance.subprocess, "run", return_value=completed
            ) as run:
                reference = image_provenance.build_committed_image(context, IDENTITY)

        self.assertEqual(reference, image_provenance.provenance_tag(IDENTITY))
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["docker", "build", "--tag"])
        self.assertEqual(command[3], reference)
        self.assertEqual(command[-1], str(context))
        self.assertIn(f"FREQUI_COMMIT_HASH={IDENTITY.frontend}", command)
        for name, value in image_provenance.expected_labels(IDENTITY).items():
            self.assertIn(f"{name}={value}", command)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(run.call_args.kwargs["timeout"], 1800)
        self.assertIs(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_operator_build_has_fixed_target_tag_and_root_commit_argument(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "docker progress", "private detail")
        with tempfile.TemporaryDirectory() as directory:
            context = Path(directory)
            with mock.patch.object(
                image_provenance.subprocess, "run", return_value=completed
            ) as run:
                reference = image_provenance.build_committed_operator_image(
                    context,
                    IDENTITY,
                )

        self.assertEqual(
            reference,
            f"freqtrade-cn-operator:p0-{'a' * 12}-{'b' * 12}-{'c' * 12}",
        )
        self.assertEqual(
            run.call_args.args[0],
            [
                "docker",
                "build",
                "--tag",
                reference,
                "--target",
                "platform-operator-image",
                "--build-arg",
                f"PLATFORM_OPERATOR_ROOT_COMMIT={IDENTITY.root}",
                "--build-arg",
                f"FREQUI_COMMIT_HASH={IDENTITY.frontend}",
                "--label",
                f"org.freqtrade-cn.revision.root={IDENTITY.root}",
                "--label",
                f"org.freqtrade-cn.revision.backend={IDENTITY.backend}",
                "--label",
                f"org.freqtrade-cn.revision.frontend={IDENTITY.frontend}",
                str(context),
            ],
        )
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(run.call_args.kwargs["timeout"], 1800)

    def test_operator_command_builds_and_verifies_only_the_fixed_operator_image(self) -> None:
        image = image_provenance.InspectedImage(
            "sha256:" + "d" * 64,
            f"freqtrade-cn-operator:p0-{'a' * 12}-{'b' * 12}-{'c' * 12}",
            image_provenance.expected_labels(IDENTITY),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                image_provenance, "resolve_commit_identity", return_value=IDENTITY
            ),
            mock.patch.object(image_provenance, "committed_build_context") as context,
            mock.patch.object(
                image_provenance,
                "build_and_inspect_operator_image",
                return_value=image,
            ) as build_operator,
            mock.patch.object(image_provenance, "build_and_inspect_image") as build_runtime,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            context.return_value.__enter__.return_value = Path("committed")
            result = image_provenance.main(["build-operator", "--print-image-id"])

        self.assertEqual(
            (result, stdout.getvalue(), stderr.getvalue()),
            (0, f"{image.image_id}\n", ""),
        )
        build_operator.assert_called_once_with(Path("committed"), IDENTITY)
        build_runtime.assert_not_called()

    def test_print_image_id_stdout_contains_only_one_image_id(self) -> None:
        image = image_provenance.InspectedImage(
            "sha256:" + "d" * 64,
            image_provenance.provenance_tag(IDENTITY),
            image_provenance.expected_labels(IDENTITY),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                image_provenance, "resolve_commit_identity", return_value=IDENTITY
            ),
            mock.patch.object(image_provenance, "committed_build_context") as context,
            mock.patch.object(
                image_provenance, "build_and_inspect_image", return_value=image
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            context.return_value.__enter__.return_value = Path("committed")
            result = image_provenance.main(["build", "--print-image-id"])
        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), f"{image.image_id}\n")
        self.assertEqual(stderr.getvalue(), "")

    def test_embedded_ui_version_uses_isolated_immutable_image(self) -> None:
        image_id = "sha256:" + "d" * 64
        completed = subprocess.CompletedProcess(
            [], 0, image_provenance.expected_ui_version(IDENTITY), ""
        )
        with mock.patch.object(
            image_provenance.subprocess, "run", return_value=completed
        ) as run:
            image_provenance.verify_embedded_ui_version(image_id, IDENTITY)

        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        self.assertIn("--network", command)
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertIn("--read-only", command)
        self.assertEqual(command[command.index("--cap-drop") + 1], "ALL")
        self.assertEqual(
            command[command.index("--security-opt") + 1], "no-new-privileges"
        )
        self.assertEqual(command[command.index("--user") + 1], "1000:1000")
        self.assertEqual(Path(command[command.index("--cidfile") + 1]).name, "container.cid")
        self.assertEqual(command[command.index("--entrypoint") + 1], "python")
        self.assertEqual(command[command.index(image_id) : -2], [image_id])
        self.assertEqual(command[-2], "-c")
        self.assertIn(image_provenance.UI_VERSION_PATH, command[-1])
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertTrue(run.call_args.kwargs["text"])
        self.assertEqual(
            run.call_args.kwargs["timeout"], image_provenance.UI_VERSION_TIMEOUT_SECONDS
        )

    def test_embedded_ui_version_rejects_non_exact_output(self) -> None:
        image_id = "sha256:" + "d" * 64
        expected = image_provenance.expected_ui_version(IDENTITY)
        for output in ("", "unknown", "local-frequi-short", expected + "\n", expected + "0"):
            with self.subTest(output=output):
                completed = subprocess.CompletedProcess([], 0, output, "")
                with mock.patch.object(
                    image_provenance.subprocess, "run", return_value=completed
                ):
                    with self.assertRaises(ValueError):
                        image_provenance.verify_embedded_ui_version(image_id, IDENTITY)

    def test_embedded_ui_version_timeout_removes_captured_container(self) -> None:
        image_id = "sha256:" + "d" * 64
        container_id = "e" * 64
        commands: list[list[str]] = []

        def run(command, **_kwargs):
            commands.append(command)
            if command[:2] == ["docker", "run"]:
                cidfile = Path(command[command.index("--cidfile") + 1])
                cidfile.write_text(container_id, encoding="ascii")
                raise subprocess.TimeoutExpired(command, 1)
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(image_provenance.subprocess, "run", side_effect=run):
            with self.assertRaises(ValueError):
                image_provenance.verify_embedded_ui_version(
                    image_id, IDENTITY, timeout_seconds=1
                )

        self.assertEqual(
            commands[1], ["docker", "container", "rm", "--force", container_id]
        )

    def test_reviewed_builds_verify_ui_from_the_immutable_image_id(self) -> None:
        cases = (
            (
                "build_and_inspect_image",
                "build_committed_image",
                "verify_image_provenance",
                image_provenance.provenance_tag(IDENTITY),
            ),
            (
                "build_and_inspect_operator_image",
                "build_committed_operator_image",
                "verify_operator_image_provenance",
                image_provenance.operator_provenance_tag(IDENTITY),
            ),
        )
        for entrypoint, builder, label_verifier, tag in cases:
            with self.subTest(entrypoint=entrypoint):
                image = image_provenance.InspectedImage(
                    "sha256:" + "d" * 64,
                    tag,
                    image_provenance.expected_labels(IDENTITY),
                )
                with (
                    mock.patch.object(image_provenance, builder, return_value=tag),
                    mock.patch.object(image_provenance, "inspect_image", return_value=image),
                    mock.patch.object(image_provenance, label_verifier),
                    mock.patch.object(
                        image_provenance, "verify_embedded_ui_version"
                    ) as verify_ui,
                ):
                    result = getattr(image_provenance, entrypoint)(Path("context"), IDENTITY)

                self.assertIs(result, image)
                verify_ui.assert_called_once_with(image.image_id, IDENTITY)

    def test_workflow_keeps_render_artifact_outside_committed_checkout(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/root-safety.yml").read_text(
            encoding="utf-8"
        )
        render = workflow.index("      - name: Render and enforce Compose")
        build = workflow.index("      - name: Build integrated image")
        render_step = workflow[render:build]
        self.assertIn('${RUNNER_TEMP}/compose.rendered.json', render_step)
        self.assertNotIn("> compose.rendered.json", render_step)
        self.assertLess(render, build)

    def test_inspect_requires_sha256_image_id_and_exact_complete_labels(self) -> None:
        labels = image_provenance.expected_labels(IDENTITY)
        output = json.dumps([{"Id": "sha256:" + "d" * 64, "Config": {"Labels": labels}}])
        completed = subprocess.CompletedProcess([], 0, output, "")
        with mock.patch.object(image_provenance.subprocess, "run", return_value=completed):
            image = image_provenance.inspect_image("reviewed")
        self.assertEqual(image.image_id, "sha256:" + "d" * 64)
        self.assertEqual(image.tag, "reviewed")
        self.assertEqual(image.labels, labels)

        for malformed in (
            "[]",
            json.dumps([{}, {}]),
            json.dumps([{"Id": "reviewed:latest", "Config": {"Labels": labels}}]),
            json.dumps([{"Id": "sha256:short", "Config": {"Labels": labels}}]),
        ):
            with self.subTest(malformed=malformed):
                completed = subprocess.CompletedProcess([], 0, malformed, "")
                with mock.patch.object(
                    image_provenance.subprocess, "run", return_value=completed
                ):
                    with self.assertRaises(ValueError):
                        image_provenance.inspect_image("reviewed")

    def test_rejects_missing_mismatched_or_extra_identity_labels(self) -> None:
        expected = image_provenance.expected_labels(IDENTITY)
        mutations = []
        missing = dict(expected)
        missing.pop(next(iter(missing)))
        mutations.append(missing)
        mismatched = dict(expected)
        mismatched[next(iter(mismatched))] = "d" * 40
        mutations.append(mismatched)
        extra = dict(expected)
        extra["org.freqtrade-cn.revision.extra"] = "e" * 40
        mutations.append(extra)
        for labels in mutations:
            with self.subTest(labels=labels):
                image = image_provenance.InspectedImage(
                    "sha256:" + "d" * 64,
                    image_provenance.provenance_tag(IDENTITY),
                    labels,
                )
                with self.assertRaises(ValueError):
                    image_provenance.verify_image_provenance(image, IDENTITY)

    def test_operator_verification_requires_the_commit_qualified_tag(self) -> None:
        expected_tag = (
            f"freqtrade-cn-operator:p0-{'a' * 12}-{'b' * 12}-{'c' * 12}"
        )
        labels = image_provenance.expected_labels(IDENTITY)
        image_provenance.verify_operator_image_provenance(
            image_provenance.InspectedImage(
                "sha256:" + "d" * 64,
                expected_tag,
                labels,
            ),
            IDENTITY,
        )
        with self.assertRaises(ValueError):
            image_provenance.verify_operator_image_provenance(
                image_provenance.InspectedImage(
                    "sha256:" + "d" * 64,
                    "freqtrade-cn-operator:local",
                    labels,
                ),
                IDENTITY,
            )


if __name__ == "__main__":
    unittest.main()
