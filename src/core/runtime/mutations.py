from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from .errors import PlaybookExecutionError
from .events import utc_now_iso
from .identifiers import validate_namespaced_id, validate_runtime_id
from .installs import SECRET_VALUE_FRAGMENTS


class MutationState(StrEnum):
    PREPARED = "prepared"
    APPROVED = "approved"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"


def canonical_mutation_input(value: dict[str, Any]) -> dict[str, Any]:
    _assert_no_secret_values(value)
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def mutation_input_fingerprint(value: dict[str, Any]) -> str:
    canonical = canonical_mutation_input(value)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_mutation_id(
    *,
    execution_id: str,
    node_id: str,
    capability_id: str,
    component_id: str,
    install_id: str,
    input_fingerprint: str,
) -> str:
    seed = ":".join((execution_id, node_id, capability_id, component_id, install_id, input_fingerprint))
    return f"mutation_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:32]}"


def build_mutation_idempotency_key(
    *,
    deployment_id: str,
    execution_id: str,
    node_id: str,
    trigger_idempotency_key: str,
    input_fingerprint: str,
) -> str:
    trigger_key = trigger_idempotency_key or execution_id
    seed = ":".join((deployment_id, execution_id, node_id, trigger_key, input_fingerprint))
    return f"mutation:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True)
class MutationIntent:
    mutation_id: str
    execution_id: str
    node_id: str
    capability_id: str
    component_id: str
    install_id: str
    normalized_input: dict[str, Any]
    input_fingerprint: str
    idempotency_key: str
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        validate_runtime_id(self.mutation_id, field_name="mutation_id")
        validate_runtime_id(self.execution_id, field_name="execution_id")
        validate_runtime_id(self.node_id, field_name="node_id")
        validate_namespaced_id(self.capability_id, field_name="capability_id")
        validate_runtime_id(self.component_id, field_name="component_id")
        validate_runtime_id(self.install_id, field_name="install_id")
        normalized = canonical_mutation_input(self.normalized_input)
        object.__setattr__(self, "normalized_input", normalized)
        object.__setattr__(self, "input_fingerprint", self.input_fingerprint or mutation_input_fingerprint(normalized))

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "component_id": self.component_id,
            "created_at": self.created_at,
            "execution_id": self.execution_id,
            "idempotency_key": self.idempotency_key,
            "input_fingerprint": self.input_fingerprint,
            "install_id": self.install_id,
            "mutation_id": self.mutation_id,
            "node_id": self.node_id,
            "normalized_input": canonical_mutation_input(self.normalized_input),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MutationIntent:
        return cls(
            mutation_id=str(payload.get("mutation_id") or ""),
            execution_id=str(payload.get("execution_id") or ""),
            node_id=str(payload.get("node_id") or ""),
            capability_id=str(payload.get("capability_id") or ""),
            component_id=str(payload.get("component_id") or ""),
            install_id=str(payload.get("install_id") or ""),
            normalized_input=dict(payload.get("normalized_input") or {}),
            input_fingerprint=str(payload.get("input_fingerprint") or ""),
            idempotency_key=str(payload.get("idempotency_key") or ""),
            created_at=str(payload.get("created_at") or ""),
        )


