from __future__ import annotations

import unittest
from pathlib import Path


class WebsiteInstrumentationSecurityPhase26Tests(unittest.TestCase):
    def test_no_backend_provider_write_path_or_visitor_tracking_storage(self) -> None:
        files = [
            Path("src/core/website_instrumentation/service.py"),
            Path("src/core/website_instrumentation/worker.py"),
            Path("src/providers/analytics/plausible/instrumentation/bridge.py"),
            Path("web/instrumentation/smm-analytics.js"),
            Path("web/instrumentation/plausible-bridge.js"),
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
        for marker in (
            "requests.",
            "httpx.",
            "socket.socket",
            "Authorization",
            "api_key",
            "document.cookie",
            "fingerprint",
            "FormData",
            "input.value",
        ):
            self.assertNotIn(marker, combined)
        self.assertNotIn("/api/event", "\n".join(path.read_text(encoding="utf-8") for path in files[:-1]))
        self.assertNotIn("content/drafts", combined)

    def test_templates_and_docs_do_not_contain_credentials(self) -> None:
        for root in (Path("templates/website-instrumentation"), Path("docs")):
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in {".md", ".js"}:
                    continue
                text = path.read_text(encoding="utf-8").lower()
                if "website-instrumentation" in str(path) or "plausible-browser-bridge" in str(path):
                    self.assertNotIn("secret-", text)
                    self.assertNotIn("private key", text)


if __name__ == "__main__":
    unittest.main()
