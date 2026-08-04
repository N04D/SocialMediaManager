import unittest

from channels.youtube.auth import MINIMAL_SCOPES, OAuthStateStore, validate_redirect_uri
from channels.youtube.errors import YouTubeChannelError


class YouTubeOAuthTests(unittest.TestCase):
    def test_state_is_random_single_use_and_scope_is_minimal(self):
        store = OAuthStateStore()
        one = store.issue(workspace_id="w", channel_account_id="a", redirect_uri="https://app.test/callback")
        two = store.issue(workspace_id="w", channel_account_id="a", redirect_uri="https://app.test/callback")
        self.assertNotEqual(one.state, two.state)
        self.assertEqual(one.scopes, MINIMAL_SCOPES)
        store.consume(one.state, workspace_id="w", channel_account_id="a", redirect_uri="https://app.test/callback")
        with self.assertRaises(YouTubeChannelError):
            store.consume(one.state, workspace_id="w", channel_account_id="a", redirect_uri="https://app.test/callback")

    def test_redirect_uri_rejects_embedded_credentials(self):
        with self.assertRaises(YouTubeChannelError):
            validate_redirect_uri("https://user:secret@example.test/callback")
