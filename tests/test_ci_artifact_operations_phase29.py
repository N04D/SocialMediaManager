import tempfile
import unittest
from pathlib import Path

from integrations.ci_artifacts.fake_source import fake_github_source
from src.core.certification_evidence.service import CertificationEvidenceService
from src.core.ci_artifacts.service import CiArtifactImportService
from src.providers.ci.github_actions.origins import default_github_origin_payload


class CiArtifactOperationsPhase29Tests(unittest.TestCase):
    def test_uncertainty_reconciliation_retention_and_remote_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "owned.sqlite3"
            commit = "d4eaff40f239e750aab38652176d6581621ae069"
            evidence = CertificationEvidenceService(database_path=db)
            run_id = evidence.staging.deterministic_certification()["run"]["id"]
            package = evidence.create_from_staging_run(run_id, source_type="ci", commit_sha=commit)
            data = evidence.export_evidence(package["evidence"]["package_id"])["data"]
            ci = CiArtifactImportService(database_path=db, source=fake_github_source(data, commit_sha=commit))
            ci.register_origin(default_github_origin_payload())
            request = ci.create_import_request(
                origin_id="github-actions-owned-publication",
                run_id="1001",
                artifact_id="5001",
                expected_commit_sha=commit,
            )["import_request"]
            ci.repository.update_request(request, "downloading")
            reconciled = ci.reconcile(request["id"])
            self.assertEqual(reconciled["finding"], "download_status_uncertain_local_checksum_required")
            self.assertFalse(reconciled["second_download_started"])
            retention = ci.retention_preview()
            self.assertTrue(retention["last_verified_package_protected"])
            self.assertEqual(evidence.remote_ci_status()["artifact_status"], "artifact_not_imported")


if __name__ == "__main__":
    unittest.main()
