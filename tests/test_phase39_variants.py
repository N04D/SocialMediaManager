from __future__ import annotations

import unittest

from tests.phase39_support import WooFixtureServer, woo_plugin


class Phase39VariantsTests(unittest.TestCase):
    def test_variable_product_variations_are_read_only_variant_data(self) -> None:
        with WooFixtureServer() as server:
            plugin = woo_plugin(server.url)
            plugin.sync_products()
            hoodie = next(product for product in plugin.list_products() if product.title == "Sabr hoodie")
            self.assertEqual(hoodie.availability, "out_of_stock")
            self.assertEqual(len(hoodie.variants), 2)
            first = hoodie.variants[0]
            self.assertEqual(first["attributes"]["Size"], "M")
            self.assertEqual(first["price"], 59.0)
            self.assertEqual(first["regular_price"], 69.0)
            self.assertEqual(first["sale_price"], 59.0)
            self.assertEqual(first["stock_status"], "out_of_stock")
