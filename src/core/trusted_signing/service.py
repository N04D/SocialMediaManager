"""Host-owned signer lifecycle and Ed25519 signing service."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Protocol

from src.core.certification_evidence.canonical import canonical_json_bytes
from src.core.certification_evidence.models import CertificationSignatureEnvelope, stable_checksum, utc_now_iso

from .algorithms import (
    ed25519_available,
    fingerprint_public_key,
    public_key_from_private_pem,
    sign_ed25519,
    validate_key_pair,
    verify_ed25519,
)
from .contracts import TRUSTED_SIGNER_FRAMEWORK_VERSION
from .errors import TrustedSigningError
from .models import (
    SignerApproval,
    SignerAuditEvent,
    SignerHealthReport,
    SignerRotationRecord,
    TrustedSignerReference,
    signer_record,
)
from .persistence import TrustedSignerRepository


class SecretReader(Protocol):
    def get_secret(self, secret_reference: str) -> str: ...


class HostCertificationSigner:
    def __init__(self, signer: TrustedSignerReference, secret_reader: SecretReader) -> None:
        self.signer = signer
        self.secret_reader = secret_reader

    @property
    def signer_reference_id(self) -> str:
        return self.signer.id

    @property
    def algorithm(self) -> str:
        return self.signer.algorithm_identifier

    def get_public_key(self) -> str:
        return self.signer.public_key

    def get_public_key_fingerprint(self) -> str:
        return self.signer.public_key_fingerprint

    def validate_key_pair(self) -> bool:
        private_key = self.secret_reader.get_secret(self.signer.private_key_secret_reference)
        return validate_key_pair(private_key, self.signer.public_key)

    def health_check(self) -> SignerHealthReport:
        if self.signer.revoked_at:
            return SignerHealthReport(
                signer_id=self.signer.id,
                status="invalid",
                secret_reference_exists=bool(self.signer.private_key_secret_reference),
                secret_readable=False,
                key_format_valid=False,
                key_pair_valid=False,
                algorithm_allowed=self.signer.algorithm_identifier == "Ed25519",
                fingerprint_matches=False,
                approval_valid=bool(self.signer.approved_by),
                sign_verify_probe=False,
                safe_error_code="signer.revoked",
                checked_at=utc_now_iso(),
            )
        try:
            secret = self.secret_reader.get_secret(self.signer.private_key_secret_reference)
            public_key = public_key_from_private_pem(secret)
            fingerprint = fingerprint_public_key(public_key)
            pair_valid = validate_key_pair(secret, self.signer.public_key)
            healthy = (
                self.signer.status == "active"
                and self.signer.approved_by
                and self.signer.revoked_at == ""
                and pair_valid
                and fingerprint == self.signer.public_key_fingerprint
            )
            return SignerHealthReport(
                signer_id=self.signer.id,
                status="healthy" if healthy else "degraded",
                secret_reference_exists=True,
                secret_readable=True,
                key_format_valid=True,
                key_pair_valid=pair_valid,
                algorithm_allowed=self.signer.algorithm_identifier == "Ed25519",
                fingerprint_matches=fingerprint == self.signer.public_key_fingerprint,
                approval_valid=bool(self.signer.approved_by),
                sign_verify_probe=pair_valid,
                safe_error_code="" if healthy else "signer.health.degraded",
                checked_at=utc_now_iso(),
            )
        except Exception:
            return SignerHealthReport(
                signer_id=self.signer.id,
                status="invalid",
                secret_reference_exists=bool(self.signer.private_key_secret_reference),
                secret_readable=False,
                key_format_valid=False,
                key_pair_valid=False,
                algorithm_allowed=self.signer.algorithm_identifier == "Ed25519",
                fingerprint_matches=False,
                approval_valid=bool(self.signer.approved_by),
                sign_verify_probe=False,
                safe_error_code="signer.health.key_unavailable",
                checked_at=utc_now_iso(),
            )

    def sign(self, payload: object, *, evidence_type: str, source_type: str) -> CertificationSignatureEnvelope:
        if self.signer.status != "active" or not self.signer.approved_by:
            raise TrustedSigningError("signer.not_active", "Signer is not approved and active.")
        if (
            evidence_type not in self.signer.allowed_evidence_types
            or source_type not in self.signer.allowed_source_types
        ):
            raise TrustedSigningError("signer.policy", "Signer is not allowed for this evidence payload.")
        private_key = self.secret_reader.get_secret(self.signer.private_key_secret_reference)
        canonical = canonical_json_bytes(payload)
        signature = sign_ed25519(private_key, canonical)
        if not verify_ed25519(self.signer.public_key, canonical, signature):
            raise TrustedSigningError("signer.verify_failed", "Signer probe verification failed.")
        return CertificationSignatureEnvelope(
            signature_version="1.0",
            signer_reference_id=self.signer.id,
            algorithm_identifier="Ed25519",
            signed_payload_checksum=stable_checksum(canonical.decode("utf-8")),
            signature=signature,
            public_key_fingerprint=self.signer.public_key_fingerprint,
            signed_at=utc_now_iso(),
            signature_status="signed",
        )


class TrustedSignerService:
    def __init__(self, *, database_path: Path | None = None, secret_reader: SecretReader | None = None) -> None:
        self.repository = TrustedSignerRepository(database_path)
        self.secret_reader = secret_reader

    def status(self) -> dict[str, object]:
        return {
            "framework_version": TRUSTED_SIGNER_FRAMEWORK_VERSION,
            "cryptographic_library": "cryptography" if ed25519_available() else "not_configured",
            "production_signing_status": "available" if ed25519_available() else "not_configured",
            "algorithm": "Ed25519",
            "signers": self.repository.list_signers(),
        }

    def enroll(
        self,
        *,
        signer_id: str,
        display_name: str,
        private_key_secret_reference: str,
        operator_id: str = "operator-a",
    ) -> dict[str, object]:
        if not private_key_secret_reference.startswith("secretref:"):
            raise TrustedSigningError("signer.secret_reference", "Signer enrollment requires a secret reference.")
        secret = self._secret(private_key_secret_reference)
        public_key = public_key_from_private_pem(secret)
        fingerprint = fingerprint_public_key(public_key)
        if not validate_key_pair(secret, public_key):
            raise TrustedSigningError("signer.invalid_key_pair", "Signer key pair validation failed.")
        signer = signer_record(
            signer_id=signer_id,
            display_name=display_name,
            secret_reference=private_key_secret_reference,
            public_key=public_key,
            fingerprint=fingerprint,
        )
        self.repository.save_signer(signer)
        self._audit("signer.registered", signer.id, operator_id, "signer enrolled pending approval")
        return {"signer": self._public(signer), "status": "pending_approval"}

    def approve(self, signer_id: str, *, reviewer_id: str, requester_id: str = "operator-a") -> dict[str, object]:
        if reviewer_id == requester_id:
            raise TrustedSigningError("signer.self_approval", "Independent signer approval is required.")
        signer = self._signer(signer_id)
        approval = SignerApproval(
            id="signer-approval-" + stable_checksum({"signer_id": signer_id, "reviewer_id": reviewer_id})[:16],
            signer_id=signer_id,
            reviewer_id=reviewer_id,
            decision="approved",
            approved_at=utc_now_iso(),
        )
        self.repository.save_approval(approval)
        updated = replace(signer, status="pending_approval", approved_by=reviewer_id, approved_at=approval.approved_at)
        self.repository.save_signer(updated)
        self._audit("signer.approved", signer_id, reviewer_id, "signer approved")
        return {"approval": approval.__dict__, "signer": self._public(updated)}

    def activate(self, signer_id: str, *, actor: str = "operator-b") -> dict[str, object]:
        signer = self._signer(signer_id)
        if not signer.approved_by:
            raise TrustedSigningError("signer.approval_required", "Signer approval is required before activation.")
        health = self.health(signer_id)["health"]
        if not health["key_pair_valid"] or not health["fingerprint_matches"]:
            raise TrustedSigningError("signer.health", "Signer health blocks activation.")
        updated = replace(signer, status="active", activated_at=utc_now_iso(), updated_at=utc_now_iso())
        self.repository.save_signer(updated)
        self._audit("signer.activated", signer_id, actor, "signer activated")
        return {"signer": self._public(updated)}

    def health(self, signer_id: str) -> dict[str, object]:
        signer = self._signer(signer_id)
        report = HostCertificationSigner(signer, self._reader()).health_check()
        if report.status != "healthy" and signer.status == "active":
            self.repository.save_signer(replace(signer, status="degraded", updated_at=utc_now_iso()))
        return {"health": self.repository.save_health(report)}

    def test_sign(self, signer_id: str) -> dict[str, object]:
        signer = self._signer(signer_id)
        envelope = HostCertificationSigner(signer, self._reader()).sign(
            {"schema_version": "1.0", "probe": "trusted-signer"},
            evidence_type="deterministic_staging_certification",
            source_type="local",
        )
        self._audit("signer.test_signed", signer_id, "operator", "test payload signed and verified")
        return {
            "signature_status": "valid",
            "algorithm": envelope.algorithm_identifier,
            "public_key_fingerprint": envelope.public_key_fingerprint,
        }

    def sign_payload(
        self, signer_id: str, payload: object, *, evidence_type: str, source_type: str
    ) -> CertificationSignatureEnvelope:
        signer = self._signer(signer_id)
        return HostCertificationSigner(signer, self._reader()).sign(
            payload, evidence_type=evidence_type, source_type=source_type
        )

    def verify_payload(self, signer_id: str, payload: object, envelope: CertificationSignatureEnvelope) -> str:
        signer = self._signer(signer_id)
        if signer.revoked_at and signer.revocation_reason == "key_compromise":
            return "revoked"
        canonical = canonical_json_bytes(payload)
        if stable_checksum(canonical.decode("utf-8")) != envelope.signed_payload_checksum:
            return "payload_mismatch"
        return "valid" if verify_ed25519(signer.public_key, canonical, envelope.signature) else "invalid"

    def rotate(
        self,
        old_signer_id: str,
        *,
        new_signer_id: str,
        new_secret_reference: str,
        actor: str = "operator-b",
    ) -> dict[str, object]:
        old = self._signer(old_signer_id)
        enrolled = self.enroll(
            signer_id=new_signer_id,
            display_name=f"{old.display_name} rotation",
            private_key_secret_reference=new_secret_reference,
            operator_id=actor,
        )
        new = self._signer(new_signer_id)
        self.repository.save_signer(replace(new, rotated_from_signer_id=old_signer_id, updated_at=utc_now_iso()))
        self.repository.save_signer(replace(old, status="rotated", updated_at=utc_now_iso()))
        record = SignerRotationRecord(
            id="signer-rotation-" + stable_checksum({"old": old_signer_id, "new": new_signer_id})[:16],
            old_signer_id=old_signer_id,
            new_signer_id=new_signer_id,
            reason="operator_rotation",
            rotated_at=utc_now_iso(),
            actor=actor,
        )
        self.repository.save_rotation(record)
        self._audit("signer.rotated", old_signer_id, actor, f"replacement {new_signer_id} enrolled")
        return {"rotation": record.__dict__, "new_signer": enrolled["signer"]}

    def revoke(self, signer_id: str, *, reason: str, actor: str = "operator-b") -> dict[str, object]:
        if reason not in {"key_compromise", "administrative_retirement", "configuration_error", "unknown"}:
            raise TrustedSigningError("signer.revocation_reason", "Signer revocation reason is invalid.")
        signer = self._signer(signer_id)
        updated = replace(
            signer,
            status="revoked",
            revoked_at=utc_now_iso(),
            revocation_reason=reason,
            updated_at=utc_now_iso(),
        )
        self.repository.save_signer(updated)
        self._audit("signer.revoked", signer_id, actor, reason)
        return {"signer": self._public(updated)}

    def _signer(self, signer_id: str) -> TrustedSignerReference:
        return TrustedSignerReference(**self.repository.get_signer(signer_id))

    def _reader(self) -> SecretReader:
        if self.secret_reader is None:
            raise TrustedSigningError("signer.secret_reader", "No host-owned secret reader is configured.")
        return self.secret_reader

    def _secret(self, reference: str) -> str:
        return self._reader().get_secret(reference)

    def _audit(self, action: str, signer_id: str, actor: str, summary: str) -> None:
        self.repository.audit(
            SignerAuditEvent(
                id="signer-audit-"
                + stable_checksum({"action": action, "signer_id": signer_id, "at": utc_now_iso()})[:20],
                action=action,
                signer_id=signer_id,
                actor=actor,
                safe_summary=summary,
                occurred_at=utc_now_iso(),
            )
        )

    def _public(self, signer: TrustedSignerReference) -> dict[str, object]:
        payload = signer.__dict__.copy()
        payload.pop("private_key_secret_reference", None)
        payload["secret_reference_status"] = "present" if signer.private_key_secret_reference else "missing"
        return payload


__all__ = ["HostCertificationSigner", "SecretReader", "TrustedSignerService"]
