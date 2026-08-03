from __future__ import annotations

import unittest

from plugins.commerce.woocommerce.plugin import WooCommerceError
from tests.phase39_support import PRODUCTS, WooFixtureServer, woo_plugin


class Phase39CatalogSyncTests(unittest.TestCase):
    def test_pagination_sync_status_and_product_lookup(self) -> None:
        with WooFixtureServer() as server:
            plugin = woo_plugin(server.url)
            self.assertEqual(plugin.health_check()["catalog_status"], "not_synced")
            sync = plugin.sync_products()
            self.assertEqual(sync["status"], "succeeded")
            self.assertEqual(sync["product_count"], 4)
            self.assertEqual(sync["pages_fetched"], 2)
            self.assertTrue(sync["last_sync_at"])
            self.assertEqual(plugin.lookup("woocommerce.fixture-store.101").title, "Sabr T-shirt")

    def test_partial_failure_preserves_previous_catalog_and_marks_failed(self) -> None:
        with WooFixtureServer() as server:
            plugin = woo_plugin(server.url)
            plugin.sync_products()
            self.assertEqual(len(plugin.list_products()), 4)
            plugin.client.get_json = lambda *args, **kwargs: (_ for _ in ()).throw(
                WooCommerceError("provider_error", "boom")
            )
            result = plugin.sync_products()
            self.assertEqual(result["status"], "failed")
            self.assertEqual(len(plugin.list_products()), 4)

    def test_historical_product_is_marked_source_missing_not_deleted(self) -> None:
        with WooFixtureServer() as server:
            plugin = woo_plugin(server.url)
            plugin.sync_products()
            removed = PRODUCTS.pop()
            try:
                sync = plugin.sync_products()
            finally:
                PRODUCTS.append(removed)
            self.assertEqual(sync["status"], "succeeded")
            self.assertIn("woocommerce.fixture-store.104", sync["source_missing"])
