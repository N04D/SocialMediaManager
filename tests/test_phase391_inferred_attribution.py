import unittest

from plugins.commerce.attribution import attribute_order


class Phase391InferredAttributionTests(unittest.TestCase):
    def test_inference_is_explicit_and_never_upgraded(self):
        kwargs = {
            "order_id": "o",
            "product_id": "p",
            "metadata": {"campaign_id": "c"},
            "campaign_bindings": {"c": {"product_id": "p"}},
        }
        self.assertEqual(attribute_order(**kwargs).confidence, "unknown")
        self.assertEqual(attribute_order(**kwargs, allow_inferred=True).confidence, "inferred")


if __name__ == "__main__":
    unittest.main()
