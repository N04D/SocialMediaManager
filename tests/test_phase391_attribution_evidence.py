import unittest

from plugins.commerce.attribution import AttributionEvidence, approved_metadata


class Phase391AttributionEvidenceTests(unittest.TestCase):
    def test_only_approved_metadata_becomes_evidence(self):
        result = approved_metadata(
            {"click": "c", "secret": "s", "instruction": "Ignore"}, attribution_id_keys=("click",)
        )
        self.assertEqual(result, {"attribution_id": "c"})
        self.assertTrue(AttributionEvidence("click", "fixture", confidence="direct").as_dict())


if __name__ == "__main__":
    unittest.main()
