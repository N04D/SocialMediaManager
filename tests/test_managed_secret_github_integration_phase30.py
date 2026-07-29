from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.ci_artifacts.fake_source import fake_github_source
from integrations.managed_secrets.fixtures import encrypted_facade
from src.core.ci_artifacts.service import CiArtifactImportService
from src.core.managed_secrets.service import PurposeBoundSecretReader
from src.providers.ci.github_actions.origins import default_github_origin_payload


class ManagedSecretGitHubIntegrationPhase30Test(unittest.TestCase):
    def test_github_read_only_credential_lease_doctor_and_fake_import_without_token_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            facade = encrypted_facade(root / "app.sqlite", root / "vault")
            facade.authz.grant_role("alice", "secret_operator")
            facade.authz.grant_role("bob", "security_approver")
            secret = facade.create_reference(
                secret_type="github_read_only_token",
                display_name="GitHub Actions read credential",
                purpose_allowlist=("github_actions_read",),
                created_by="alice",
            )["secret"]
            token = b"github-token-synthetic-read-only"
            facade.set_value(secret["id"], token, actor="alice")
            facade.validate(secret["id"])
            facade.approve(
                secret["id"],
                action_type="approve_github_credential",
                requester_id="alice",
                approver_id="bob",
            )
            facade.activate(secret["id"], action_type="approve_github_credential")

            commit = "bc228b2da464f75fe8f53e052a783f7b6df7ce64"
            package = _ci_package(root / "app.sqlite", commit)
            reader = PurposeBoundSecretReader(facade, purpose="github_actions_read", consumer="github_actions")
            source = fake_github_source(package, commit_sha=commit, secret_reader=reader)
            ci_service = CiArtifactImportService(database_path=root / "app.sqlite", source=source)
            origin = default_github_origin_payload()
            origin["credential_secret_reference"] = secret["id"]
            source.origins[origin["id"]]["credential_secret_reference"] = secret["id"]
            ci_service.register_origin(origin)
            doctor = ci_service.origin_doctor(origin["id"])
            self.assertEqual(doctor["checks"]["authentication"], "PASS")
            created = ci_service.create_import_request(
                origin_id=origin["id"],
                run_id="1001",
                artifact_id="5001",
                expected_commit_sha=commit,
            )
            result = ci_service.process_import(created["import_request"]["id"])
            self.assertEqual(result["artifact_status"], "artifact_imported_verified")
            dumped_db = (root / "app.sqlite").read_bytes()
            self.assertNotIn(token, dumped_db)
            self.assertNotIn("github-token-synthetic", str(result))
            self.assertEqual(
                ci_service.readiness(current_commit=commit)["remote_ci_status"], "artifact_imported_verified"
            )


def _ci_package(database_path: Path, commit: str) -> bytes:
    from src.core.certification_evidence.service import CertificationEvidenceService

    service = CertificationEvidenceService(database_path=database_path)
    run = service.staging.deterministic_certification()["run"]["id"]
    evidence = service.create_from_staging_run(run, source_type="ci", commit_sha=commit)["evidence"]
    return service.export_evidence(evidence["package_id"])["data"]


if __name__ == "__main__":
    unittest.main()
