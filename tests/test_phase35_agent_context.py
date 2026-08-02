from __future__ import annotations

import unittest

from tests.phase35_support import Phase35TestMixin


class Phase35AgentContextTests(Phase35TestMixin, unittest.TestCase):
    def test_context_contains_source_transformations_variants_product_outcomes_and_playbook(self) -> None:
        context = self.harness.run_sabr()["agent_context"]
        entities = {entity["id"]: entity for entity in context["entities"]}
        self.assertIn("entity.youtube.video.sabr1234567", entities)
        self.assertIn("entity.product.sabr-tshirt", entities)
        self.assertTrue(any(entity["entity_type"] == "variant.social_text" for entity in entities.values()))
        self.assertTrue(
            any(run["transformation_id"] == "transformation.video_repurpose.sabr" for run in context["transformations"])
        )
        self.assertTrue(any(outcome["outcome_type"] == "purchase" for outcome in context["outcomes"]))
        self.assertTrue(
            any(playbook["id"] == "playbook.creator_commerce_repurpose" for playbook in context["playbooks"])
        )
        self.assertTrue(any(rel["relationship_type"] == "promotes" for rel in context["relationships"]))

    def test_context_is_platform_neutral_for_agent_reasoning(self) -> None:
        context = self.harness.run_sabr()["agent_context"]
        joined = str(context)
        self.assertIn("primary_source", joined)
        self.assertIn("canonical", joined)
        self.assertIn("commerce.product_catalog", joined)
        self.assertNotIn("Shopify", joined)
