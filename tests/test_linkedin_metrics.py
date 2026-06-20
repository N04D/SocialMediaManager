from __future__ import annotations

import sys
import types
import unittest

pipeline_stub = types.ModuleType("pipeline")


class _AppConfig:
    pass


pipeline_stub.AppConfig = _AppConfig
pipeline_stub.POST_BUTTON_PATTERNS = [r"post"]
pipeline_stub.run_local_ai = lambda *args, **kwargs: "stubbed derivative"
pipeline_stub.open_linkedin_session = lambda *args, **kwargs: None
sys.modules["pipeline"] = pipeline_stub

from channels.linkedin.worker.metrics import parse_compact_number


class LinkedInMetricsParsingTests(unittest.TestCase):
    def test_parse_compact_number_handles_common_linkedin_formats(self) -> None:
        cases = {
            "123": 123,
            "1,234": 1234,
            "1.2K": 1200,
            "1K": 1000,
            "2.5M": 2_500_000,
            "7,5K": 7500,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_compact_number(raw), expected)

    def test_parse_compact_number_returns_none_for_unknown_values(self) -> None:
        for raw in ["", "n/a", "unknown"]:
            with self.subTest(raw=raw):
                self.assertIsNone(parse_compact_number(raw))
