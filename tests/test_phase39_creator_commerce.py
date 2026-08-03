from __future__ import annotations

import unittest

from plugins.playbooks.creator_commerce import CreatorCommerceRepurposePlaybook
from tests.phase35_support import Phase35Harness
from tests.phase39_support import WooFixtureServer, bootstrap_with_woocommerce_first, woo_plugin


class Phase39CreatorCommerceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase35Harness()
        self.addCleanup(self.harness.close)

    def test_creator_commerce_playbook_uses_woocommerce_without_code_changes(self) -> None:
        with WooFixtureServer() as server:
            service = woo_plugin(server.url)
            service.sync_products()
            runtime = bootstrap_with_woocommerce_first(self.harness.config, service)
            content = runtime.content_service(self.harness.config)
            playbook = CreatorCommerceRepurposePlaybook(runtime=runtime, content_service=content)
            resolved = playbook.resolve_capabilities()
            self.assertEqual(resolved["commerce.product_catalog"], "commerce.woocommerce")
            result = playbook.run_sabr_scenario(workspace_id="phase39-creator-commerce")
            self.assertEqual(result["product"].title, "Sabr T-shirt")
            self.assertEqual(result["product"].availability, "in_stock")
            self.assertNotEqual(result["product"].title, "Sabr hoodie")
            self.assertEqual(result["cta_variant"].metadata["no_discount_claim"], True)
            relationships = result["agent_context"]["relationships"]
            product_relationship = next(
                item for item in relationships if item["relationship_type"] == "semantically_related_to"
            )
            self.assertIn("entity.product.woocommerce.fixture-store.101", product_relationship["to_entity_id"])
