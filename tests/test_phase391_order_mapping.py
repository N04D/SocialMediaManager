import unittest

from tests.phase391_support import SABR_PRODUCT, OutcomeFixtureServer, outcome_plugin


class Phase391OrderMappingTests(unittest.TestCase):
    def test_order_and_line_identity_are_store_scoped(self):
        with OutcomeFixtureServer() as server:
            plugin = outcome_plugin(server.url)
            self.assertEqual(plugin.sync_orders()["status"], "succeeded")
            order = plugin.list_orders()[0]
            self.assertEqual(order.external_ref, "woocommerce:fixture-store:order:1001")
            self.assertEqual(order.line_items[0].product_id, SABR_PRODUCT)


if __name__ == "__main__":
    unittest.main()
