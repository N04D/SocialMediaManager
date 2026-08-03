from __future__ import annotations

import unittest

from plugins.commerce.woocommerce.plugin import StaticSecretReader, WooCommerceCatalogPlugin, WooCommerceError
from tests.phase39_support import KEY_REF, SECRET_REF, WooFixtureServer, woo_config, woo_plugin


class Phase39WooCommerceHttpTests(unittest.TestCase):
    def test_connection_success_and_authentication_failure(self) -> None:
        with WooFixtureServer() as server:
            plugin = woo_plugin(server.url)
            self.assertEqual(plugin.test_connection()["status"], "ready")
            bad = WooCommerceCatalogPlugin(
                config=woo_config(server.url),
                secret_reader=StaticSecretReader({KEY_REF: "bad", SECRET_REF: "bad"}),
            )
            self.assertEqual(bad.test_connection()["status"], "authentication_failed")

    def test_failure_mapping_for_malformed_500_and_timeout(self) -> None:
        with WooFixtureServer(mode="malformed") as server:
            plugin = woo_plugin(server.url)
            self.assertEqual(plugin.sync_products()["status"], "failed")
            self.assertEqual(plugin.health_check()["catalog_status"], "failed")
        with WooFixtureServer(mode="server_error") as server:
            plugin = woo_plugin(server.url)
            self.assertEqual(plugin.sync_products()["error_code"], "provider_error")
        with WooFixtureServer(mode="timeout") as server:
            plugin = woo_plugin(server.url, timeout=0.01)
            result = plugin.sync_products()
            self.assertEqual(result["status"], "failed")
            self.assertIn(result["error_code"], {"timeout", "store_unreachable"})

    def test_mutation_methods_are_blocked(self) -> None:
        with WooFixtureServer() as server:
            plugin = woo_plugin(server.url)
            for method in ["POST", "PUT", "PATCH", "DELETE"]:
                with self.assertRaises(WooCommerceError):
                    plugin.client.request_mutation(method, "/products")
