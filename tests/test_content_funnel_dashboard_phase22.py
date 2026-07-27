from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication import OwnedPublicationWorkspaceService


class ContentFunnelDashboardPhase22Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = OwnedPublicationWorkspaceService(database_path=Path(self.tmp.name) / "funnel.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_funnel_steps_rates_quality_and_no_causality_claim(self) -> None:
        funnel = self.service.funnel("content-owned-1")
        steps = funnel["steps"]
        self.assertEqual(steps[0]["name"], "Social impressions")
        self.assertEqual(steps[-1]["name"], "Conversions")
        self.assertEqual(steps[-1]["rate_from_first"], 0.002)
        self.assertEqual(funnel["quality"], "complete")
        self.assertFalse(funnel["causality_claimed"])

    def test_channel_and_revision_comparison(self) -> None:
        channels = self.service.channel_comparison("content-owned-1")
        self.assertFalse(channels["causality_claimed"])
        self.assertEqual(channels["channels"][0]["channel"], "linkedin")
        self.assertGreater(channels["channels"][0]["engaged_visits"], channels["channels"][1]["engaged_visits"])
        revisions = self.service.revision_comparison("content-owned-1")
        self.assertIn("time effects", revisions["time_period_warning"])
        self.assertIn("linkedin", revisions["channel_variant_differences"])

    def test_content_aware_insights_are_evidence_bound(self) -> None:
        insights = self.service.insights("content-owned-1")
        insight = insights["insights"][0]
        self.assertEqual(insight["content_revision_id"], "revision-owned-1")
        self.assertIn("publication-website-1", insight["evidence_links"])
        self.assertIn("not causal proof", insight["limitations"][0])


if __name__ == "__main__":
    unittest.main()
