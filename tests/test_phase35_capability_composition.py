from __future__ import annotations

import unittest

from tests.phase35_support import Phase35TestMixin


class Phase35CapabilityCompositionTests(Phase35TestMixin, unittest.TestCase):
    def test_registry_discovers_plugins_by_capability(self) -> None:
        registry = self.harness.runtime.registry
        self.assertEqual(registry.providers_for("source.video")[0].id, "source.youtube")
        self.assertEqual(registry.providers_for("source.transcript")[0].id, "source.youtube")
        self.assertEqual(registry.providers_for("transformation.clip_candidates")[0].id, "plugin.video_repurpose")
        self.assertEqual(registry.providers_for("variant.social_text")[0].id, "plugin.video_repurpose")
        self.assertEqual(registry.providers_for("commerce.product_catalog")[0].id, "commerce.catalog")
        self.assertEqual(registry.providers_for("entity.product")[0].id, "commerce.catalog")

    def test_playbook_resolution_never_names_services_directly(self) -> None:
        resolved = self.harness.playbook().resolve_capabilities()
        self.assertEqual(resolved["source.video"], "source.youtube")
        self.assertEqual(resolved["variant.social_text"], "plugin.video_repurpose")
        self.assertEqual(resolved["commerce.product_catalog"], "commerce.catalog")
        self.assertIn("channel.linkedin", resolved)
        self.assertIn("channel.mastodon", resolved)
