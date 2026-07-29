from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.ci_artifacts.operator_scenarios import build_operator_stack, complete_promoted_flow
from src.core.ci_artifacts.errors import CiArtifactError


class CiOperatorReadinessPhase31Tests(unittest.TestCase):
    def test_readiness_requires_review_promotion_fresh_trusted_exact_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stack = build_operator_stack(Path(tmp))
            operator = stack["operator"]
            self.assertEqual(
                operator.readiness(current_commit=stack["commit"])["remote_ci_status"], "artifact_not_imported"
            )
            promoted = complete_promoted_flow(stack)
            readiness = operator.readiness(current_commit=stack["commit"])
            self.assertTrue(readiness["ci_certification_ready"])
            self.assertEqual(readiness["remote_ci_status"], "artifact_imported_verified")
            stack["signer_service"].revoke(stack["signer_id"], reason="key_compromise")
            degraded = operator.readiness(current_commit=promoted["promotion"]["target_commit_sha"])
            self.assertFalse(degraded["ci_certification_ready"])

    def test_wrong_commit_and_digest_mismatch_block_import_and_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stack = build_operator_stack(Path(tmp))
            operator = stack["operator"]
            flow = operator.create_flow(origin_reference_id=stack["origin"]["id"], expected_commit_sha=stack["commit"])[
                "flow"
            ]
            with self.assertRaises(CiArtifactError):
                operator.discover_runs(stack["origin"]["id"], commit_sha="0000000000000000000000000000000000000000")

            operator.select_run(flow["id"], run_id=stack["run_id"], run_attempt=1)
            operator.select_artifact(flow["id"], artifact_id=stack["artifact_id"])
            dry = operator.dry_run_import(flow["id"])["dry_run"]
            key = (stack["origin"]["id"], stack["run_id"], 1)
            artifact = stack["source"]._artifacts[key][0]
            from dataclasses import replace

            stack["source"]._artifacts[key] = [replace(artifact, provider_digest="sha256:bad")]
            with self.assertRaises(CiArtifactError):
                operator.execute_import(dry["id"], confirmed_by="alice", signer_id=stack["signer_id"])
            self.assertFalse(operator.readiness(current_commit=stack["commit"])["ci_certification_ready"])


if __name__ == "__main__":
    unittest.main()
