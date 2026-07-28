"""Host-owned signer references for certification evidence."""

from __future__ import annotations

from .models import CertificationSignerReference, utc_now_iso


def deterministic_test_signer() -> CertificationSignerReference:
    now = utc_now_iso()
    return CertificationSignerReference(
        id="signer.local.deterministic-test",
        display_name="Deterministic local test signer",
        signer_type="deterministic_hmac_test_only",
        public_key_reference="fingerprint:deterministic-test",
        private_key_secret_reference="secretref:certification/test-signer",
        allowed_evidence_types=(
            "deterministic_staging_certification",
            "browser_certification",
            "worker_certification",
            "instrumentation_certification",
            "owned_publication_release_readiness",
        ),
        allowed_source_types=("local", "ci", "staging"),
        trust_scope="workspace",
        enabled=True,
        revoked_at="",
        created_at=now,
        updated_at=now,
    )


def unsigned_signer() -> CertificationSignerReference:
    now = utc_now_iso()
    return CertificationSignerReference(
        id="signer.none",
        display_name="Unsigned evidence",
        signer_type="not_configured",
        public_key_reference="",
        private_key_secret_reference="",
        allowed_evidence_types=(),
        allowed_source_types=(),
        trust_scope="none",
        enabled=True,
        revoked_at="",
        created_at=now,
        updated_at=now,
    )


def default_signers() -> tuple[CertificationSignerReference, ...]:
    return (deterministic_test_signer(), unsigned_signer())


def get_signer(signer_id: str) -> CertificationSignerReference:
    for signer in default_signers():
        if signer.id == signer_id:
            return signer
    raise KeyError(signer_id)


__all__ = ["default_signers", "deterministic_test_signer", "get_signer", "unsigned_signer"]
