from __future__ import annotations

import json
import unittest
from pathlib import Path

from plugins.commerce.woocommerce.plugin import WooCommerceError, map_product
from tests.phase39_support import PRODUCTS, WooFixtureServer, woo_config, woo_plugin


class Phase39SecurityTests(unittest.TestCase):
    def test_untrusted_html_is_plain_data_not_instruction(self) -> None:
        with WooFixtureServer() as server:
            config = woo_config(server.url)
            product = map_product(PRODUCTS[0], config=config)
            self.assertNotIn("<script>", product.description)
            self.assertNotIn("Ignore previous instructions", product.description)
            self.assertEqual(product.metadata["trust_boundary"], "external_untrusted_commerce_data")

    def test_no_write_mutation_methods_or_order_payment_refund_support(self) -> None:
        with WooFixtureServer() as server:
            plugin = woo_plugin(server.url)
            health = plugin.health_check()
            self.assertTrue(health["read_only"])
            self.assertFalse(health["payment_mutation"])
            self.assertFalse(health["order_creation"])
            self.assertEqual(health["mutation_methods"], [])
            for method in ["POST", "PUT", "PATCH", "DELETE"]:
                with self.assertRaises(WooCommerceError):
                    plugin.client.request_mutation(method, "/orders")

    def test_no_secret_output_no_shell_no_requests_no_blind_retry(self) -> None:
        source = Path("plugins/commerce/woocommerce/plugin.py").read_text(encoding="utf-8")
        for forbidden in ["requests.", "httpx.", "shell=True", "os.system", "subprocess", "publish("]:
            self.assertNotIn(forbidden, source)
        self.assertNotIn("retry", source.lower())
        with WooFixtureServer() as server:
            plugin = woo_plugin(server.url)
            payload = json.dumps(plugin.health_check())
            self.assertNotIn("ck_test_key", payload)
            self.assertNotIn("cs_test_secret", payload)

    def test_no_invented_discount_or_payment_mutation_in_cta_context(self) -> None:
        with WooFixtureServer() as server:
            plugin = woo_plugin(server.url)
            plugin.sync_products()
            sabr = plugin.search("sabr")[0]
            context = plugin.commercial_cta_context(sabr)
            self.assertTrue(context["no_discount_claim"])
            self.assertNotIn("sale_price", json.dumps(context).lower())
