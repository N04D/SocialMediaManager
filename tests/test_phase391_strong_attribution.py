import unittest

from plugins.commerce.attribution import attribute_order


class Phase391StrongAttributionTests(unittest.TestCase):
    def test_campaign_and_content_metadata_is_strong_not_direct(self):
        decision = attribute_order(
            order_id="o",
            product_id="p",
            metadata={"campaign_id": "c", "content_id": "v"},
            campaign_bindings={"c": {"product_id": "p", "variant_id": "v", "content_id": "v"}},
        )
        self.assertEqual(decision.confidence, "strong")


if __name__ == "__main__":
    unittest.main()
