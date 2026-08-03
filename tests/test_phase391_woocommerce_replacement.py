import unittest

from plugins.commerce.woocommerce.plugin import PLUGIN_ID, WooCommerceCatalogPlugin


class Phase391WooCommerceReplacementTests(unittest.TestCase):
    def test_outcome_consumer_uses_generic_capabilities(self):
        self.assertIn("outcome.purchase", WooCommerceCatalogPlugin.capabilities)
        self.assertIn("outcome.revenue", WooCommerceCatalogPlugin.capabilities)
        self.assertNotIn("commerce.shopify", PLUGIN_ID)


if __name__ == "__main__":
    unittest.main()
