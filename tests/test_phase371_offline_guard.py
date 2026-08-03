from __future__ import annotations

import unittest
from pathlib import Path

from dashboard import plugin_sandbox_health_payload


class Phase371OfflineGuardTests(unittest.TestCase):
    def test_provider_has_no_direct_network_or_shell_download_path(self) -> None:
        text = Path("plugins/providers/local_transcription/provider.py").read_text(encoding="utf-8")
        self.assertNotIn("snapshot_download", text)
        self.assertNotIn("requests.", text)
        self.assertNotIn("httpx.", text)
        self.assertNotIn("shell=True", text)
        self.assertNotIn("os.system", text)
        self.assertNotIn("content/", text)
        self.assertNotIn("drafts/", text)

    def test_phase20_2_still_blocked(self) -> None:
        health = plugin_sandbox_health_payload()["health"]
        self.assertEqual(health["controller_status"], "sandbox_incomplete")
        self.assertFalse(health["production_ready"])
