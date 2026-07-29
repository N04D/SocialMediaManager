from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.ci_artifacts.operator_scenarios import build_operator_stack, complete_promoted_flow


class CiOperatorSecurityPhase31Tests(unittest.TestCase):
    def test_no_secret_url_force_or_write_boundary_in_operator_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stack = build_operator_stack(Path(tmp))
            complete_promoted_flow(stack)
            repository = stack["operator"].repository
            serialized = str(
                {
                    "flows": repository.list_operator_flows(),
                    "dry_runs": repository.dry_runs(),
                    "promotions": repository.promotions(),
                    "audit": repository.operator_audit_events(),
                    "attestations": repository.attestations(),
                }
            )
            self.assertNotIn("github-token-synthetic", serialized)
            self.assertNotIn("Authorization", serialized)
            self.assertNotIn("archive_download_url", serialized)
            self.assertNotIn("temporary URL", serialized)
            self.assertNotIn("--force", serialized)
            self.assertNotIn("--skip-verification", serialized)
            self.assertIn("'artifact_id': '5001'", serialized)
            self.assertIn("'run_attempt': 1", serialized)
            self.assertEqual(stack["source"].write_operations, [])

    def test_no_artifact_name_only_identity_or_false_remote_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stack = build_operator_stack(Path(tmp))
            flow = stack["operator"].create_flow(
                origin_reference_id=stack["origin"]["id"], expected_commit_sha=stack["commit"]
            )["flow"]
            stack["operator"].select_run(flow["id"], run_id=stack["run_id"], run_attempt=1)
            artifacts = stack["operator"].list_artifacts(flow["id"])["artifacts"]
            self.assertEqual(artifacts[0]["artifact_name"], "owned-publication-certification-evidence")
            self.assertEqual(
                stack["operator"].readiness(current_commit=stack["commit"])["remote_ci_status"], "artifact_not_imported"
            )
            self.assertTrue(stack["operator"].list_artifacts(flow["id"])["artifact_identity_uses_id"])


if __name__ == "__main__":
    unittest.main()
