#!/usr/bin/env python3
"""Run required owned-publication browser/worker certification suites."""

from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Owned Publication Browser and Worker Certification")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    from src.core.owned_publication.operations import CERTIFICATION_SUITES, CertificationGate

    args = parse_args()
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in CERTIFICATION_SUITES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    gate = CertificationGate(commit_sha=_git_commit())
    skips = len(result.skipped)
    report = {
        "browser_certification_passed": result.wasSuccessful() and skips == 0,
        "worker_certification_passed": result.wasSuccessful() and skips == 0,
        "required_browser_tests_skipped": skips,
        "required_worker_tests_skipped": skips,
        "required_skips": skips,
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "evidence": {
            "browser": gate.evidence_from_result(
                certification_type="browser_certification",
                required_skips=skips,
                passed=result.wasSuccessful(),
            ).__dict__,
            "worker": gate.evidence_from_result(
                certification_type="worker_certification",
                required_skips=skips,
                passed=result.wasSuccessful(),
            ).__dict__,
        },
        "safe_artifacts": ["test-result-report"],
    }
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(encoded + "\n", encoding="utf-8")
    if args.json:
        print(encoded)
    return 0 if result.wasSuccessful() and skips == 0 else 1


def _git_commit() -> str:
    import subprocess

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return "unknown"
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
