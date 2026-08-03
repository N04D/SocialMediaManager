from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.core.plugins.manifest import PluginManifest


class Phase39WooCommerceManifestTests(unittest.TestCase):
    def test_manifest_declares_generic_commerce_capabilities(self) -> None:
        payload = json.loads(Path("plugins/commerce/woocommerce/plugin.manifest.json").read_text(encoding="utf-8"))
        manifest = PluginManifest.from_dict(payload)
        self.assertEqual(manifest.id, "commerce.woocommerce")
        self.assertIn("commerce.product_catalog", manifest.capabilities)
        self.assertIn("commerce.product_lookup", manifest.capabilities)
        self.assertIn("commerce.product_media", manifest.capabilities)
        self.assertIn("entity.product", manifest.capabilities)
        self.assertTrue(payload["config_schema"]["read_only"])
