from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.ci_artifacts.operator_scenarios import build_operator_stack
from src.core.ci_artifacts.errors import CiArtifactError


class CiOperatorReviewPhase31Tests(unittest.TestCase):
    def test_two_operator_review_and_checksum_bound_promotion(self) -> None:
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
            with self.assertRaises(CiArtifactError):
                operator.review_import(request_id, reviewer_id="alice", requester_id="alice")
            reviewed = operator.review_import(request_id, reviewer_id="bob", requester_id="alice")
            self.assertEqual(reviewed["review"]["decision"], "approved")
            promoted = operator.promote_import(request_id, promoted_by="alice")
            self.assertEqual(promoted["promotion"]["review_id"], reviewed["review_id"])

    def test_invalid_or_wrong_commit_cannot_be_promoted_by_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stack = build_operator_stack(Path(tmp))
            operator = stack["operator"]
            flow = operator.create_flow(origin_reference_id=stack["origin"]["id"], expected_commit_sha=stack["commit"])[
                "flow"
            ]
            with self.assertRaises(CiArtifactError):
                operator.select_run(flow["id"], run_id=stack["run_id"], run_attempt=99)


if __name__ == "__main__":
    unittest.main()
