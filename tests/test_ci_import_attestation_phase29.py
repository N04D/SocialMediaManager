import tempfile
import unittest
from pathlib import Path

from integrations.ci_artifacts.fake_source import fake_github_source
from src.core.certification_evidence.service import CertificationEvidenceService
from src.core.ci_artifacts.service import CiArtifactImportService
from src.providers.ci.github_actions.origins import default_github_origin_payload


class CiImportAttestationPhase29Tests(unittest.TestCase):
    def test_unsigned_attestation_is_not_overclaimed(self) -> None:
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
            result = ci.process_import(request["id"])
            self.assertEqual(result["attestation"]["signature_envelope"]["signature_status"], "not_configured")
            self.assertEqual(result["attestation"]["trust_status"], "verified_ci_artifact")
            self.assertNotIn("SLSA", str(result))


if __name__ == "__main__":
    unittest.main()
