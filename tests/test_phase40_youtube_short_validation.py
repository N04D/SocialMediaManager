import tempfile
import unittest

from channels.youtube.channel import validate_short_asset
from channels.youtube.errors import YouTubeChannelError
from tests.phase40_support import make_plan


class YouTubeShortValidationTests(unittest.TestCase):
    def test_vertical_short_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(validate_short_asset(make_plan(tmp))["short_eligible"])

    def test_long_or_landscape_short_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(YouTubeChannelError):
                validate_short_asset(make_plan(tmp, duration=181))
            with self.assertRaises(YouTubeChannelError):
                validate_short_asset(make_plan(tmp, width=1920, height=1080))
