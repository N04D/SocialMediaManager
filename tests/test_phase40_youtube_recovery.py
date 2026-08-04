import tempfile
import unittest
from pathlib import Path

from channels.youtube.transport import FakeYouTubeTransport
from tests.phase40_support import make_plan, service


class YouTubeRecoveryTests(unittest.TestCase):
    def test_interruption_does_not_start_second_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = make_plan(tmp)
            transport = FakeYouTubeTransport(fail_after_bytes=1)
            runtime = service(transport)
            result = runtime.publish(
                plan, confirmation=runtime.prepare(plan)["confirmation_checksum"], access_token="test"
            )
            self.assertIn(result.status, {"interrupted", "uncertain"})
            self.assertEqual(transport.create_count, 1)
            self.assertEqual(len([r for r in transport.requests if r.get("endpoint") == "videos.insert"]), 1)

    def test_session_state_survives_service_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "youtube_sessions.json"
            plan = make_plan(tmp)
            transport = FakeYouTubeTransport(fail_after_bytes=1)
            first = service(transport)
            first.session_store_path = path
            first.publish(plan, confirmation=first.prepare(plan)["confirmation_checksum"], access_token="test")
            second = service(transport)
            second.session_store_path = path
            second.sessions = second._load_sessions()
            self.assertIn(plan.execution_id, second.sessions)
