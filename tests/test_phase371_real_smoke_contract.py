from __future__ import annotations

import unittest
from pathlib import Path


class Phase371RealSmokeContractTests(unittest.TestCase):
    def test_real_smoke_script_exists_and_is_not_deterministic_engine(self) -> None:
        script = Path("scripts/smoke-local-transcription.py")
        self.assertTrue(script.is_file())
        text = script.read_text(encoding="utf-8")
        self.assertIn("REAL LOCAL TRANSCRIPTION SMOKE: PASS", text)
        self.assertIn("transcription_provider()", text)
        self.assertNotIn("DeterministicTranscriptionEngine", text)
