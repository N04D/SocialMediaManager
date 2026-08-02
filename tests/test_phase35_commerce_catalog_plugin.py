from __future__ import annotations

import unittest

from plugins.commerce.catalog import CommerceCatalogPlugin


class Phase35CommerceCatalogPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = CommerceCatalogPlugin()

    def test_catalog_product_contract_and_outcomes(self) -> None:
        products = self.plugin.list_products()
        self.assertGreaterEqual(len(products), 3)
        sabr = self.plugin.lookup("sabr-tshirt")
        self.assertIsNotNone(sabr)
        assert sabr is not None
        self.assertEqual(sabr.title, "Sabr T-shirt")
        self.assertEqual(sabr.price, 29.0)
        self.assertEqual(sabr.currency, "EUR")
        self.assertEqual(sabr.availability, "in_stock")
        self.assertTrue(sabr.images)
        self.assertTrue(sabr.product_url.startswith("https://shop.example.test/"))
        self.assertIn("outcome.sale", self.plugin.outcome_capabilities())

    def test_product_entities_and_out_of_stock_policy(self) -> None:
        entities = self.plugin.product_entities()
        self.assertIn("entity.product.sabr-tshirt", {entity.id for entity in entities})
        available = self.plugin.list_products(include_unavailable=False)
        self.assertNotIn("sabr-hoodie", {product.product_id for product in available})
        policy = self.plugin.promotion_policy()
        self.assertTrue(policy["only_available_products"])
        self.assertFalse(policy["payment_mutation"])
        self.assertFalse(policy["order_creation"])

    def test_health_is_read_only_no_payment_mutation(self) -> None:
        health = self.plugin.health_check()
        self.assertEqual(health["catalog_status"], "fixture_read_only")
        self.assertFalse(health["payment_mutation"])
        self.assertFalse(health["order_creation"])
