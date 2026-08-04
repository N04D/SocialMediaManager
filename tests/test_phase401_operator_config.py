import os
import unittest


class Phase401OperatorConfigTests(unittest.TestCase):
    def test_host_does_not_have_real_operator_configuration(self):
        self.assertFalse(os.environ.get("YOUTUBE_ACCESS_TOKEN"))
        self.assertFalse(os.environ.get("YOUTUBE_ASSET_PATH"))
