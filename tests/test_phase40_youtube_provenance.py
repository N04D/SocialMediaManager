import tempfile
import unittest

from tests.phase40_support import make_plan, service


class YouTubeProvenanceTests(unittest.TestCase):
    def test_publication_keeps_exact_asset_variant_revision_and_remote_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = service()
            plan = make_plan(tmp)
            result = runtime.publish(
                plan, confirmation=runtime.prepare(plan)["confirmation_checksum"], access_token="test"
            )
            self.assertEqual(result.asset_id, plan.asset_id)
            self.assertEqual(result.variant_id, plan.variant_id)
            self.assertEqual(result.revision_id, plan.revision_id)
            self.assertEqual(result.evidence["remote_video_id"], result.remote_video_id)
