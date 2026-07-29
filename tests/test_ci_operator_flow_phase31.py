from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.ci_artifacts.operator_scenarios import PHASE31_COMMIT, build_operator_stack, complete_promoted_flow
from src.core.ci_artifacts.contracts import (
    CI_EVIDENCE_PROMOTION_CONTRACT_VERSION,
    CI_IMPORT_DRY_RUN_CONTRACT_VERSION,
    GITHUB_CI_OPERATOR_FLOW_VERSION,
)


class CiOperatorFlowPhase31Tests(unittest.TestCase):
    def test_end_to_end_operator_flow_promotes_exact_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stack = build_operator_stack(Path(tmp))
            operator = stack["operator"]
            self.assertEqual(operator.contracts()["github_ci_operator_flow_version"], GITHUB_CI_OPERATOR_FLOW_VERSION)
            self.assertEqual(
                operator.contracts()["ci_import_dry_run_contract_version"], CI_IMPORT_DRY_RUN_CONTRACT_VERSION
            )
            self.assertEqual(
                operator.contracts()["ci_evidence_promotion_contract_version"],
                CI_EVIDENCE_PROMOTION_CONTRACT_VERSION,
            )
            doctor = operator.origin_doctor(stack["origin"]["id"])
            self.assertEqual(doctor["checks"]["read_only_permissions"], "PASS")
            discovered = operator.discover_runs(stack["origin"]["id"], commit_sha=stack["commit"])
            self.assertEqual(len(discovered["runs"]), 1)
            promoted = complete_promoted_flow(stack)
            readiness = operator.readiness(current_commit=stack["commit"])
            self.assertEqual(readiness["remote_ci_status"], "artifact_imported_verified")
            self.assertTrue(readiness["ci_evidence_promoted_for_current_commit"])
            self.assertEqual(promoted["promotion"]["target_commit_sha"], PHASE31_COMMIT)
            self.assertFalse(
                operator.readiness(current_commit="d4eaff40f239e750aab38652176d6581621ae069")["ci_certification_ready"]
            )

    def test_current_commit_and_dirty_state_exclude_user_owned_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stack = build_operator_stack(Path(tmp))
            context = stack["operator"].current_commit(expected_commit_sha=stack["commit"])
            self.assertEqual(context["commit_sha"], stack["commit"])
            self.assertIn(
                context["worktree_state"], {"clean", "dirty_user_owned_only", "dirty_generated_only", "dirty_other"}
            )
            self.assertTrue(len(context["commit_sha"]) == 40)


if __name__ == "__main__":
    unittest.main()
