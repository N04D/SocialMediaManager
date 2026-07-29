"""Purpose-bound managed secret facade."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.core.certification_evidence.models import stable_checksum, utc_now_iso
from src.core.managed_secrets.backends import ManagedSecretBackend
from src.core.trusted_signing.algorithms import fingerprint_public_key, public_key_from_private_pem

from .approvals import OperatorAuthorizationService
from .contracts import MANAGED_SECRET_FRAMEWORK_VERSION
from .errors import ManagedSecretError
from .leases import SecretLeaseValue
from .models import (
    ManagedSecretAuditEvent,
    ManagedSecretHealthReport,
    ManagedSecretReference,
    ManagedSecretVersion,
    SecretLease,
    secret_reference_id,
)
from .persistence import ManagedSecretRepository
from .purposes import validate_purpose_allowed


class ManagedSecretFacade:
    def __init__(self, *, database_path: Path | None = None, backend: ManagedSecretBackend | None = None) -> None:
        self.repository = ManagedSecretRepository(database_path)
        self.backend = backend
        self.authz = OperatorAuthorizationService(self.repository)

    def status(self) -> dict[str, object]:
        health = self.vault_health()
        references = self.repository.list_references()
        return {
            "framework_version": MANAGED_SECRET_FRAMEWORK_VERSION,
            "managed_secrets_status": "configured" if self.backend else "not_configured",
            "references": [self._public_reference(item) for item in references],
            "vault_health": health,
        }

    def create_reference(
        self,
        *,
        secret_type: str,
        display_name: str,
        purpose_allowlist: tuple[str, ...],
        scope: str = "host",
        created_by: str = "operator",
        expires_at: str = "",
    ) -> dict[str, object]:
        self._validate_secret_type(secret_type)
        for purpose in purpose_allowlist:
            validate_purpose_allowed(purpose, purpose_allowlist)
        reference = ManagedSecretReference(
            id=secret_reference_id(secret_type, display_name),
            workspace_id_or_host_scope=scope,
            backend_id=self._backend().backend_id,
            secret_type=secret_type,
            display_name=display_name,
            purpose_allowlist=purpose_allowlist,
            current_version=0,
            status="pending_value",
            created_by=created_by,
            approved_by="",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
            rotated_at="",
            expires_at=expires_at,
            revoked_at="",
            safe_fingerprint="",
            version=1,
        )
        self.repository.save_reference(reference)
        self._audit("secret.reference_created", reference.id, 1, "", created_by, "success", "")
        return {"secret": self._public_reference(reference.__dict__)}

    def set_value(self, reference_id: str, value: bytes, *, actor: str = "operator") -> dict[str, object]:
        self._validate_secret_size(value)
        reference = self._reference(reference_id)
        version = int(reference["current_version"]) + 1
        backend_record = self._backend().create(
            reference_id=reference_id,
            secret_type=reference["secret_type"],
            scope=reference["workspace_id_or_host_scope"],
            version=version,
            value=value,
        )
        updated = self._save_new_version(reference, version, backend_record, "pending_validation")
        self._audit("secret.value_set", reference_id, version, "", actor, "success", "")
        return {"secret": self._public_reference(updated)}

    def generate_ed25519(self, reference_id: str, *, actor: str = "operator") -> dict[str, object]:
        reference = self._reference(reference_id)
        if reference["secret_type"] != "ed25519_private_key":
            raise ManagedSecretError("secret.generate_type", "Reference is not an Ed25519 private key.")
        version = int(reference["current_version"]) + 1
        backend_record = self._backend().generate(
            reference_id=reference_id,
            secret_type=reference["secret_type"],
            scope=reference["workspace_id_or_host_scope"],
            version=version,
        )
        updated = self._save_new_version(reference, version, backend_record, "pending_validation")
        self._audit("secret.generated", reference_id, version, "certification_signing", actor, "success", "")
        return {"secret": self._public_reference(updated)}

    def validate(self, reference_id: str, *, actor: str = "operator") -> dict[str, object]:
        reference = self._reference(reference_id)
        try:
            value = self._read_current(reference)
            fingerprint = _fingerprint_for_secret(reference["secret_type"], value)
            status = "pending_approval"
            updated = self._replace_reference(reference, status=status, safe_fingerprint=fingerprint)
            self._audit(
                "secret.validation_performed", reference_id, reference["current_version"], "", actor, "success", ""
            )
            return {"secret": self._public_reference(updated), "validation_status": "valid"}
        except Exception as exc:
            updated = self._replace_reference(reference, status="invalid")
            self._audit(
                "secret.validation_performed",
                reference_id,
                reference["current_version"],
                "",
                actor,
                "failed",
                getattr(exc, "code", "secret.validation_failed"),
            )
            return {"secret": self._public_reference(updated), "validation_status": "invalid"}

    def approve(
        self,
        reference_id: str,
        *,
        action_type: str = "approve_github_credential",
        requester_id: str = "operator-a",
        approver_id: str = "operator-b",
    ) -> dict[str, object]:
        reference = self._reference(reference_id)
        approval = self.authz.approve(
            reference=reference,
            action_type=action_type,
            requester_id=requester_id,
            approver_id=approver_id,
        )
        updated = self._replace_reference(reference, approved_by=approver_id, status="pending_approval")
        self._audit(
            "secret.approval_granted", reference_id, reference["current_version"], "", approver_id, "success", ""
        )
        return {"approval": approval, "secret": self._public_reference(updated)}

    def activate(
        self,
        reference_id: str,
        *,
        action_type: str = "approve_github_credential",
        actor: str = "operator-b",
    ) -> dict[str, object]:
        reference = self._reference(reference_id)
        if not self.authz.approval_satisfied(reference, action_type):
            raise ManagedSecretError("secret.approval_required", "Secret approval is required.")
        self._read_current(reference)
        updated = self._replace_reference(reference, status="active", updated_at=utc_now_iso())
        self._audit("secret.activated", reference_id, reference["current_version"], "", actor, "success", "")
        return {"secret": self._public_reference(updated)}

    def rotate(self, reference_id: str, value: bytes, *, actor: str = "operator") -> dict[str, object]:
        reference = self._reference(reference_id)
        old_version = int(reference["current_version"])
        updated = self.set_value(reference_id, value, actor=actor)["secret"]
        self._audit("secret.rotation_prepared", reference_id, old_version, "", actor, "success", "")
        return {"old_version": old_version, "secret": updated}

    def revoke(self, reference_id: str, *, reason: str, actor: str = "operator-b") -> dict[str, object]:
        reference = self._reference(reference_id)
        updated = self._replace_reference(
            reference, status="revoked", revoked_at=utc_now_iso(), updated_at=utc_now_iso()
        )
        self._backend().revoke(
            reference_id=reference_id,
            secret_type=reference["secret_type"],
            scope=reference["workspace_id_or_host_scope"],
            version=int(reference["current_version"]),
        )
        self._audit("secret.revoked", reference_id, reference["current_version"], "", actor, "success", reason)
        return {"secret": self._public_reference(updated)}

    def health(self, reference_id: str) -> dict[str, object]:
        reference = self._reference(reference_id)
        expired = _is_expired(reference.get("expires_at", ""))
        report = ManagedSecretHealthReport(
            secret_reference_id=reference_id,
            status="healthy" if reference["status"] == "active" and not expired else "degraded",
            backend_record_exists=bool(self._versions(reference_id)),
            active_value_present=int(reference["current_version"]) > 0,
            purpose_allowlist_valid=bool(reference["purpose_allowlist"]),
            approval_satisfied=bool(reference.get("approved_by")),
            expired=expired,
            revoked=bool(reference.get("revoked_at")),
            safe_error_code="" if reference["status"] == "active" and not expired else "secret.health.degraded",
            checked_at=utc_now_iso(),
        )
        return {"health": self.repository.save_health(report)}

    def vault_health(self) -> dict[str, object]:
        if self.backend is None:
            return {
                "backend_id": "not_configured",
                "ready": False,
                "safe_warnings": ("managed_secret_backend_not_configured",),
            }
        payload = self.backend.health_check()
        refs = self.repository.list_references()
        payload["active_secret_count"] = len([item for item in refs if item.get("status") == "active"])
        payload["degraded_secret_count"] = len([item for item in refs if item.get("status") in {"degraded", "invalid"}])
        payload["expired_secret_count"] = len([item for item in refs if _is_expired(item.get("expires_at", ""))])
        return payload

    def acquire(
        self,
        reference_id: str,
        purpose: str,
        *,
        consumer: str = "consumer",
        lease_seconds: int = 30,
    ) -> SecretLeaseValue:
        reference = self._reference(reference_id)
        validate_purpose_allowed(purpose, tuple(reference["purpose_allowlist"]))
        if reference["status"] != "active":
            self._audit(
                "secret.lease_denied",
                reference_id,
                reference["current_version"],
                purpose,
                consumer,
                "denied",
                "secret.not_active",
            )
            raise ManagedSecretError("secret.not_active", "Secret is not active.")
        if _is_expired(reference.get("expires_at", "")):
            raise ManagedSecretError("secret.expired", "Secret is expired.")
        value = self._read_current(reference)
        now = datetime.now(UTC)
        lease = SecretLease(
            lease_id="secret-lease-" + stable_checksum({"reference": reference_id, "at": utc_now_iso()})[:20],
            secret_reference_id=reference_id,
            secret_version=int(reference["current_version"]),
            purpose=purpose,
            consumer=consumer,
            acquired_at=now.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            expires_at=(now + timedelta(seconds=lease_seconds))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
        )
        self._audit(
            "secret.lease_acquired", reference_id, reference["current_version"], purpose, consumer, "success", ""
        )
        return SecretLeaseValue(lease=lease, value=bytearray(value), _release=self._release)

    def get_secret(
        self, secret_reference: str, purpose: str = "certification_signing", consumer: str = "legacy"
    ) -> str:
        with self.acquire(secret_reference, purpose, consumer=consumer) as lease:
            return lease.text()

    def support_bundle_summary(self) -> dict[str, object]:
        return {
            "framework_version": MANAGED_SECRET_FRAMEWORK_VERSION,
            "references": [self._public_reference(item) for item in self.repository.list_references()],
            "vault_health": self.vault_health(),
            "contains_secret_values": False,
            "contains_ciphertext": False,
        }

    def _save_new_version(self, reference: dict, secret_version: int, backend_record: dict, status: str) -> dict:
        version = ManagedSecretVersion(
            id=f"{reference['id']}:v{secret_version}",
            secret_reference_id=reference["id"],
            secret_version=secret_version,
            backend_id=reference["backend_id"],
            backend_record_reference=backend_record["backend_record_reference"],
            status=status,
            safe_fingerprint=backend_record.get("safe_fingerprint", ""),
            created_at=backend_record.get("created_at", utc_now_iso()),
            activated_at="",
            revoked_at="",
        )
        self.repository.save_version(version)
        return self._replace_reference(
            reference,
            current_version=secret_version,
            status=status,
            safe_fingerprint=version.safe_fingerprint,
            updated_at=utc_now_iso(),
            version=int(reference["version"]) + 1,
        )

    def _read_current(self, reference: dict) -> bytes:
        return self._backend().read(
            reference_id=reference["id"],
            secret_type=reference["secret_type"],
            scope=reference["workspace_id_or_host_scope"],
            version=int(reference["current_version"]),
        )

    def _reference(self, reference_id: str) -> dict:
        try:
            return self.repository.get_reference(reference_id)
        except KeyError as exc:
            raise ManagedSecretError("secret.not_found", "Secret reference was not found.") from exc

    def _versions(self, reference_id: str) -> list[dict]:
        return self.repository.list_versions(reference_id)

    def _replace_reference(self, reference: dict, **changes: object) -> dict:
        payload = dict(reference)
        payload.update(changes)
        saved = self.repository.save_reference(ManagedSecretReference(**payload))
        return saved

    def _backend(self) -> ManagedSecretBackend:
        if self.backend is None:
            raise ManagedSecretError("secret.backend_not_configured", "No managed secret backend is configured.")
        return self.backend

    def _release(self, lease: SecretLease) -> None:
        self._audit(
            "secret.lease_released",
            lease.secret_reference_id,
            lease.secret_version,
            lease.purpose,
            lease.consumer,
            "success",
            "",
        )

    def _audit(
        self,
        action: str,
        resource_id: str,
        resource_version: int,
        purpose: str,
        actor: str,
        result: str,
        safe_error_code: str,
    ) -> None:
        self.repository.audit(
            ManagedSecretAuditEvent(
                id="secret-audit-"
                + stable_checksum({"action": action, "resource": resource_id, "at": utc_now_iso()})[:20],
                action=action,
                resource_id=resource_id,
                resource_version=resource_version,
                purpose=purpose,
                actor=actor,
                result=result,
                safe_error_code=safe_error_code,
                occurred_at=utc_now_iso(),
            )
        )

    @staticmethod
    def _validate_secret_type(secret_type: str) -> None:
        from .models import SECRET_TYPES

        if secret_type not in SECRET_TYPES or secret_type == "master_key":
            raise ManagedSecretError("secret.type_invalid", "Secret type is not available through workspace API.")

    @staticmethod
    def _validate_secret_size(value: bytes) -> None:
        if not value or len(value) > 64 * 1024:
            raise ManagedSecretError("secret.size", "Secret size is invalid.")

    @staticmethod
    def _public_reference(reference: dict) -> dict:
        payload = dict(reference)
        payload["value_redacted"] = True
        payload.pop("backend_record_reference", None)
        return payload


def _fingerprint_for_secret(secret_type: str, value: bytes) -> str:
    if secret_type == "ed25519_private_key":
        return fingerprint_public_key(public_key_from_private_pem(value.decode("utf-8")))
    return stable_checksum(
        {"secret_type": secret_type, "secret_value_sha256": stable_checksum(value.decode("latin1"))}
    )[:16]


def _is_expired(expires_at: str) -> bool:
    if not expires_at:
        return False
    try:
        normalized = expires_at.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized) <= datetime.now(UTC)
    except ValueError:
        return True


__all__ = ["ManagedSecretFacade"]
