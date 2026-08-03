from __future__ import annotations

import unittest

from tests.phase36_support import Phase36Harness


class Phase36TransformChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase36Harness()
        self.addCleanup(self.harness.close)

    def test_graph_chain_and_reverse_provenance(self) -> None:
        rendered = self.harness.render_candidate()["result"]
        context = self.harness.content.graph_service.agent_context(
            workspace_id="creator-video", content_service=self.harness.content
        )
        relationships = context["relationships"]
        self.assertTrue(any(rel["relationship_type"] == "selected_as" for rel in relationships))
        self.assertTrue(any(rel["to_entity_id"] == rendered.captioned_asset.id for rel in relationships))
        self.assertEqual(
            rendered.captioned_asset.metadata["original_timestamps"]["start"], rendered.selected_candidate.start_time
        )
        self.assertEqual(rendered.captioned_asset.metadata["extract_run_id"], rendered.extract_run_id)
        self.assertEqual(rendered.captioned_asset.metadata["reframe_run_id"], rendered.reframe_run_id)
        self.assertEqual(rendered.captioned_asset.metadata["caption_run_id"], rendered.caption_run_id)
