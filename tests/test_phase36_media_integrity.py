from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.phase36_support import Phase36Harness


class Phase36MediaIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase36Harness()
        self.addCleanup(self.harness.close)

    def test_captioned_output_materializes_and_passes_probe_with_audio(self) -> None:
        rendered = self.harness.render_candidate()["result"]
        asset = rendered.captioned_asset
        provider = self.harness.runtime.media_provider(preferred_provider_id=asset.storage_provider_id)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "short.mp4"
            with path.open("wb") as handle:
                for chunk in provider.open_stream(asset.storage_reference):
                    handle.write(chunk)
            metadata = self.harness.plugin.probe_video(path)
        self.assertEqual(metadata.width, 360)
        self.assertEqual(metadata.height, 640)
        self.assertTrue(metadata.audio_present)
        self.assertGreater(metadata.duration, 0)
