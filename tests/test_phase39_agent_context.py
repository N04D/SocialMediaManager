from __future__ import annotations

import unittest

from plugins.playbooks.creator_commerce import CreatorCommerceRepurposePlaybook
from tests.phase35_support import Phase35Harness
from tests.phase39_support import WooFixtureServer, bootstrap_with_woocommerce_first, woo_plugin


class Phase39AgentContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase35Harness()
        self.addCleanup(self.harness.close)

    def test_agent_context_contains_woocommerce_product_and_reverse_provenance(self) -> None:
        with WooFixtureServer() as server:
            service = woo_plugin(server.url)
            service.sync_products()
            runtime = bootstrap_with_woocommerce_first(self.harness.config, service)
            content = runtime.content_service(self.harness.config)
            result = CreatorCommerceRepurposePlaybook(runtime=runtime, content_service=content).run_sabr_scenario(
                workspace_id="phase39-agent"
            )
            context = result["agent_context"]
            product = next(entity for entity in context["entities"] if entity["title"] == "Sabr T-shirt")
            self.assertEqual(product["source_plugin"], "commerce.woocommerce")
            self.assertEqual(product["metadata"]["availability"], "in_stock")
            self.assertEqual(product["metadata"]["price"], 29.0)
            self.assertEqual(product["metadata"]["currency"], "EUR")
            self.assertEqual(
                product["metadata"]["metadata"]["woocommerce"]["external_ref"],
                "woocommerce:fixture-store:101",
            )
            self.assertEqual(product["metadata"]["catalog_sync"]["status"], "succeeded")
            self.assertEqual(result["product_for_variant"], f"entity.product.{result['product'].product_id}")
