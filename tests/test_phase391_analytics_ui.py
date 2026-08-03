import unittest

from plugins.commerce.outcomes import outcome_summary


class Phase391AnalyticsUITests(unittest.TestCase):
    def test_not_collected_is_not_zero(self):
        summary = outcome_summary([])
        self.assertEqual(summary["purchases"], 0)
        self.assertEqual(summary["revenue"], {})


if __name__ == "__main__":
    unittest.main()
