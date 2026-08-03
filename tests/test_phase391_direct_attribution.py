import unittest

from plugins.commerce.attribution import attribute_order


class Phase391DirectAttributionTests(unittest.TestCase):
    def test_matching_click_id_is_direct_and_mismatch_is_not(self):
        direct = attribute_order(
            order_id="o",
            product_id="p",
            metadata={"attribution_id": "click-1"},
            click_bindings={"click-1": {"product_id": "p", "variant_id": "v"}},
        )
        unknown = attribute_order(
            order_id="o",
            product_id="p",
            metadata={"attribution_id": "click-2"},
            click_bindings={"click-1": {"product_id": "p"}},
        )
        self.assertEqual(direct.confidence, "direct")
        self.assertEqual(unknown.confidence, "unknown")


if __name__ == "__main__":
    unittest.main()
