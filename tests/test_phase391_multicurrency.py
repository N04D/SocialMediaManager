import unittest

from plugins.commerce.attribution import aggregate_revenue


class Phase391MultiCurrencyTests(unittest.TestCase):
    def test_currencies_are_not_combined(self):
        result = aggregate_revenue(
            [
                {"value": 29, "currency": "EUR", "metadata": {"attribution_confidence": "direct"}},
                {"value": 31, "currency": "USD", "metadata": {"attribution_confidence": "strong"}},
            ]
        )
        self.assertEqual(set(result), {"EUR", "USD"})
        self.assertNotIn("total", result)


if __name__ == "__main__":
    unittest.main()
