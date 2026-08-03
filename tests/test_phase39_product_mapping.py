from __future__ import annotations

import unittest

from tests.phase39_support import WooFixtureServer, woo_plugin


class Phase39ProductMappingTests(unittest.TestCase):
    def test_simple_products_map_to_generic_product_contract(self) -> None:
        with WooFixtureServer() as server:
            plugin = woo_plugin(server.url)
            sync = plugin.sync_products()
            self.assertEqual(sync["status"], "succeeded")
            sabr = plugin.search("sabr patience")[0]
            self.assertEqual(sabr.title, "Sabr T-shirt")
            self.assertEqual(sabr.price, 29.0)
            self.assertEqual(sabr.currency, "EUR")
            self.assertEqual(sabr.availability, "in_stock")
            self.assertEqual(sabr.metadata["regular_price"], 29.0)
            self.assertIsNone(sabr.metadata["sale_price"])
            self.assertIn("Apparel", sabr.categories)
            self.assertIn("sabr", sabr.tags)
            self.assertEqual(sabr.images[0]["url"], "https://shop.local/sabr-shirt.png")

    def test_unknown_price_is_not_zero_and_identity_is_store_scoped(self) -> None:
        with WooFixtureServer() as server:
            plugin = woo_plugin(server.url)
            plugin.sync_products()
            notebook = next(product for product in plugin.list_products() if product.title == "Notebook")
            self.assertIsNone(notebook.price)
            self.assertEqual(notebook.metadata["price_status"], "unavailable")
            self.assertIn("fixture-store.104", notebook.product_id)
            other = woo_plugin(server.url, store_id="second-store")
            other.sync_products()
            other_notebook = next(product for product in other.list_products() if product.title == "Notebook")
            self.assertNotEqual(notebook.product_id, other_notebook.product_id)
