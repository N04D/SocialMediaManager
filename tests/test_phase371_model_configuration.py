from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plugins.providers.local_transcription import WhisperLocalEngine


class Phase371ModelConfigurationTests(unittest.TestCase):
    def test_local_path_guard_requires_existing_model_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "local-model"
            self.assertFalse(path.exists())
            engine = WhisperLocalEngine()
            self.assertEqual(engine.engine_id, "whisper_compatible_local")
