from __future__ import annotations

from tests.phase33_support import Phase33UITestCase


class MVPComposerUIPhase33Tests(Phase33UITestCase):
    def test_composer_fields_autosave_preview_variants_media_cta(self) -> None:
        html = self.assert_html_contains(
            "/content/phase33-fixture/compose",
            "Markdown editor",
            "SEO description",
            "Tags",
            "Author",
            "CTA",
            "Website variant",
            "Mastodon variant",
            "LinkedIn variant",
            "Saved",
            "Website",
            "Mastodon",
            "LinkedIn",
            "Media alt text",
        )
        self.assert_no_sensitive_fixture_data(html)

    def test_conflict_state_is_visible_and_not_silent(self) -> None:
        html = self.assert_html_contains("/content/phase33-fixture/compose", "Conflict detected", "Expected version")
        self.assertIn("reload to use the latest revision", html)


if __name__ == "__main__":
    import unittest

    unittest.main()
