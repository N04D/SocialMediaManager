from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .identifiers import validate_namespaced_id, validate_runtime_id

EVENT_SCHEMA_VERSION = "1.0"
SECRET_FIELD_FRAGMENTS = ("secret", "token", "password", "credential", "api_key")


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def generate_event_id() -> str:
    return f"evt_{uuid4().hex}"


def _safe_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))


def _contains_secret_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SECRET_FIELD_FRAGMENTS):
                return True
            if _contains_secret_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_key(item) for item in value)
    return False


@dataclass(frozen=True)
class EventSource:
    component: str = ""
    install: str = ""
    provider: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.component and not self.install and not self.provider:
            raise ValueError("EventSource requires component, install, or provider.")
        if self.component:
            object.__setattr__(self, "component", validate_runtime_id(self.component, field_name="source.component"))
        if self.install:
            object.__setattr__(self, "install", validate_runtime_id(self.install, field_name="source.install"))
        if self.provider:
            object.__setattr__(self, "provider", validate_runtime_id(self.provider, field_name="source.provider"))
        object.__setattr__(self, "metadata", _safe_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "install": self.install,
            "metadata": _safe_mapping(self.metadata),
            "provider": self.provider,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EventSource:
        return cls(
            component=str(payload.get("component") or ""),
            install=str(payload.get("install") or ""),
            provider=str(payload.get("provider") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class EventEnvelope:
    event_type: str
    source: EventSource
    event_id: str = field(default_factory=generate_event_id)
    schema_version: str = EVENT_SCHEMA_VERSION
    occurred_at: str = field(default_factory=utc_now_iso)
    received_at: str = field(default_factory=utc_now_iso)
    workspace_id: str = ""
    account_id: str = ""
    entity_ref: str = ""
    external_event_id: str = ""
    correlation_id: str = ""
    causation_id: str = ""
    trace_id: str = ""
    idempotency_key: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", validate_runtime_id(self.event_id, field_name="event_id"))
        object.__setattr__(self, "event_type", validate_namespaced_id(self.event_type, field_name="event_type"))
        if _contains_secret_key(self.payload) or _contains_secret_key(self.metadata):
            raise ValueError("EventEnvelope payload and metadata must not include secret-shaped fields.")
        object.__setattr__(self, "payload", _safe_mapping(self.payload))
        object.__setattr__(self, "metadata", _safe_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "causation_id": self.causation_id,
            "correlation_id": self.correlation_id,
            "entity_ref": self.entity_ref,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "external_event_id": self.external_event_id,
            "idempotency_key": self.idempotency_key,
            "metadata": _safe_mapping(self.metadata),
            "occurred_at": self.occurred_at,
            "payload": _safe_mapping(self.payload),
            "received_at": self.received_at,
            "schema_version": self.schema_version,
            "source": self.source.to_dict(),
            "trace_id": self.trace_id,
            "workspace_id": self.workspace_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EventEnvelope:
        return cls(
            event_id=str(payload.get("event_id") or ""),
            event_type=str(payload.get("event_type") or ""),
            schema_version=str(payload.get("schema_version") or EVENT_SCHEMA_VERSION),
            occurred_at=str(payload.get("occurred_at") or ""),
            received_at=str(payload.get("received_at") or ""),
            source=EventSource.from_dict(dict(payload.get("source") or {})),
            workspace_id=str(payload.get("workspace_id") or ""),
            account_id=str(payload.get("account_id") or ""),
            entity_ref=str(payload.get("entity_ref") or ""),
            external_event_id=str(payload.get("external_event_id") or ""),
            correlation_id=str(payload.get("correlation_id") or ""),
            causation_id=str(payload.get("causation_id") or ""),
            trace_id=str(payload.get("trace_id") or ""),
            idempotency_key=str(payload.get("idempotency_key") or ""),
            payload=dict(payload.get("payload") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )

    @classmethod
    def from_json(cls, payload: str) -> EventEnvelope:
        return cls.from_dict(json.loads(payload))
