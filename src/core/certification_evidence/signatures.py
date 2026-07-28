"""Signature envelope helpers.

The v0.1 production path is safe when signing is not configured. Tests may use a
deterministic fake signer for integrity-flow coverage; no signing key material is
stored in evidence, persistence, CLI output, support bundles, or source.
"""

from __future__ import annotations

import hmac

from .canonical import canonical_json_bytes
from .errors import CertificationEvidenceError
from .models import CertificationSignatureEnvelope, stable_checksum, utc_now_iso
from .signers import get_signer


def unsigned_envelope(payload: object) -> CertificationSignatureEnvelope:
    checksum = stable_checksum(canonical_json_bytes(payload).decode("utf-8"))
    return CertificationSignatureEnvelope(
        signature_version="1.0",
        signer_reference_id="signer.none",
        algorithm_identifier="not_configured",
        signed_payload_checksum=checksum,
        signature="",
        public_key_fingerprint="",
        signed_at="",
        signature_status="not_configured",
    )


def sign_payload(payload: object, signer_reference_id: str) -> CertificationSignatureEnvelope:
    signer = get_signer(signer_reference_id)
    if not signer.enabled or signer.revoked_at:
        raise CertificationEvidenceError("certification.signer_unavailable", "Signer is disabled or revoked.")
    if signer.signer_type != "deterministic_hmac_test_only":
        return unsigned_envelope(payload)
    canonical = canonical_json_bytes(payload)
    signature = hmac.digest(_fake_signing_material(signer.public_key_reference), canonical, "sha256").hex()
    return CertificationSignatureEnvelope(
        signature_version="1.0",
        signer_reference_id=signer.id,
        algorithm_identifier="hmac-sha256-test-only",
        signed_payload_checksum=stable_checksum(canonical.decode("utf-8")),
        signature=signature,
        public_key_fingerprint=stable_checksum(signer.public_key_reference)[:32],
        signed_at=utc_now_iso(),
        signature_status="signed",
    )


def verify_signature(payload: object, envelope: CertificationSignatureEnvelope) -> str:
    if envelope.signature_status == "not_configured" or envelope.signer_reference_id == "signer.none":
        return "not_configured"
    signer = get_signer(envelope.signer_reference_id)
    if signer.revoked_at:
        return "revoked"
    if signer.signer_type != "deterministic_hmac_test_only":
        return "untrusted"
    canonical = canonical_json_bytes(payload)
    expected = hmac.digest(_fake_signing_material(signer.public_key_reference), canonical, "sha256").hex()
    checksum = stable_checksum(canonical.decode("utf-8"))
    if envelope.signed_payload_checksum != checksum:
        return "payload_mismatch"
    return "valid" if hmac.compare_digest(expected, envelope.signature) else "invalid"


def _fake_signing_material(public_key_reference: str) -> bytes:
    return f"fake-signer:{public_key_reference}".encode()


__all__ = ["sign_payload", "unsigned_envelope", "verify_signature"]
