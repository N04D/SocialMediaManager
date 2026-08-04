import tempfile
import unittest

from channels.youtube.errors import YouTubeChannelError
from tests.phase40_support import make_plan, service


class YouTubePublicationTests(unittest.TestCase):
    def test_no_confirmation_means_no_external_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = service()
            with self.assertRaises(YouTubeChannelError):
                runtime.publish(make_plan(tmp), confirmation="", access_token="test")
            self.assertEqual(runtime.transport.requests, [])

    def test_changed_asset_or_metadata_invalidates_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = service()
            original = make_plan(tmp)
            confirmation = runtime.prepare(original)["confirmation_checksum"]
            with self.assertRaises(YouTubeChannelError):
                runtime.publish(make_plan(tmp, title="drifted"), confirmation=confirmation, access_token="test")
