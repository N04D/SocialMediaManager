from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from integrations.ci_artifacts.operator_scenarios import build_operator_stack
from src.core.ci_artifacts.errors import CiArtifactError


class CiOperatorRecoveryPhase31Tests(unittest.TestCase):
    def test_reconciliation_detects_review_complete_without_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stack = build_operator_stack(Path(tmp))
            operator = stack["operator"]
            flow = operator.create_flow(origin_reference_id=stack["origin"]["id"], expected_commit_sha=stack["commit"])[
                "flow"
            ]
            operator.select_run(flow["id"], run_id=stack["run_id"], run_attempt=1)
            operator.select_artifact(flow["id"], artifact_id=stack["artifact_id"])
            dry = operator.dry_run_import(flow["id"])["dry_run"]
            request_id = operator.execute_import(dry["id"], confirmed_by="alice", signer_id=stack["signer_id"])["flow"][
                "import_request_id"
            ]
            operator.review_import(request_id, reviewer_id="bob", requester_id="alice")
            finding = operator.reconcile_flow(flow["id"])
            self.assertEqual(finding["finding"], "review_complete_promotion_missing")
            self.assertFalse(finding["automatic_promotion"])

    def test_stale_dry_run_blocks_execution_when_artifact_expires_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stack = build_operator_stack(Path(tmp))
            operator = stack["operator"]
            flow = operator.create_flow(origin_reference_id=stack["origin"]["id"], expected_commit_sha=stack["commit"])[
                "flow"
            ]
            operator.select_run(flow["id"], run_id=stack["run_id"], run_attempt=1)
            operator.select_artifact(flow["id"], artifact_id=stack["artifact_id"])
            dry = operator.dry_run_import(flow["id"])["dry_run"]
            key = (stack["origin"]["id"], stack["run_id"], 1)
            artifact = stack["source"]._artifacts[key][0]
            stack["source"]._artifacts[key] = [replace(artifact, expired=True)]
            with self.assertRaises(CiArtifactError):
                operator.execute_import(dry["id"], confirmed_by="alice", signer_id=stack["signer_id"])


if __name__ == "__main__":
    unittest.main()
