import json
import unittest
from pathlib import Path


class YouTubeManifestTests(unittest.TestCase):
    def test_manifest_declares_independent_short_destination(self):
        payload = json.loads(Path("channels/youtube/plugin.manifest.json").read_text())
        self.assertEqual(payload["id"], "channel.youtube")
        self.assertIn("channel.publish.short_video", payload["capabilities"])
        self.assertIn("publication.status.read", payload["capabilities"])
        self.assertEqual(payload["config_schema"]["default_privacy"]["default"], "private")
