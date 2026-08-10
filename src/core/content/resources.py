from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.runtime.events import utc_now_iso
from src.core.runtime.identifiers import validate_runtime_id


@dataclass(frozen=True)
class ResourceRef:
    provider: str
    resource_type: str
    external_id: str
    install_id: str = ""
    canonical_ref: str = ""

    def __post_init__(self) -> None:
        validate_runtime_id(self.provider, field_name="provider")
        validate_runtime_id(self.resource_type, field_name="resource_type")
        if not str(self.external_id or "").strip():
            raise ValueError("ResourceRef external_id is required.")
        if not self.canonical_ref:
            object.__setattr__(self, "canonical_ref", f"{self.provider}:{self.resource_type}:{self.external_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_ref": self.canonical_ref,
            "external_id": self.external_id,
            "install_id": self.install_id,
            "provider": self.provider,
            "resource_type": self.resource_type,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResourceRef:
        return cls(
            provider=str(payload.get("provider") or ""),
            resource_type=str(payload.get("resource_type") or ""),
            external_id=str(payload.get("external_id") or ""),
            install_id=str(payload.get("install_id") or ""),
            canonical_ref=str(payload.get("canonical_ref") or ""),
        )


@dataclass(frozen=True)
class ExternalResourceSnapshot:
    resource_ref: ResourceRef
    observed_at: str = field(default_factory=utc_now_iso)
    provider_revision: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "fields": dict(self.fields),
            "observed_at": self.observed_at,
            "provider_revision": self.provider_revision,
            "resource_ref": self.resource_ref.to_dict(),
        }
        if self.raw_payload is not None:
            data["raw_payload"] = self.raw_payload
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ExternalResourceSnapshot:
        ref_payload = payload.get("resource_ref")
        ref = ResourceRef.from_dict(dict(ref_payload or {}))
        return cls(
            resource_ref=ref,
            observed_at=str(payload.get("observed_at") or utc_now_iso()),
            provider_revision=str(payload.get("provider_revision") or ""),
            fields=dict(payload.get("fields") or {}),
            raw_payload=payload.get("raw_payload"),
        )
