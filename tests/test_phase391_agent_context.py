import unittest

from tests.phase391_support import OutcomeFixtureServer, outcome_plugin


class Phase391AgentContextTests(unittest.TestCase):
    def test_outcome_metadata_is_evidence_based_and_pii_free(self):
        with OutcomeFixtureServer() as server:
            plugin = outcome_plugin(server.url)
            plugin.sync_orders()
            outcomes = plugin.order_outcomes(
                plugin.list_orders()[0],
                workspace_id="w",
                click_bindings={"click-001": {"product_id": "woocommerce.fixture-store.101"}},
            )
            payload = str([item.metadata for item in outcomes])
            self.assertIn("direct", payload)
            self.assertNotIn("private@example.test", payload)


if __name__ == "__main__":
    unittest.main()
