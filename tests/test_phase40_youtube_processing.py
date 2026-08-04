import tempfile
import unittest

from tests.phase40_support import make_plan, service


class YouTubeProcessingTests(unittest.TestCase):
    def test_processing_is_not_reported_as_ready_until_readback_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = service()
            runtime.transport.processing_status = "processing"
            result = runtime.publish(
                make_plan(tmp),
                confirmation=runtime.prepare(make_plan(tmp))["confirmation_checksum"],
                access_token="test",
            )
            self.assertEqual(result.status, "processing")
            self.assertEqual(result.processing_status, "processing")
