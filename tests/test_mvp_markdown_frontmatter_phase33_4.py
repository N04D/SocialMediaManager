from __future__ import annotations

from tests.phase334_support import Phase334TestCase


class MVPMarkdownFrontmatterPhase334Tests(Phase334TestCase):
    def test_generated_frontmatter_uses_custom_seo_description_not_default_summary(self) -> None:
        _session_id, repo, publication = self.publish_custom_seo()
        article = repo / "articles" / "mvp-dogfood-publication-334.md"
        markdown = article.read_text(encoding="utf-8")

        self.assertIn(f'description: "{self.custom_seo}"', markdown)
        self.assertNotIn('description: "Default summary that must not replace custom SEO."', markdown)
        self.assertEqual(publication["checksum_bindings"]["seo_description"], self.custom_seo)
        self.assertEqual(publication["checksum_bindings"]["seo_description_source"], "custom")
