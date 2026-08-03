from __future__ import annotations

import json
import unittest

from plugin_runtime import ROOT_DIR


class Phase37TranscriptionContractTests(unittest.TestCase):
    def test_provider_manifest_declares_transcription_contract(self) -> None:
        manifest = json.loads(
            (ROOT_DIR / "plugins" / "providers" / "local_transcription" / "plugin.manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["id"], "provider.transcription.local")
        self.assertEqual(manifest["type"], "provider")
        self.assertIn("transcription.media", manifest["capabilities"])
        self.assertIn("transcription.accepts.asset.video", manifest["capabilities"])
        self.assertIn("transcription.accepts.asset.audio", manifest["capabilities"])
        self.assertIn("transcription.produces.timeline.transcript", manifest["capabilities"])
        self.assertEqual(manifest["config_schema"]["transcription_provider_contract_version"], "0.1")
