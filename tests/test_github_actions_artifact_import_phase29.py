import tempfile
import unittest
from pathlib import Path

from integrations.ci_artifacts.fake_source import fake_github_source
from integrations.trusted_signing.fixtures import signer_secret_fixture
from src.core.certification_evidence.service import CertificationEvidenceService
from src.core.ci_artifacts.service import CiArtifactImportService
from src.core.ci_artifacts.worker import CiArtifactImportWorker
from src.core.trusted_signing.service import TrustedSignerService
from src.providers.ci.github_actions.origins import default_github_origin_payload


class GitHubActionsArtifactImportPhase29Tests(unittest.TestCase):
    def test_end_to_end_import_attestation_review_and_commit_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "owned.sqlite3"
            commit = "d4eaff40f239e750aab38652176d6581621ae069"
            evidence = CertificationEvidenceService(database_path=db)
            run_id = evidence.staging.deterministic_certification()["run"]["id"]
            package_record = evidence.create_from_staging_run(run_id, source_type="ci", commit_sha=commit)
            package_bytes = evidence.export_evidence(package_record["evidence"]["package_id"])["data"]

            store, secret_ref = signer_secret_fixture("secretref:signer/import")
            signer = TrustedSignerService(database_path=db, secret_reader=store)
            signer.enroll(
                signer_id="import-signer", display_name="Import signer", private_key_secret_reference=secret_ref
            )
            signer.approve("import-signer", reviewer_id="operator-b", requester_id="operator-a")
            signer.activate("import-signer")

            ci = CiArtifactImportService(
                database_path=db,
                source=fake_github_source(package_bytes, commit_sha=commit),
                signer_service=signer,
            )
            ci.register_origin(default_github_origin_payload())
            dry = ci.dry_run_import("github-actions-owned-publication", "1001", "5001", expected_commit_sha=commit)
            self.assertFalse(dry["downloads_artifact"])
            request = ci.create_import_request(
                origin_id="github-actions-owned-publication",
                run_id="1001",
                artifact_id="5001",
                expected_commit_sha=commit,
            )["import_request"]
            result = CiArtifactImportWorker(ci).run_once(signer_id="import-signer")["result"]
            self.assertEqual(result["artifact_status"], "artifact_imported_verified")
            self.assertEqual(result["attestation"]["signature_envelope"]["signature_status"], "signed")
            reviewed = ci.review_import(request["id"], decision="approved")
            self.assertEqual(reviewed["import_request"]["status"], "accepted")
            self.assertTrue(ci.readiness(current_commit=commit)["ci_certification_ready"])
            self.assertFalse(
                ci.readiness(current_commit="1111111111111111111111111111111111111111")["ci_certification_ready"]
            )


if __name__ == "__main__":
    unittest.main()
