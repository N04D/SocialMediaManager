import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.core.certification_evidence.freshness import default_freshness_policy, freshness_status
from src.core.certification_evidence.models import CertificationProvenance
from src.core.certification_evidence.provenance import build_local_provenance, local_commit_sha
from src.core.certification_evidence.service import CertificationEvidenceService


class CertificationEvidenceFreshnessPhase28Tests(unittest.TestCase):
    def test_freshness_warning_stale_and_import_does_not_refresh(self) -> None:
        provenance = build_local_provenance(source_type="local")
        policy = default_freshness_policy()
        self.assertEqual(
            freshness_status(
                provenance=provenance,
                policy=policy,
                current_commit=local_commit_sha(),
                current_framework_version="phase28",
                now=provenance.generated_at,
            ),
            "fresh",
        )
        old = replace(provenance, generated_at="2020-01-01T00:00:00Z")
        self.assertEqual(
            freshness_status(
                provenance=old,
                policy=policy,
                current_commit=local_commit_sha(),
                current_framework_version="phase28",
                now=provenance.generated_at,
            ),
            "stale",
        )
        with tempfile.TemporaryDirectory() as tmp:
            service = CertificationEvidenceService(database_path=Path(tmp) / "cert.sqlite")
            created = service.generate_deterministic_evidence()
            self.assertTrue(service.freshness(created["evidence"]["package_id"])["import_does_not_refresh"])

    def test_commit_mismatch_is_stale(self) -> None:
        provenance = CertificationProvenance(
            **(build_local_provenance(source_type="local").__dict__ | {"commit_sha": "0" * 40})
        )
        self.assertEqual(
            freshness_status(
                provenance=provenance,
                policy=default_freshness_policy(),
                current_commit=local_commit_sha(),
                current_framework_version="phase28",
                now=provenance.generated_at,
            ),
            "stale",
        )


if __name__ == "__main__":
    unittest.main()
