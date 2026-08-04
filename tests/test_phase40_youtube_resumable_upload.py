import tempfile
import unittest

from tests.phase40_support import make_plan, service


class YouTubeResumableUploadTests(unittest.TestCase):
    def test_confirmed_upload_uses_one_insert_and_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = make_plan(tmp)
            runtime = service()
            result = runtime.publish(
                plan, confirmation=runtime.prepare(plan)["confirmation_checksum"], access_token="test"
            )
            self.assertEqual(result.remote_video_id, "youtube-test-video")
            self.assertEqual(result.status, "processed")
            self.assertEqual(runtime.transport.create_count, 1)
            self.assertEqual(result.observed_privacy, "private")

    def test_same_execution_does_not_create_second_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = make_plan(tmp)
            runtime = service()
            confirmation = runtime.prepare(plan)["confirmation_checksum"]
            runtime.publish(plan, confirmation=confirmation, access_token="test")
            runtime.publish(plan, confirmation=confirmation, access_token="test")
            self.assertEqual(runtime.transport.create_count, 1)
