from __future__ import annotations

import unittest

from dashboard import render_owned_publication_workspace_page


class Phase36CreatorWorkspaceTests(unittest.TestCase):
    def test_workspace_shows_video_creator_flow_without_debug_ids(self) -> None:
        html = render_owned_publication_workspace_page()
        self.assertIn("Video", html)
        self.assertIn("Primary source</strong> Video", html)
        self.assertIn("Suggested clips", html)
        self.assertIn("Use clip", html)
        self.assertIn("Rendered clips", html)
        self.assertIn("Short clip", html)
        self.assertIn("Captions included", html)
        normal_flow = html.split("Suggested clips", maxsplit=1)[1].split("Advanced", maxsplit=1)[0]
        self.assertNotIn("transformation_run_", normal_flow)
