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

    def test_build_uses_committed_context_and_complete_revision_labels(self) -> None:
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
        for name, value in image_provenance.expected_labels(IDENTITY).items():
            self.assertIn(f"{name}={value}", command)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(run.call_args.kwargs["timeout"], 1800)
        self.assertIs(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

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


if __name__ == "__main__":
    unittest.main()
