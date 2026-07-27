from __future__ import annotations

import unittest

from src.core.publication_dependencies import (
    PublicationDependencyError,
    PublicationDependencyGraph,
    PublicationTargetDependency,
)


class PublicationDependencyPhase21Tests(unittest.TestCase):
    def test_website_verified_unlocks_social_targets(self) -> None:
        graph = PublicationDependencyGraph()
        graph.add(
            PublicationTargetDependency(
                "dep-linkedin",
                "plan-1",
                "target-website",
                "target-linkedin",
                "publication_verified",
                workspace_id="workspace-1",
            )
        )
        graph.add(
            PublicationTargetDependency(
                "dep-mastodon",
                "plan-1",
                "target-website",
                "target-mastodon",
                "publication_verified",
                workspace_id="workspace-1",
            )
        )
        self.assertFalse(graph.claimable("target-linkedin", {"target-website": "remote_acknowledged"}))
        self.assertTrue(graph.claimable("target-linkedin", {"target-website": "publication_verified"}))
        self.assertTrue(graph.claimable("target-mastodon", {"target-website": "publication_verified"}))

    def test_failure_uncertain_and_timeout_do_not_bypass_dependency(self) -> None:
        graph = PublicationDependencyGraph()
        graph.add(PublicationTargetDependency("dep", "plan", "website", "social", "publication_verified"))
        self.assertFalse(graph.claimable("social", {"website": "failed"}))
        self.assertFalse(graph.claimable("social", {"website": "mutation_uncertain"}))
        self.assertFalse(graph.claimable("social", {"website": "deployment_pending"}))

    def test_cycle_self_dependency_and_cross_workspace_are_blocked_by_policy(self) -> None:
        graph = PublicationDependencyGraph()
        with self.assertRaises(PublicationDependencyError):
            graph.add(PublicationTargetDependency("self", "plan", "a", "a", "publication_verified"))
        graph.add(PublicationTargetDependency("one", "plan", "a", "b", "publication_verified"))
        with self.assertRaises(PublicationDependencyError):
            graph.add(PublicationTargetDependency("two", "plan", "b", "a", "publication_verified"))


if __name__ == "__main__":
    unittest.main()
