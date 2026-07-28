import tempfile
import unittest
from pathlib import Path

from integrations.ci_artifacts.fake_source import fake_github_source, source_with_duplicate_artifact_name
from src.core.certification_evidence.service import CertificationEvidenceService
from src.core.ci_artifacts.contracts import CI_ARTIFACT_SOURCE_CONTRACT_VERSION, GITHUB_ACTIONS_ARTIFACT_SOURCE_VERSION
from src.core.ci_artifacts.errors import CiArtifactError
from src.core.ci_artifacts.service import CiArtifactImportService
from src.providers.ci.github_actions.manifest import MANIFEST
from src.providers.ci.github_actions.origins import default_github_origin_payload


class CiArtifactSourcePhase29Tests(unittest.TestCase):
    def package(self, tmp: str, commit: str) -> bytes:
        service = CertificationEvidenceService(database_path=Path(tmp) / "owned.sqlite3")
        run_id = service.staging.deterministic_certification()["run"]["id"]
        evidence = service.create_from_staging_run(run_id, source_type="ci", commit_sha=commit)
        return service.export_evidence(evidence["evidence"]["package_id"])["data"]

    def test_github_actions_identity_read_only_origin_run_and_artifact_validation(self) -> None:
        self.assertEqual(CI_ARTIFACT_SOURCE_CONTRACT_VERSION, "1.0")
        self.assertEqual(GITHUB_ACTIONS_ARTIFACT_SOURCE_VERSION, "0.1.0")
        self.assertEqual(MANIFEST["provider_id"], "ci.github_actions")
        self.assertEqual(MANIFEST["data_access"], "read_only")
        with tempfile.TemporaryDirectory() as tmp:
            commit = "d4eaff40f239e750aab38652176d6581621ae069"
            source = fake_github_source(self.package(tmp, commit), commit_sha=commit)
            service = CiArtifactImportService(database_path=Path(tmp) / "ci.sqlite3", source=source)
            service.register_origin(default_github_origin_payload())
            runs = service.list_runs("github-actions-owned-publication", commit_sha=commit)["runs"]
            self.assertEqual(runs[0]["run_id"], "1001")
            artifacts = service.artifacts("github-actions-owned-publication", "1001")["artifacts"]
            self.assertEqual(artifacts[0]["artifact_id"], "5001")
            self.assertEqual(source.write_operations, [])

    def test_wrong_commit_and_duplicate_artifact_name_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            commit = "d4eaff40f239e750aab38652176d6581621ae069"
            package = self.package(tmp, commit)
            source = fake_github_source(package, commit_sha=commit)
            service = CiArtifactImportService(database_path=Path(tmp) / "ci.sqlite3", source=source)
            service.register_origin(default_github_origin_payload())
            with self.assertRaises(CiArtifactError):
                service.dry_run_import(
                    "github-actions-owned-publication",
                    "1001",
                    "5001",
                    expected_commit_sha="0000000000000000000000000000000000000000",
                )
            duplicate = CiArtifactImportService(
                database_path=Path(tmp) / "ci2.sqlite3",
                source=source_with_duplicate_artifact_name(package, commit_sha=commit),
            )
            duplicate.register_origin(default_github_origin_payload())
            with self.assertRaises(CiArtifactError):
                duplicate.dry_run_import("github-actions-owned-publication", "1001", "5001", expected_commit_sha=commit)


if __name__ == "__main__":
    unittest.main()
