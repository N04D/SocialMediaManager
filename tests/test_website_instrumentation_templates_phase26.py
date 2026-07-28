from __future__ import annotations

import unittest

from src.core.website_instrumentation.service import WebsiteInstrumentationService


class WebsiteInstrumentationTemplatesPhase26Tests(unittest.TestCase):
    def test_static_site_templates_exist_and_are_secret_free(self) -> None:
        payload = WebsiteInstrumentationService().templates()
        profiles = {item["profile_id"]: item["content"] for item in payload["templates"]}
        for profile in ("generic", "astro", "hugo", "jekyll", "eleventy", "nextjs"):
            self.assertIn(profile, profiles)
            self.assertIn("smm-analytics.js", profiles[profile])
            self.assertNotIn("api_key", profiles[profile].lower())
            self.assertNotIn("authorization", profiles[profile].lower())
        self.assertIn("CSP", profiles["generic"])


if __name__ == "__main__":
    unittest.main()
