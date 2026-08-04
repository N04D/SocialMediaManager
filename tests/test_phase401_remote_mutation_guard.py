import tempfile
import unittest

from channels.youtube.transport import FakeYouTubeTransport
from tests.phase40_support import make_plan, service


class Phase401MutationGuardTests(unittest.TestCase):
    def test_private_defaults_and_single_insert_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport = FakeYouTubeTransport()
            runtime = service(transport)
            plan = make_plan(tmp)
            confirmation = runtime.prepare(plan)["confirmation_checksum"]
            evidence = runtime.publish(plan, confirmation=confirmation, access_token="test")
            self.assertEqual(plan.privacy, "private")
            self.assertFalse(plan.notify_subscribers)
            self.assertEqual(transport.create_count, 1)
            self.assertEqual(evidence.observed_privacy, "private")
