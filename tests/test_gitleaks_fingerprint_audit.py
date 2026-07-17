from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.gitleaks_fingerprint_audit import (
    audit_fingerprint_files,
    expected_fingerprint_counts,
    main,
)


class GitleaksFingerprintAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.findings_path = self.root / "findings.json"
        self.expected_path = self.root / "expected-ignore"

    def write_case(self, findings: list[str], expected: list[str]) -> None:
        self.findings_path.write_text(
            json.dumps([{"Fingerprint": fingerprint} for fingerprint in findings]),
            encoding="utf-8",
        )
        self.expected_path.write_text("\n".join(expected) + "\n", encoding="utf-8")

    def test_exact_duplicate_fingerprint_counts_match(self) -> None:
        self.write_case(
            [
                "docs/example.md:jwt:10",
                "docs/example.md:jwt:10",
                "tests/api.py:generic-api-key:20",
            ],
            [
                "# reviewed fixtures",
                "docs/example.md:jwt:10",
                "docs/example.md:jwt:10",
                "",
                "tests/api.py:generic-api-key:20",
            ],
        )

        self.assertTrue(
            audit_fingerprint_files(self.findings_path, self.expected_path)
        )

    def test_actual_duplicate_count_increase_or_decrease_fails(self) -> None:
        expected = ["docs/example.md:jwt:10", "docs/example.md:jwt:10"]
        for findings in (
            ["docs/example.md:jwt:10"],
            [
                "docs/example.md:jwt:10",
                "docs/example.md:jwt:10",
                "docs/example.md:jwt:10",
            ],
        ):
            with self.subTest(findings=len(findings)):
                self.write_case(findings, expected)
                self.assertFalse(
                    audit_fingerprint_files(self.findings_path, self.expected_path)
                )

    def test_expected_duplicate_count_change_fails(self) -> None:
        findings = ["docs/example.md:jwt:10", "docs/example.md:jwt:10"]
        for expected in (
            ["docs/example.md:jwt:10"],
            [
                "docs/example.md:jwt:10",
                "docs/example.md:jwt:10",
                "docs/example.md:jwt:10",
            ],
        ):
            with self.subTest(expected=len(expected)):
                self.write_case(findings, expected)
                self.assertFalse(
                    audit_fingerprint_files(self.findings_path, self.expected_path)
                )

    def test_cli_main_is_fail_closed_for_mismatch_and_malformed_findings(self) -> None:
        self.write_case(["docs/example.md:jwt:10"], ["docs/example.md:jwt:10"])
        arguments = [str(self.findings_path), str(self.expected_path)]

        self.assertEqual(main(arguments), 0)
        self.write_case([], ["docs/example.md:jwt:10"])
        with self.assertRaisesRegex(SystemExit, "fingerprint audit mismatch"):
            main(arguments)
        self.findings_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "JSON list"):
            main(arguments)
        with self.assertRaisesRegex(SystemExit, "usage"):
            main([])

        malformed_findings = (
            "not-json",
            "[null]",
            "[{}]",
            '[{"Fingerprint": ""}]',
            '[{"Fingerprint": 1}]',
        )
        for payload in malformed_findings:
            with self.subTest(payload=payload):
                self.findings_path.write_text(payload, encoding="utf-8")
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    main(arguments)

    def test_reviewed_platform_migration_fingerprints_track_current_tree(self) -> None:
        ignore_path = Path(__file__).resolve().parents[1] / ".gitleaksignore"
        fingerprints = expected_fingerprint_counts(
            ignore_path.read_text(encoding="utf-8").splitlines()
        )
        prefix = "freqtrade/tests/platform/test_platform_migrations.py:generic-api-key:"

        for line in (588, 1300, 1305, 1316):
            self.assertEqual(fingerprints[f"{prefix}{line}"], 1)
        for line in (576, 585, 1278, 1283, 1288, 1293, 1294, 1304):
            self.assertEqual(fingerprints[f"{prefix}{line}"], 0)


if __name__ == "__main__":
    unittest.main()
