import tempfile
import unittest
from pathlib import Path

from channels.youtube.transport import FakeYouTubeTransport
from tests.phase40_support import make_plan, service


class Phase401RestartReconciliationTests(unittest.TestCase):
    def test_restart_reads_existing_session_without_new_insert(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_path = Path(tmp) / "sessions.json"
            transport = FakeYouTubeTransport()
            first = service(transport)
            first.session_store_path = session_path
            plan = make_plan(tmp)
            confirmation = first.prepare(plan)["confirmation_checksum"]
            first.publish(plan, confirmation=confirmation, access_token="test")
            second = service(transport)
            second.session_store_path = session_path
            second.sessions = second._load_sessions()
            self.assertIn(plan.execution_id, second.sessions)
            self.assertEqual(transport.create_count, 1)
