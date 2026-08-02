from __future__ import annotations

import json
import unittest

from plugins.sources.youtube import YouTubeSourceError, YouTubeSourcePlugin
from plugins.sources.youtube.fixtures import SABR_TRANSCRIPT, SABR_VIDEO_ID, SABR_VIDEO_URL
from tests.phase35_support import Phase35TestMixin


class Phase35YouTubeSourcePluginTests(Phase35TestMixin, unittest.TestCase):
    def test_url_validation_and_video_id_resolution(self) -> None:
        plugin = YouTubeSourcePlugin()
        self.assertEqual(plugin.validate_video_ref(url=SABR_VIDEO_URL)["video_id"], SABR_VIDEO_ID)
        self.assertEqual(plugin.validate_video_ref(video_id=SABR_VIDEO_ID)["url"], SABR_VIDEO_URL)
        with self.assertRaises(YouTubeSourceError):
            plugin.validate_video_ref(url="https://example.test/watch?v=sabr1234567")

    def test_transcript_import_timeline_original_edited_and_provenance(self) -> None:
        plugin = self.harness.runtime.get_plugin_service("source.youtube", "source_service")
        result = plugin.import_source(
            content_service=self.harness.content,
            workspace_id="creator-commerce",
            url=SABR_VIDEO_URL,
            title="What is Sabr?",
            transcript=SABR_TRANSCRIPT,
            edited_transcript="Edited canonical transcript",
            channel_name="Synthetic Creator",
            duration=106,
            language="en",
            actor="test",
        )
        item = result["content_item"]
        self.assertEqual(item.primary_source_type, "youtube_video")
        self.assertEqual(item.primary_source_entity_id, result["entity"].id)
        self.assertEqual(item.canonical_text_representation, "Edited canonical transcript")
        self.assertIn("Sabr is often", item.canonical_metadata["transcript_original"])
        self.assertTrue(item.canonical_metadata["transcript_changed"])
        self.assertEqual(item.source_provenance["plugin_id"], "source.youtube")
        self.assertGreaterEqual(len(result["canonical"]["timeline"]), 3)
        self.assertEqual(result["canonical"]["timeline"][0].start_time, 0.0)
        self.assertIn("timeline_segments_json", item.canonical_metadata)
        self.assertIsInstance(json.loads(item.canonical_metadata["timeline_segments_json"]), list)

    def test_source_survives_reload_without_rewriting_user_content(self) -> None:
        plugin = self.harness.runtime.get_plugin_service("source.youtube", "source_service")
        created = plugin.import_source(
            content_service=self.harness.content,
            workspace_id="creator-commerce",
            url=SABR_VIDEO_URL,
            title="What is Sabr?",
            transcript=SABR_TRANSCRIPT,
        )["content_item"]
        reloaded = self.harness.content.get_content(created.id, workspace_id="creator-commerce")
        self.assertEqual(reloaded.primary_source_type, "youtube_video")
        self.assertEqual(reloaded.primary_source_ref, SABR_VIDEO_URL)
        self.assertEqual(reloaded.primary_source_metadata["video_id"], SABR_VIDEO_ID)

    def test_health_reports_no_fake_transcript_retrieval(self) -> None:
        health = YouTubeSourcePlugin().health_check()
        self.assertEqual(health["transcript_retrieval"], "not_configured")
        self.assertIn("Paste transcript", health["fallbacks"])
        self.assertFalse(health["network_required"])
