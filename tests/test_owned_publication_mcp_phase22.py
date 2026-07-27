from __future__ import annotations

import unittest

from src.core.owned_publication import OwnedPublicationMCP, OwnedPublicationWorkspaceService


class OwnedPublicationMCPPhase22Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = OwnedPublicationWorkspaceService()
        self.mcp = OwnedPublicationMCP(self.service)

    def test_mcp_article_plan_dependencies_timeline_and_evidence(self) -> None:
        article = self.mcp.get_article_with_channel_variants("content-owned-1")
        self.assertTrue(article["read_only"])
        self.assertEqual(article["exact_binding"]["content_revision_id"], "revision-owned-1")
        self.assertIn("linkedin", article["variants"])
        plan = self.mcp.get_publication_plan("plan-owned-1")
        self.assertEqual(plan["plan"]["id"], "plan-owned-1")
        dependencies = self.mcp.get_publication_dependencies("plan-owned-1")
        self.assertIn("target-linkedin", str(dependencies["dependencies"]))
        timeline = self.mcp.get_publication_execution_timeline("publication-website-1")
        self.assertIn("timeline", timeline)
        evidence = self.mcp.get_publication_evidence("publication-website-1")
        self.assertIn("verification_markers", evidence["evidence"][0])

    def test_mcp_funnel_channel_revision_cta_quality(self) -> None:
        funnel = self.mcp.get_content_funnel("content-owned-1")
        self.assertEqual(funnel["funnel"]["model"]["content_revision_id"], "revision-owned-1")
        channels = self.mcp.compare_channel_performance("content-owned-1")
        self.assertEqual(channels["channels"][0]["attribution_quality"], "complete")
        revisions = self.mcp.compare_content_revisions("content-owned-1")
        self.assertTrue(revisions["title_changed"])
        dropoffs = self.mcp.get_funnel_dropoffs("content-owned-1")
        self.assertGreater(dropoffs["dropoffs"][0]["dropoff"], 0)
        cta = self.mcp.get_cta_performance("content-owned-1")
        self.assertEqual(cta["conversions"], 2)
        quality = self.mcp.get_attribution_quality("content-owned-1")
        self.assertEqual(quality["quality"], "complete")

    def test_mcp_reconciliation_queue_is_read_only(self) -> None:
        queue = self.mcp.get_reconciliation_queue()
        self.assertTrue(queue["read_only"])
        self.assertFalse(queue["unsafe_repairs_attempted"])


if __name__ == "__main__":
    unittest.main()
