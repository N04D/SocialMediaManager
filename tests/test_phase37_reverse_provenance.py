from __future__ import annotations

import json
import unittest

from tests.phase37_support import Phase37Harness


class Phase37ReverseProvenanceTests(unittest.TestCase):
    def test_short_traces_back_to_transcription_provider_and_video(self) -> None:
        harness = Phase37Harness()
        self.addCleanup(harness.close)
        result = harness.transcribe_and_render()
        short = result["rendered"].captioned_asset
        context = harness.content.graph_service.agent_context(
            workspace_id="creator-video", content_service=harness.content
        )
        payload = json.dumps(context)
        self.assertIn(short.id, payload)
        self.assertIn("provider.transcription.local", payload)
        self.assertIn(harness.video_asset.id, payload)
        self.assertIn(result["transcript"].run_id, payload)