@dataclass(frozen=True)
class MutationReceipt:
    mutation_id: str
    capability_id: str
    component_id: str
    resource_ref: str
    applied_at: str
    idempotency_key: str
    result_fingerprint: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_runtime_id(self.mutation_id, field_name="mutation_id")
        validate_namespaced_id(self.capability_id, field_name="capability_id")
        validate_runtime_id(self.component_id, field_name="component_id")
        if not self.resource_ref:
            raise PlaybookExecutionError("MUTATION_RECEIPT_INVALID", "Mutation receipt requires a resource_ref.")
        _assert_no_secret_values(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied_at": self.applied_at,
            "capability_id": self.capability_id,
            "component_id": self.component_id,
            "idempotency_key": self.idempotency_key,
            "metadata": json.loads(json.dumps(self.metadata, sort_keys=True, ensure_ascii=True)),
            "mutation_id": self.mutation_id,
            "resource_ref": self.resource_ref,
            "result_fingerprint": self.result_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MutationReceipt:
        return cls(
            mutation_id=str(payload.get("mutation_id") or ""),
            capability_id=str(payload.get("capability_id") or ""),
            component_id=str(payload.get("component_id") or ""),
            resource_ref=str(payload.get("resource_ref") or ""),
            applied_at=str(payload.get("applied_at") or ""),
            idempotency_key=str(payload.get("idempotency_key") or ""),
            result_fingerprint=str(payload.get("result_fingerprint") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class MutationJournalRecord:
    intent: MutationIntent
    state: str = MutationState.PREPARED.value
    approval_id: str = ""
    approved_at: str = ""
    applied_at: str = ""
    failed_at: str = ""
    error_code: str = ""
    receipt: MutationReceipt | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied_at": self.applied_at,
            "approval_id": self.approval_id,
            "approved_at": self.approved_at,
            "error_code": self.error_code,
            "failed_at": self.failed_at,
            "intent": self.intent.to_dict(),
            "receipt": self.receipt.to_dict() if self.receipt else {},
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MutationJournalRecord:
        receipt_payload = payload.get("receipt") or {}
        return cls(
            intent=MutationIntent.from_dict(dict(payload.get("intent") or {})),
            state=str(payload.get("state") or MutationState.PREPARED.value),
            approval_id=str(payload.get("approval_id") or ""),
            approved_at=str(payload.get("approved_at") or ""),
            applied_at=str(payload.get("applied_at") or ""),
            failed_at=str(payload.get("failed_at") or ""),
            error_code=str(payload.get("error_code") or ""),
            receipt=MutationReceipt.from_dict(dict(receipt_payload)) if receipt_payload else None,
        )


class MutationJournal(Protocol):
    def prepare_intent(self, intent: MutationIntent) -> MutationJournalRecord: ...

    def get(self, mutation_id: str) -> MutationJournalRecord | None: ...

    def find_by_idempotency_key(self, idempotency_key: str) -> MutationJournalRecord | None: ...

    def mark_approved(self, mutation_id: str, *, approval_id: str) -> MutationJournalRecord: ...

    def mark_applying(self, mutation_id: str) -> MutationJournalRecord: ...

    def record_applied(self, receipt: MutationReceipt) -> MutationJournalRecord: ...

    def record_failed(self, mutation_id: str, *, error_code: str) -> MutationJournalRecord: ...


@dataclass
class InMemoryMutationJournal:
    records: dict[str, MutationJournalRecord] = field(default_factory=dict)
    idempotency_index: dict[str, str] = field(default_factory=dict)

    def prepare_intent(self, intent: MutationIntent) -> MutationJournalRecord:
        existing = self.find_by_idempotency_key(intent.idempotency_key)
        if existing is not None:
            _assert_same_intent(existing.intent, intent)
            return existing
        record = self.records.get(intent.mutation_id)
        if record is not None:
            _assert_same_intent(record.intent, intent)
            return record
        record = MutationJournalRecord(intent=intent)
        self.records[intent.mutation_id] = record
        self.idempotency_index[intent.idempotency_key] = intent.mutation_id
        return record

    def get(self, mutation_id: str) -> MutationJournalRecord | None:
        return self.records.get(mutation_id)

    def find_by_idempotency_key(self, idempotency_key: str) -> MutationJournalRecord | None:
        mutation_id = self.idempotency_index.get(idempotency_key)
        return self.records.get(mutation_id) if mutation_id else None

    def mark_approved(self, mutation_id: str, *, approval_id: str) -> MutationJournalRecord:
        record = self._require(mutation_id)
        if record.state == MutationState.APPLIED.value:
            return record
        updated = replace(
            record,
            state=MutationState.APPROVED.value,
            approval_id=approval_id or record.approval_id,
            approved_at=record.approved_at or utc_now_iso(),
        )
        self.records[mutation_id] = updated
        return updated

    def mark_applying(self, mutation_id: str) -> MutationJournalRecord:
        record = self._require(mutation_id)
        if record.state == MutationState.APPLIED.value:
            return record
        updated = replace(record, state=MutationState.APPLYING.value)
        self.records[mutation_id] = updated
        return updated

    def record_applied(self, receipt: MutationReceipt) -> MutationJournalRecord:
        record = self._require(receipt.mutation_id)
        updated = replace(
            record,
            state=MutationState.APPLIED.value,
            receipt=receipt,
            applied_at=receipt.applied_at,
            error_code="",
        )
        self.records[receipt.mutation_id] = updated
        return updated

    def record_failed(self, mutation_id: str, *, error_code: str) -> MutationJournalRecord:
        record = self._require(mutation_id)
        if record.state == MutationState.APPLIED.value:
            return record
        updated = replace(
            record,
            state=MutationState.FAILED.value,
            failed_at=utc_now_iso(),
            error_code=error_code,
        )
        self.records[mutation_id] = updated
        return updated

    def _require(self, mutation_id: str) -> MutationJournalRecord:
        record = self.records.get(mutation_id)
        if record is None:
            raise PlaybookExecutionError("MUTATION_INTENT_NOT_FOUND", "Mutation intent was not prepared.")
        return record


class JsonMutationJournal(InMemoryMutationJournal):
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__()
        self._load()

    def prepare_intent(self, intent: MutationIntent) -> MutationJournalRecord:
        record = super().prepare_intent(intent)
        self._save()
        return record

    def mark_approved(self, mutation_id: str, *, approval_id: str) -> MutationJournalRecord:
        record = super().mark_approved(mutation_id, approval_id=approval_id)
        self._save()
        return record

    def mark_applying(self, mutation_id: str) -> MutationJournalRecord:
        record = super().mark_applying(mutation_id)
        self._save()
        return record

    def record_applied(self, receipt: MutationReceipt) -> MutationJournalRecord:
        record = super().record_applied(receipt)
        self._save()
        return record

    def record_failed(self, mutation_id: str, *, error_code: str) -> MutationJournalRecord:
        record = super().record_failed(mutation_id, error_code=error_code)
        self._save()
        return record

    def _load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        records = payload.get("records", {}) if isinstance(payload, dict) else {}
        self.records = {
            str(mutation_id): MutationJournalRecord.from_dict(dict(record))
            for mutation_id, record in records.items()
            if isinstance(record, dict)
        }
        self.idempotency_index = {
            record.intent.idempotency_key: mutation_id for mutation_id, record in self.records.items()
        }

    def _save(self) -> None:
        payload = {"records": {key: record.to_dict() for key, record in sorted(self.records.items())}}
        tmp = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)


def _assert_same_intent(existing: MutationIntent, incoming: MutationIntent) -> None:
    if existing.input_fingerprint != incoming.input_fingerprint:
        raise PlaybookExecutionError(
            "MUTATION_INTENT_CHANGED",
            "Mutation idempotency key was reused with different input.",
            {
                "existing_fingerprint": existing.input_fingerprint,
                "incoming_fingerprint": incoming.input_fingerprint,
            },
        )


def _assert_no_secret_values(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SECRET_VALUE_FRAGMENTS) and not lowered.endswith("_ref"):
                raise PlaybookExecutionError(
                    "MUTATION_SECRET_VALUE",
                    "Mutation intent and receipt data may not contain secret-shaped values.",
                    {"field": str(key)},
                )
            _assert_no_secret_values(child)
    elif isinstance(value, list):
        for item in value:
            _assert_no_secret_values(item)
