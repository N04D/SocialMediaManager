from __future__ import annotations

import unittest

from tests.phase35_support import Phase35Harness


class Phase39CommerceCapabilitiesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase35Harness()
        self.addCleanup(self.harness.close)

    def test_registry_discovers_fixture_and_woocommerce_catalog_producers(self) -> None:
        registry = self.harness.runtime.registry
        providers = [provider.id for provider in registry.providers_for("commerce.product_catalog")]
        self.assertIn("commerce.catalog", providers)
        self.assertIn("commerce.woocommerce", providers)
        entity_providers = [provider.id for provider in registry.providers_for("entity.product")]
        self.assertIn("commerce.woocommerce", entity_providers)
