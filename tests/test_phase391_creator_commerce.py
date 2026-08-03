import unittest

from plugins.commerce.outcomes import outcome_summary
from tests.phase391_support import OutcomeFixtureServer, outcome_plugin


class Phase391CreatorCommerceTests(unittest.TestCase):
    def test_sabr_truth_test_separates_direct_strong_and_unknown_revenue(self):
        with OutcomeFixtureServer() as server:
            plugin = outcome_plugin(server.url)
            plugin.sync_orders()
            clicks = {"click-001": {"product_id": "woocommerce.fixture-store.101", "variant_id": "sabr-cta"}}
            campaigns = {
                "sabr-campaign": {
                    "product_id": "woocommerce.fixture-store.101",
                    "variant_id": "variant-123",
                    "content_id": "variant-123",
                }
            }
            outcomes = [
                outcome
                for order in plugin.list_orders()[:3]
                for outcome in plugin.order_outcomes(
                    order, workspace_id="creator-commerce", click_bindings=clicks, campaign_bindings=campaigns
                )
            ]
            summary = outcome_summary(outcomes)
            self.assertEqual(summary["revenue"]["EUR"]["direct"], 29.0)
            self.assertEqual(summary["revenue"]["EUR"]["strong"], 29.0)
            self.assertEqual(summary["revenue"]["EUR"]["unknown"], 29.0)


if __name__ == "__main__":
    unittest.main()
