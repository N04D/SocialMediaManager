from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Phase35PluginIndependenceTests(unittest.TestCase):
    def assert_file_omits(self, path: str, forbidden: tuple[str, ...]) -> None:
        text = (ROOT / path).read_text(encoding="utf-8")
        for needle in forbidden:
            self.assertNotIn(needle, text, f"{path} must not reference {needle}")

    def test_source_plugin_knows_only_source_concepts(self) -> None:
        self.assert_file_omits(
            "plugins/sources/youtube/plugin.py",
            ("commerce.catalog", "plugin.video_repurpose", "VideoRepurposePlugin", "CommerceCatalogPlugin", "LinkedIn"),
        )

    def test_transformation_plugin_has_no_source_or_commerce_dependency(self) -> None:
        self.assert_file_omits(
            "plugins/transformations/video_repurpose/plugin.py",
            ("YouTube", "youtube", "commerce", "CommerceCatalog", "LinkedIn"),
        )

    def test_commerce_plugin_has_no_source_or_channel_dependency(self) -> None:
        self.assert_file_omits(
            "plugins/commerce/catalog/plugin.py",
            ("YouTube", "youtube", "clip", "repurpose", "LinkedIn", "publish("),
        )

    def test_composition_uses_capability_registry_only(self) -> None:
        text = (ROOT / "plugins/playbooks/creator_commerce/playbook.py").read_text(encoding="utf-8")
        self.assertIn("providers_for(capability)", text)
        self.assertNotIn("call YoutubePlugin", text)
        self.assertNotIn("call VideoRepurposePlugin", text)
        self.assertNotIn("call CommerceCatalogPlugin", text)
