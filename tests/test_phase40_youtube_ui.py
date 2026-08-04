import unittest

from dashboard import render_owned_publication_workspace_page, render_plugins_page
from plugin_runtime import get_plugin_runtime
from tests.phase35_support import Phase35Harness


class YouTubeUiTests(unittest.TestCase):
    def test_channel_card_is_user_facing_and_secret_safe(self):
        harness = Phase35Harness()
        self.addCleanup(harness.close)
        get_plugin_runtime(harness.config, reset=True, strict=False)
        page = render_plugins_page()
        self.assertIn("YouTube Channel", page)
        self.assertIn("Default privacy: Private", page)
        self.assertIn("Notify subscribers: No", page)
        self.assertNotIn("access_token", page)

    def test_publish_review_shows_exact_user_facing_fields(self):
        page = render_owned_publication_workspace_page()
        self.assertIn("YouTube publish review", page)
        self.assertIn("Publish to YouTube", page)
        self.assertIn("Notify subscribers", page)
