import tempfile
import unittest

from channels.youtube.auth import redact_tokens
from channels.youtube.errors import YouTubeChannelError
from tests.phase40_support import make_plan, service


class YouTubeSecurityTests(unittest.TestCase):
    def test_tokens_are_redacted(self):
        self.assertEqual(
            redact_tokens({"access_token": "secret", "refresh_token": "refresh"})["access_token"], "[REDACTED]"
        )

    def test_no_confirmation_and_no_mutation_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = service()
            with self.assertRaises(YouTubeChannelError):
                runtime.publish(make_plan(tmp), access_token="test")
            self.assertFalse(hasattr(runtime.transport, "delete_video"))
            self.assertFalse(hasattr(runtime.transport, "update_video"))
