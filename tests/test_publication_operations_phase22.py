from __future__ import annotations

import unittest

from src.core.owned_publication import OwnedPublicationWorkspaceService
from src.core.owned_publication.errors import OwnedPublicationError
from src.core.publication_dependencies import (
    PublicationDependencyError,
    PublicationDependencyGraph,
    PublicationTargetDependency,
)


class PublicationOperationsPhase22Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = OwnedPublicationWorkspaceService()

    def test_plan_builder_dependencies_and_scheduling(self) -> None:
        plan = self.service.plan_payload("plan-owned-1")
        self.assertEqual(plan["plan"]["targets"][0]["channel"], "channel.markdown_website")
        self.assertTrue(plan["dependencies"]["claimable"]["target-linkedin"])
        scheduled = self.service.schedule_plan("plan-owned-1", {"expected_version": 2})
        self.assertTrue(scheduled["dependencies_respected"])
        self.assertFalse(scheduled["duplicate_occurrence"])
        with self.assertRaises(OwnedPublicationError):
            self.service.schedule_plan("plan-owned-1", {"expected_version": 1})

    def test_dependency_graph_blocks_cycle_self_failure_and_uncertain(self) -> None:
        graph = PublicationDependencyGraph()
        dependency = PublicationTargetDependency("dep", "plan", "website", "linkedin", "publication_verified")
        graph.add(dependency)
        self.assertFalse(graph.claimable("linkedin", {"website": "remote_acknowledged"}))
        self.assertFalse(graph.claimable("linkedin", {"website": "failed"}))
        self.assertFalse(graph.claimable("linkedin", {"website": "uncertain"}))
        self.assertTrue(graph.claimable("linkedin", {"website": "publication_verified"}))
        with self.assertRaises(PublicationDependencyError):
            graph.add(PublicationTargetDependency("self", "plan", "website", "website", "publication_verified"))
        with self.assertRaises(PublicationDependencyError):
            graph.add(PublicationTargetDependency("cycle", "plan", "linkedin", "website", "publication_verified"))

    def test_timeline_evidence_and_reconciliation_are_safe(self) -> None:
        timeline = self.service.timeline("publication-website-1")
        phases = {item["phase"] for item in timeline["timeline"]}
        self.assertIn("Markdown rendered", phases)
        self.assertIn("Public URL verified", phases)
        evidence = self.service.evidence("publication-website-1")
        self.assertNotIn("/", evidence["evidence"][0]["publication_commit"])
        self.assertEqual(evidence["evidence"][0]["verification_status"], "publication_verified")
        queue = self.service.reconciliation()
        self.assertFalse(queue["blind_retry"])
        checked = self.service.reconciliation_check("rec-deployment-pending")
        self.assertTrue(checked["read_only"])
        repair = self.service.reconciliation_repair("rec-deployment-pending")
        self.assertFalse(repair["blind_retry"])


if __name__ == "__main__":
    unittest.main()
