from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.phase36_support import Phase36Harness


class Phase36CapabilityResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase36Harness()
        self.addCleanup(self.harness.close)

    def test_render_steps_and_channel_consumers_resolve_by_capability(self) -> None:
        registry = self.harness.runtime.registry
        for capability in [
            "transformation.clip_candidates",
            "transformation.clip_selection",
            "transformation.video_extract",
            "transformation.video_reframe",
            "transformation.caption_render",
        ]:
            self.assertEqual(registry.providers_for(capability)[0].id, "plugin.video_repurpose")
        social_consumers = [
            provider.id for provider in registry.providers_for("transformation.accepts.variant.social_text")
        ]
        self.assertIn("channel.linkedin", social_consumers)
        markdown_manifest = json.loads(
            (Path(__file__).resolve().parents[1] / "channels/markdown_website/plugin.manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(markdown_manifest["id"], "channel.markdown_website")
        self.assertIn("channel.publish.text", markdown_manifest["capabilities"])
