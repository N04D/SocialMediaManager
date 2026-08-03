from __future__ import annotations

import unittest

from tests.phase35_support import Phase35Harness
from tests.phase39_support import WooFixtureServer, bootstrap_with_woocommerce_first, woo_plugin


class Phase39MultipleProducersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase35Harness()
        self.addCleanup(self.harness.close)

    def test_fixture_and_woocommerce_are_interchangeable_by_registry_selection(self) -> None:
        fixture_result = self.harness.run_sabr()
        self.assertEqual(fixture_result["resolved_capabilities"]["commerce.product_catalog"], "commerce.catalog")
        self.assertEqual(fixture_result["product"].title, "Sabr T-shirt")
        with WooFixtureServer() as server:
            service = woo_plugin(server.url)
            service.sync_products()
            runtime = bootstrap_with_woocommerce_first(self.harness.config, service)
            providers = [provider.id for provider in runtime.registry.providers_for("commerce.product_catalog")]
            self.assertEqual(providers[0], "commerce.woocommerce")
            self.assertIn("commerce.catalog", providers)

    def test_future_shopify_can_implement_same_generic_capabilities(self) -> None:
        required = {"entity.product", "commerce.product_catalog", "commerce.product_lookup", "commerce.product_media"}
        self.assertTrue(required.issubset(set(woo_plugin("http://127.0.0.1:9").capabilities)))
