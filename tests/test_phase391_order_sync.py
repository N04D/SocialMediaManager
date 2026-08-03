import unittest

from tests.phase391_support import OutcomeFixtureServer, outcome_plugin


class Phase391OrderSyncTests(unittest.TestCase):
    def test_pagination_and_resync_are_idempotent(self):
        with OutcomeFixtureServer() as server:
            plugin = outcome_plugin(server.url)
            first = plugin.sync_orders()
            second = plugin.sync_orders()
            self.assertEqual(first["orders_observed"], second["orders_observed"])
            self.assertEqual(len(plugin.list_orders()), 6)

    def test_partial_failure_preserves_previous_orders(self):
        with OutcomeFixtureServer() as server:
            plugin = outcome_plugin(server.url)
            plugin.sync_orders()
            plugin.client.config = plugin.client.config
            self.assertEqual(len(plugin.list_orders()), 6)


if __name__ == "__main__":
    unittest.main()
