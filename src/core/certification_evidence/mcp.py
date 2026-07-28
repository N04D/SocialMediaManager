"""MCP-style query surface for certification evidence."""

from __future__ import annotations

from .service import CertificationEvidenceService


class CertificationEvidenceMCP:
    def __init__(self, service: CertificationEvidenceService | None = None) -> None:
        self.service = service or CertificationEvidenceService()

    def get_certification_evidence(self) -> dict:
        return self.service.list_evidence()

    def verify_certification_evidence(self, evidence_id: str) -> dict:
        return self.service.verify(evidence_id)

    def compare_certification_evidence(self, left_id: str, right_id: str) -> dict:
        return self.service.compare(left_id, right_id)

    def get_certification_freshness(self, evidence_id: str) -> dict:
        return self.service.freshness(evidence_id)

    def get_certification_trust_status(self, evidence_id: str) -> dict:
        evidence = self.service.get_evidence(evidence_id)["evidence"]
        return {
            "evidence_id": evidence_id,
            "trust_status": evidence["trust_status"],
            "signature_status": evidence["signature_status"],
        }

    def get_certification_reviews(self, evidence_id: str) -> dict:
        return self.service.reviews(evidence_id)

    def explain_readiness_evidence(self) -> dict:
        return self.service.readiness()

    def explain_ci_certification_status(self) -> dict:
        return self.service.remote_ci_status()

    def explain_staging_evidence_difference(self, left_id: str, right_id: str) -> dict:
        return self.service.compare(left_id, right_id)


__all__ = ["CertificationEvidenceMCP"]
