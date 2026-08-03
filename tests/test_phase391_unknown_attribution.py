import unittest

from plugins.commerce.attribution import attribute_order


class Phase391UnknownAttributionTests(unittest.TestCase):
    def test_product_alone_does_not_prove_attribution(self):
        decision = attribute_order(order_id="o", product_id="p", metadata={})
        self.assertEqual(decision.confidence, "unknown")
        self.assertNotEqual(decision.confidence, "direct")


if __name__ == "__main__":
    unittest.main()
