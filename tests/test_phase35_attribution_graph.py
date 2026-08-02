from __future__ import annotations

import unittest

from tests.phase35_support import Phase35TestMixin


class Phase35AttributionGraphTests(Phase35TestMixin, unittest.TestCase):
    def test_forward_attribution_chain(self) -> None:
        result = self.harness.run_sabr()
        relationships = result["agent_context"]["relationships"]
        rels = {(rel["from_entity_id"], rel["relationship_type"], rel["to_entity_id"]) for rel in relationships}
        source_id = result["source"]["entity"].id
        transcript_id = f"entity.transcript.{result['source']['entity'].external_ref}"
        self.assertIn((source_id, "transcribed_to", transcript_id), rels)
        self.assertIn((source_id, "semantically_related_to", "entity.product.sabr-tshirt"), rels)
        self.assertIn(result["product_for_variant"], {"entity.product.sabr-tshirt"})

    def test_reverse_queries_for_outcome_product_and_transformation(self) -> None:
        result = self.harness.run_sabr()
        self.assertEqual(result["reverse_purchase_source"], result["source"]["entity"].id)
        self.assertEqual(result["product_for_variant"], "entity.product.sabr-tshirt")
        self.assertTrue(result["transformations_for_variant"][0].startswith("transformation_run_"))

    def test_outcomes_preserve_false_zero_semantics(self) -> None:
        outcomes = {outcome.id: outcome for outcome in self.harness.run_sabr()["outcomes"]}
        self.assertEqual(outcomes["outcome.social_view.sabr"].value, 1000)
        self.assertEqual(outcomes["outcome.product_click.sabr"].value, 25)
        self.assertEqual(outcomes["outcome.purchase.sabr"].value, 3)
