import tempfile
import unittest

from channels.youtube.channel import confirmation_checksum
from tests.phase40_support import make_plan


class YouTubeMetadataTests(unittest.TestCase):
    def test_confirmation_binds_title_description_privacy_and_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = make_plan(tmp)
            changed = make_plan(tmp, title="Changed")
            self.assertNotEqual(confirmation_checksum(plan), confirmation_checksum(changed))
