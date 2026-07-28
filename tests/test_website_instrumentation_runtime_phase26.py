from __future__ import annotations

import unittest
from pathlib import Path


class WebsiteInstrumentationRuntimePhase26Tests(unittest.TestCase):
    def test_runtime_has_safe_api_and_no_persistent_tracking(self) -> None:
        runtime = Path("web/instrumentation/smm-analytics.js").read_text(encoding="utf-8")
        self.assertIn("SMMAnalytics", runtime)
        for marker in (
            "eval(",
            "new Function",
            "innerHTML",
            "document.cookie",
            "localStorage",
            "sessionStorage",
            "indexedDB",
            "navigator.userAgent",
            "FormData",
            "input.value",
        ):
            self.assertNotIn(marker, runtime)
        self.assertIn('closest("[data-smm-track]")', runtime)
        self.assertIn("state.sentKeys", runtime)

    def test_plausible_bridge_is_public_browser_only(self) -> None:
        bridge = Path("web/instrumentation/plausible-bridge.js").read_text(encoding="utf-8")
        self.assertIn("window.plausible", bridge)
        self.assertNotIn("Authorization", bridge)
        self.assertNotIn("api_key", bridge)
        self.assertNotIn("token", bridge.lower())
        self.assertNotIn("/api/event", bridge)
        self.assertIn("analytics.plausible", bridge)


if __name__ == "__main__":
    unittest.main()
