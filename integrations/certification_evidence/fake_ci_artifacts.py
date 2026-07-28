"""Synthetic CI artifact helpers."""

from __future__ import annotations

from src.core.certification_evidence.service import CertificationEvidenceService


def generate_signed_ci_artifact(service: CertificationEvidenceService, *, commit_sha: str) -> bytes:
    payload = service.generate_deterministic_evidence(signer_reference_id="signer.local.deterministic-test")
    evidence_id = payload["evidence"]["package_id"]
    return service.export_evidence(evidence_id)["data"]
