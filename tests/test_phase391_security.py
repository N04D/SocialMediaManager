import unittest

from plugins.commerce.woocommerce.plugin import BLOCKED_MUTATION_METHODS, WooCommerceError
from tests.phase391_support import OutcomeFixtureServer, outcome_plugin


class Phase391SecurityTests(unittest.TestCase):
    def test_order_adapter_is_get_only(self):
        self.assertEqual(BLOCKED_MUTATION_METHODS, {"POST", "PUT", "PATCH", "DELETE"})
        with OutcomeFixtureServer() as server:
            client = outcome_plugin(server.url).client
            with self.assertRaises(WooCommerceError):
                client.request_mutation("POST", "/orders")


if __name__ == "__main__":
    unittest.main()
