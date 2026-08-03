from __future__ import annotations

import unittest
from pathlib import Path

from dashboard import plugin_sandbox_health_payload
from plugins.providers.local_transcription import LocalTranscriptionConfig, LocalTranscriptionProvider


class Phase37SecurityTests(unittest.TestCase):
    def test_no_network_download_shell_or_publication_payment_scope(self) -> None:
        provider_text = Path("plugins/providers/local_transcription/provider.py").read_text(encoding="utf-8")
        self.assertNotIn("requests.", provider_text)
        self.assertNotIn("httpx.", provider_text)
        self.assertNotIn("socket.socket", provider_text)
        self.assertNotIn("shell=True", provider_text)
        self.assertNotIn("os.system", provider_text)
        self.assertNotIn("publish(", provider_text)
        self.assertNotIn("payment", provider_text)
        self.assertNotIn("order", provider_text)
        self.assertNotIn("model.download", provider_text.lower())
        self.assertIn('"model_autodownload": False', provider_text)
        self.assertNotIn("content/", provider_text)
        self.assertNotIn("drafts/", provider_text)

    def test_phase20_2_remains_blocked_and_provider_does_not_autodownload(self) -> None:
        health = plugin_sandbox_health_payload()["health"]
        self.assertFalse(health["production_ready"])
        self.assertEqual(health["controller_status"], "sandbox_incomplete")
        provider = LocalTranscriptionProvider(provider_config=LocalTranscriptionConfig(model=""))
        self.assertFalse(provider.health_check()["model_autodownload"])
