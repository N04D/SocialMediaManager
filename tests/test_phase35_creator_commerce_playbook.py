from __future__ import annotations

import unittest

from plugins.playbooks.creator_commerce import CreatorCommerceRepurposePlaybook
from tests.phase35_support import Phase35TestMixin


class Phase35CreatorCommercePlaybookTests(Phase35TestMixin, unittest.TestCase):
    def test_required_optional_intent_policies_and_success_metrics(self) -> None:
        playbook = CreatorCommerceRepurposePlaybook(runtime=self.harness.runtime, content_service=self.harness.content)
        resolved = playbook.resolve_capabilities()
        self.assertEqual(resolved["source.video"], "source.youtube")
        self.assertEqual(resolved["transformation.clip_candidates"], "plugin.video_repurpose")
        self.assertEqual(resolved["commerce.product_catalog"], "commerce.catalog")
        self.assertEqual(playbook.playbook.intent_id, "educate")
        self.assertIn("purchase", playbook.playbook.success_metrics)
        policy_text = " ".join(policy.description for policy in playbook.policies)
        self.assertIn("Never invent discounts", policy_text)
        self.assertIn("Do not publish automatically", policy_text)

    def test_sabr_scenario_selects_product_and_outputs_variants(self) -> None:
        result = self.harness.run_sabr()
        self.assertEqual(len(result["candidates"]), 3)
        self.assertEqual(result["product"].product_id, "sabr-tshirt")
        self.assertEqual(result["social_variant"].asset_type, "variant.social_text")
        self.assertEqual(result["article_variant"].asset_type, "variant.article")
        self.assertEqual(result["cta_variant"].asset_type, "variant.commercial_cta")
        self.assertEqual(result["short_video"]["status"], "rendering capability not configured")
        self.assertEqual(result["campaign"].metadata["secondary_intent"], "sell_product")
