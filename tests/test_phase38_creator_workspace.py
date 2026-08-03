from __future__ import annotations

import unittest

from dashboard import render_owned_publication_workspace_page, render_plugins_page
from plugin_runtime import get_plugin_runtime
from tests.phase38_support import Phase38Harness


class Phase38CreatorWorkspaceTests(unittest.TestCase):
    def test_workspace_shows_human_reasons_not_graph_ids(self) -> None:
        html = render_owned_publication_workspace_page()
        self.assertIn("Recommended", html)
        self.assertIn("Why this clip?", html)
        self.assertIn("Strong hook", html)
        self.assertIn("Complete thought", html)
        normal_flow = html.split("Suggested clips", maxsplit=1)[1].split("Advanced provenance", maxsplit=1)[0]
        self.assertNotIn("TransformationRun", normal_flow)
        self.assertNotIn("ProviderManifest", normal_flow)

    def test_plugins_ui_groups_clip_intelligence_under_video_repurpose(self) -> None:
        harness = Phase38Harness()
        self.addCleanup(harness.close)
        get_plugin_runtime(harness.config, reset=True, strict=False)
        html = render_plugins_page()
        self.assertIn("Video Repurpose", html)
        self.assertIn("Clip intelligence", html)
        self.assertIn("Semantic analysis", html)
        self.assertIn("Speaker boundaries unavailable", html)
