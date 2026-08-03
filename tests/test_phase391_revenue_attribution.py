import unittest

from plugins.commerce.outcomes import outcome_summary
from tests.phase391_support import OutcomeFixtureServer, outcome_plugin


class Phase391RevenueAttributionTests(unittest.TestCase):
    def test_multi_product_order_uses_line_item_revenue(self):
        with OutcomeFixtureServer() as server:
            plugin = outcome_plugin(server.url)
            plugin.sync_orders()
            order = next(item for item in plugin.list_orders() if item.order_id == "1004")
            outcomes = plugin.order_outcomes(
                order, workspace_id="w", click_bindings={"click-001": {"product_id": "woocommerce.fixture-store.101"}}
            )
            summary = outcome_summary(outcomes)
            self.assertEqual(summary["revenue"]["EUR"]["direct"], 29.0)
            self.assertEqual(summary["revenue"]["EUR"]["unknown"], 15.0)
            self.assertEqual(len([item for item in outcomes if item.outcome_type == "revenue"]), 2)


if __name__ == "__main__":
    unittest.main()
