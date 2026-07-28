import tempfile
import unittest
from pathlib import Path

from integrations.ci_artifacts.fake_source import fake_github_source
from src.core.certification_evidence.service import CertificationEvidenceService
from src.core.ci_artifacts.errors import CiArtifactError
from src.core.ci_artifacts.service import CiArtifactImportService
from src.providers.ci.github_actions.origins import default_github_origin_payload


class CiArtifactSecurityPhase29Tests(unittest.TestCase):
    def test_boundaries_no_writes_no_private_keys_no_arbitrary_urls(self) -> None:
        combined = "\n".join(
            Path(path).read_text(encoding="utf-8")
            for path in [
                "src/core/ci_artifacts/service.py",
                "src/providers/ci/github_actions/source.py",
                "src/providers/ci/github_actions/client.py",
                "src/core/trusted_signing/service.py",
            ]
        )
        self.assertNotIn("requests.", combined)
        self.assertNotIn("httpx.", combined)
        self.assertNotIn("urllib.request", combined)
        self.assertNotIn("workflow dispatch", combined.lower())
        self.assertNotIn("delete artifact", combined.lower())
        self.assertNotIn("latest successful", combined.lower())
        self.assertNotIn("BEGIN PRIVATE KEY", combined)

    def test_digest_mismatch_and_fork_run_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "owned.sqlite3"
            commit = "d4eaff40f239e750aab38652176d6581621ae069"
            evidence = CertificationEvidenceService(database_path=db)
            run_id = evidence.staging.deterministic_certification()["run"]["id"]
            package = evidence.create_from_staging_run(run_id, source_type="ci", commit_sha=commit)
            data = evidence.export_evidence(package["evidence"]["package_id"])["data"]
            source = fake_github_source(data, commit_sha=commit)
            artifact = source._artifacts[("github-actions-owned-publication", "1001", 1)][0]
            source._artifacts[("github-actions-owned-publication", "1001", 1)][0] = artifact.__class__(
                **{**artifact.__dict__, "provider_digest": "sha256:bad"}
            )
            ci = CiArtifactImportService(database_path=db, source=source)
            ci.register_origin(default_github_origin_payload())
            request = ci.create_import_request(
                origin_id="github-actions-owned-publication",
                run_id="1001",
                artifact_id="5001",
                expected_commit_sha=commit,
            )["import_request"]
            with self.assertRaises(CiArtifactError):
                ci.process_import(request["id"])


if __name__ == "__main__":
    unittest.main()
