import unittest

from tests.phase391_support import OutcomeFixtureServer, outcome_plugin


class Phase391OutcomeMappingTests(unittest.TestCase):
    def test_completed_is_sale_and_cancelled_is_not_revenue(self):
        with OutcomeFixtureServer() as server:
            plugin = outcome_plugin(server.url)
            plugin.sync_orders()
            by_id = {item.order_id: item for item in plugin.list_orders()}
            self.assertTrue(by_id["1001"].recognized_sale)
            self.assertFalse(by_id["1005"].recognized_sale)
            self.assertFalse(by_id["1006"].recognized_sale)
            self.assertEqual(plugin.order_outcomes(by_id["1001"], workspace_id="w")[0].outcome_type, "purchase")


if __name__ == "__main__":
    unittest.main()
