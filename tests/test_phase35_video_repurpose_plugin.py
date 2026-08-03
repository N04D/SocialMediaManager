from __future__ import annotations

import unittest

from plugins.sources.youtube import YouTubeSourcePlugin
from plugins.sources.youtube.fixtures import SABR_TRANSCRIPT
from plugins.transformations.video_repurpose import VideoRepurposePlugin


class Phase35VideoRepurposePluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timeline = YouTubeSourcePlugin().parse_timestamped_transcript(SABR_TRANSCRIPT)
        self.plugin = VideoRepurposePlugin()

    def test_accepts_capabilities_and_generates_ranked_candidates(self) -> None:
        self.assertIn("transformation.accepts.timeline.transcript", self.plugin.capabilities)
        candidates = self.plugin.clip_candidates(self.timeline, max_candidates=3)
        self.assertEqual(len(candidates), 3)
        self.assertGreaterEqual(candidates[0].score, candidates[1].score)
        self.assertGreater(candidates[0].duration, 0)
        self.assertIn("plugin_id", candidates[0].provenance)
        self.assertIn(candidates[0].topic, {"sabr", "patience", "reflection", "daily life", "endurance"})

    def test_timing_variants_and_short_video_asset_contract_are_generic(self) -> None:
        selected = self.plugin.clip_candidates(self.timeline, max_candidates=1)[0]
        short_video = self.plugin.short_video_asset_contract(selected=selected, source_asset_id="asset.video.synthetic")
        social = self.plugin.social_text_variant(selected=selected, title="What is Sabr?")
        article = self.plugin.article_variant(selected=selected, title="What is Sabr?")
        self.assertEqual(short_video["asset_type"], "short_video")
        self.assertEqual(short_video["status"], "rendering capability not configured")
        self.assertEqual(short_video["start"], selected.start_time)
        self.assertEqual(social.asset_type, "variant.social_text")
        self.assertEqual(article.asset_type, "variant.article")
        self.assertNotIn("LinkedIn", social.text)
        self.assertNotIn("Instagram", social.text)

    def test_contract_has_no_external_execution_boundary(self) -> None:
        health = self.plugin.health_check()
        self.assertFalse(health["network_required"])
        self.assertEqual(health["shell"], "not_used")
        self.assertEqual(health["short_video_rendering"], "available_with_local_ffmpeg")
