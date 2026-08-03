import unittest

from tests.phase391_support import OutcomeFixtureServer, outcome_plugin


class Phase391PrivacyTests(unittest.TestCase):
    def test_customer_fields_are_not_in_order_model_or_outcome(self):
        with OutcomeFixtureServer() as server:
            plugin = outcome_plugin(server.url)
            plugin.sync_orders()
            order = plugin.list_orders()[0]
            self.assertNotIn("billing", str(order))
            self.assertNotIn("private@example.test", str(plugin.order_outcomes(order, workspace_id="w")))


if __name__ == "__main__":
    unittest.main()
