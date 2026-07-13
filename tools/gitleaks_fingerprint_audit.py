from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable


def expected_fingerprint_counts(lines: Iterable[str]) -> Counter[str]:
    return Counter(
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    )


def finding_fingerprint_counts(findings: object) -> Counter[str]:
    if not isinstance(findings, list):
        raise ValueError("gitleaks findings must be a JSON list")
    fingerprints: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("each gitleaks finding must be a JSON object")
        fingerprint = finding.get("Fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("each gitleaks finding must have a Fingerprint")
        fingerprints.append(fingerprint)
    return Counter(fingerprints)


def audit_fingerprint_files(findings_path: Path, expected_path: Path) -> bool:
    findings = json.loads(findings_path.read_text(encoding="utf-8"))
    actual = finding_fingerprint_counts(findings)
    expected = expected_fingerprint_counts(
        expected_path.read_text(encoding="utf-8").splitlines()
    )
    return actual == expected


def main(arguments: list[str]) -> int:
    if len(arguments) != 2:
        raise SystemExit(
            "usage: gitleaks_fingerprint_audit.py FINDINGS_JSON EXPECTED_IGNORE"
        )
    if not audit_fingerprint_files(Path(arguments[0]), Path(arguments[1])):
        raise SystemExit("gitleaks fingerprint audit mismatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
