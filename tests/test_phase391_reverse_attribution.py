import unittest

from plugins.commerce.attribution import attribute_order


class Phase391ReverseAttributionTests(unittest.TestCase):
    def test_direct_evidence_retains_variant_and_campaign_references(self):
        decision = attribute_order(
            order_id="order-1",
            product_id="product-1",
            metadata={"attribution_id": "click-1"},
            click_bindings={
                "click-1": {"product_id": "product-1", "variant_id": "variant-1", "campaign_id": "campaign-1"}
            },
        )
        self.assertEqual(decision.variant_id, "variant-1")
        self.assertEqual(decision.campaign_id, "campaign-1")
        self.assertEqual(decision.evidence[0].reference, "click-1")


if __name__ == "__main__":
    unittest.main()
