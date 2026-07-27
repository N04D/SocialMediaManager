from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication.operations import CertificationGate, ProductionReadinessService, StorageBackupService
from src.core.owned_publication.service import OwnedPublicationWorkspaceService


class OwnedPublicationReadinessPhase24Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = OwnedPublicationWorkspaceService(database_path=Path(self.tmp.name) / "owned.sqlite3")
        self.backups = StorageBackupService(self.service.repository, Path(self.tmp.name) / "ops")
        self.backups.create_backup()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_all_owned_operations_green_while_sandbox_remains_separate_false(self) -> None:
        gate = CertificationGate(commit_sha="test")
        browser = gate.evidence_from_result(certification_type="browser_certification", browser_version="chromium")
        worker = gate.evidence_from_result(certification_type="worker_certification")
        report = ProductionReadinessService(self.service.repository, backup_service=self.backups).report(
            browser_evidence=browser,
            worker_evidence=worker,
        )
        self.assertTrue(report.owned_publication_operations_ready)
        self.assertFalse(report.external_plugin_sandbox_ready)
        self.assertFalse(report.sandbox_phase20_2_status["production_ready"])
        self.assertTrue(report.production_ready)

    def test_missing_certification_or_required_skip_blocks_readiness(self) -> None:
        gate = CertificationGate(commit_sha="test")
        browser = gate.evidence_from_result(
            certification_type="browser_certification",
            required_skips=1,
            passed=True,
        )
        report = ProductionReadinessService(self.service.repository, backup_service=self.backups).report(
            browser_evidence=browser,
            worker_evidence=None,
        )
        self.assertFalse(report.owned_publication_operations_ready)
        self.assertGreater(report.required_certification_skips, 0)

    def test_release_check_cli_json_uses_managed_database_and_no_raw_database_path_argument(self) -> None:
        env = os.environ.copy()
        env["HOME"] = self.tmp.name
        completed = subprocess.run(
            [sys.executable, "-m", "src.plugin_sdk.cli", "owned-publication", "release-check", "--json"],
            cwd=Path.cwd(),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("owned_publication_operations_ready", completed.stdout)
        self.assertNotIn("--database", completed.stdout)


if __name__ == "__main__":
    unittest.main()
