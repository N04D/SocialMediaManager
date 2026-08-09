from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
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


class CompensationState(StrEnum):
    PREPARED = "compensation_prepared"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "compensation_failed"


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
    del execution_id
    seed = ":".join((node_id, capability_id, component_id, install_id, input_fingerprint))
    return f"mutation_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:32]}"


def build_mutation_idempotency_key(
    *,
    deployment_id: str,
    execution_id: str,
    node_id: str,
    trigger_idempotency_key: str,
    input_fingerprint: str,
) -> str:
    del execution_id
    trigger_key = trigger_idempotency_key or "missing-trigger-key"
    seed = ":".join((deployment_id, node_id, trigger_key, input_fingerprint))
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
class CompensationIntent:
    compensation_id: str
    original_mutation_id: str
    execution_id: str
    node_id: str
    capability_id: str
    component_id: str
    install_id: str
    resource_ref: str
    compensation_fingerprint: str
    idempotency_key: str
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        validate_runtime_id(self.compensation_id, field_name="compensation_id")
        validate_runtime_id(self.original_mutation_id, field_name="original_mutation_id")
        validate_runtime_id(self.execution_id, field_name="execution_id")
        validate_runtime_id(self.node_id, field_name="node_id")
        validate_namespaced_id(self.capability_id, field_name="capability_id")
        validate_runtime_id(self.component_id, field_name="component_id")
        validate_runtime_id(self.install_id, field_name="install_id")
        if not self.resource_ref:
            raise PlaybookExecutionError("COMPENSATION_INTENT_INVALID", "Compensation requires a resource_ref.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "compensation_fingerprint": self.compensation_fingerprint,
            "compensation_id": self.compensation_id,
            "component_id": self.component_id,
            "created_at": self.created_at,
            "execution_id": self.execution_id,
            "idempotency_key": self.idempotency_key,
            "install_id": self.install_id,
            "node_id": self.node_id,
            "original_mutation_id": self.original_mutation_id,
            "resource_ref": self.resource_ref,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CompensationIntent:
        return cls(
            compensation_id=str(payload.get("compensation_id") or ""),
            original_mutation_id=str(payload.get("original_mutation_id") or ""),
            execution_id=str(payload.get("execution_id") or ""),
            node_id=str(payload.get("node_id") or ""),
            capability_id=str(payload.get("capability_id") or ""),
            component_id=str(payload.get("component_id") or ""),
            install_id=str(payload.get("install_id") or ""),
            resource_ref=str(payload.get("resource_ref") or ""),
            compensation_fingerprint=str(payload.get("compensation_fingerprint") or ""),
            idempotency_key=str(payload.get("idempotency_key") or ""),
            created_at=str(payload.get("created_at") or ""),
        )


@dataclass(frozen=True)
class CompensationReceipt:
    compensation_id: str
    original_mutation_id: str
    resource_ref: str
    compensated_at: str
    idempotency_key: str
    verified: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_runtime_id(self.compensation_id, field_name="compensation_id")
        validate_runtime_id(self.original_mutation_id, field_name="original_mutation_id")
        if not self.resource_ref:
            raise PlaybookExecutionError("COMPENSATION_RECEIPT_INVALID", "Compensation receipt requires resource_ref.")
        _assert_no_secret_values(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "compensated_at": self.compensated_at,
            "compensation_id": self.compensation_id,
            "idempotency_key": self.idempotency_key,
            "metadata": json.loads(json.dumps(self.metadata, sort_keys=True, ensure_ascii=True)),
            "original_mutation_id": self.original_mutation_id,
            "resource_ref": self.resource_ref,
            "verified": self.verified,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CompensationReceipt:
        return cls(
            compensation_id=str(payload.get("compensation_id") or ""),
            original_mutation_id=str(payload.get("original_mutation_id") or ""),
            resource_ref=str(payload.get("resource_ref") or ""),
            compensated_at=str(payload.get("compensated_at") or ""),
            idempotency_key=str(payload.get("idempotency_key") or ""),
            verified=bool(payload.get("verified", False)),
            metadata=dict(payload.get("metadata") or {}),
        )


class CompensatableMutationHandler(Protocol):
    def compensate(
        self,
        *,
        receipt: MutationReceipt,
        context: Any,
        compensation: CompensationIntent,
    ) -> CompensationReceipt: ...


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


@dataclass(frozen=True)
class CompensationJournalRecord:
    intent: CompensationIntent
    state: str = CompensationState.PREPARED.value
    compensated_at: str = ""
    failed_at: str = ""
    error_code: str = ""
    receipt: CompensationReceipt | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "compensated_at": self.compensated_at,
            "error_code": self.error_code,
            "failed_at": self.failed_at,
            "intent": self.intent.to_dict(),
            "receipt": self.receipt.to_dict() if self.receipt else {},
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CompensationJournalRecord:
        receipt_payload = payload.get("receipt") or {}
        return cls(
            intent=CompensationIntent.from_dict(dict(payload.get("intent") or {})),
            state=str(payload.get("state") or CompensationState.PREPARED.value),
            compensated_at=str(payload.get("compensated_at") or ""),
            failed_at=str(payload.get("failed_at") or ""),
            error_code=str(payload.get("error_code") or ""),
            receipt=CompensationReceipt.from_dict(dict(receipt_payload)) if receipt_payload else None,
        )


class MutationJournal(Protocol):
    def prepare_intent(self, intent: MutationIntent) -> MutationJournalRecord: ...

    def get(self, mutation_id: str) -> MutationJournalRecord | None: ...

    def find_by_idempotency_key(self, idempotency_key: str) -> MutationJournalRecord | None: ...

    def mark_approved(self, mutation_id: str, *, approval_id: str) -> MutationJournalRecord: ...

    def mark_applying(self, mutation_id: str) -> MutationJournalRecord: ...

    def claim_applying(self, mutation_id: str, *, owner: str = "") -> tuple[MutationJournalRecord, bool]: ...

    def record_applied(self, receipt: MutationReceipt) -> MutationJournalRecord: ...

    def record_failed(self, mutation_id: str, *, error_code: str) -> MutationJournalRecord: ...

    def prepare_compensation(self, intent: CompensationIntent) -> CompensationJournalRecord: ...

    def get_compensation(self, compensation_id: str) -> CompensationJournalRecord | None: ...

    def claim_compensating(
        self, compensation_id: str, *, owner: str = ""
    ) -> tuple[CompensationJournalRecord, bool]: ...

    def record_compensated(self, receipt: CompensationReceipt) -> CompensationJournalRecord: ...

    def record_compensation_failed(self, compensation_id: str, *, error_code: str) -> CompensationJournalRecord: ...


@dataclass
class InMemoryMutationJournal:
    records: dict[str, MutationJournalRecord] = field(default_factory=dict)
    idempotency_index: dict[str, str] = field(default_factory=dict)
    compensations: dict[str, CompensationJournalRecord] = field(default_factory=dict)
    compensation_idempotency_index: dict[str, str] = field(default_factory=dict)

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

    def claim_applying(self, mutation_id: str, *, owner: str = "") -> tuple[MutationJournalRecord, bool]:
        del owner
        record = self._require(mutation_id)
        if record.state == MutationState.APPLIED.value:
            return record, False
        if record.state == MutationState.APPLYING.value:
            return record, False
        return self.mark_applying(mutation_id), True

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

    def prepare_compensation(self, intent: CompensationIntent) -> CompensationJournalRecord:
        existing = self._find_compensation_by_idempotency_key(intent.idempotency_key)
        if existing is not None:
            return existing
        record = self.compensations.get(intent.compensation_id)
        if record is not None:
            return record
        record = CompensationJournalRecord(intent=intent)
        self.compensations[intent.compensation_id] = record
        self.compensation_idempotency_index[intent.idempotency_key] = intent.compensation_id
        return record

    def get_compensation(self, compensation_id: str) -> CompensationJournalRecord | None:
        return self.compensations.get(compensation_id)

    def claim_compensating(self, compensation_id: str, *, owner: str = "") -> tuple[CompensationJournalRecord, bool]:
        del owner
        record = self._require_compensation(compensation_id)
        if record.state == CompensationState.COMPENSATED.value:
            return record, False
        if record.state == CompensationState.COMPENSATING.value:
            return record, False
        updated = replace(record, state=CompensationState.COMPENSATING.value)
        self.compensations[compensation_id] = updated
        return updated, True

    def record_compensated(self, receipt: CompensationReceipt) -> CompensationJournalRecord:
        record = self._require_compensation(receipt.compensation_id)
        updated = replace(
            record,
            state=CompensationState.COMPENSATED.value,
            receipt=receipt,
            compensated_at=receipt.compensated_at,
            error_code="",
        )
        self.compensations[receipt.compensation_id] = updated
        return updated

    def record_compensation_failed(self, compensation_id: str, *, error_code: str) -> CompensationJournalRecord:
        record = self._require_compensation(compensation_id)
        if record.state == CompensationState.COMPENSATED.value:
            return record
        updated = replace(
            record,
            state=CompensationState.FAILED.value,
            failed_at=utc_now_iso(),
            error_code=error_code,
        )
        self.compensations[compensation_id] = updated
        return updated

    def _require(self, mutation_id: str) -> MutationJournalRecord:
        record = self.records.get(mutation_id)
        if record is None:
            raise PlaybookExecutionError("MUTATION_INTENT_NOT_FOUND", "Mutation intent was not prepared.")
        return record

    def _require_compensation(self, compensation_id: str) -> CompensationJournalRecord:
        record = self.compensations.get(compensation_id)
        if record is None:
            raise PlaybookExecutionError(
                "COMPENSATION_INTENT_NOT_FOUND",
                "Compensation intent was not prepared.",
                {"compensation_id": compensation_id},
            )
        return record

    def _find_compensation_by_idempotency_key(self, idempotency_key: str) -> CompensationJournalRecord | None:
        compensation_id = self.compensation_idempotency_index.get(idempotency_key)
        return self.compensations.get(compensation_id) if compensation_id else None


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

    def claim_applying(self, mutation_id: str, *, owner: str = "") -> tuple[MutationJournalRecord, bool]:
        record, claimed = super().claim_applying(mutation_id, owner=owner)
        self._save()
        return record, claimed

    def record_applied(self, receipt: MutationReceipt) -> MutationJournalRecord:
        record = super().record_applied(receipt)
        self._save()
        return record

    def record_failed(self, mutation_id: str, *, error_code: str) -> MutationJournalRecord:
        record = super().record_failed(mutation_id, error_code=error_code)
        self._save()
        return record

    def prepare_compensation(self, intent: CompensationIntent) -> CompensationJournalRecord:
        record = super().prepare_compensation(intent)
        self._save()
        return record

    def claim_compensating(self, compensation_id: str, *, owner: str = "") -> tuple[CompensationJournalRecord, bool]:
        record, claimed = super().claim_compensating(compensation_id, owner=owner)
        self._save()
        return record, claimed

    def record_compensated(self, receipt: CompensationReceipt) -> CompensationJournalRecord:
        record = super().record_compensated(receipt)
        self._save()
        return record

    def record_compensation_failed(self, compensation_id: str, *, error_code: str) -> CompensationJournalRecord:
        record = super().record_compensation_failed(compensation_id, error_code=error_code)
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
        compensations = payload.get("compensations", {}) if isinstance(payload, dict) else {}
        self.compensations = {
            str(compensation_id): CompensationJournalRecord.from_dict(dict(record))
            for compensation_id, record in compensations.items()
            if isinstance(record, dict)
        }
        self.compensation_idempotency_index = {
            record.intent.idempotency_key: compensation_id for compensation_id, record in self.compensations.items()
        }

    def _save(self) -> None:
        payload = {
            "compensations": {key: record.to_dict() for key, record in sorted(self.compensations.items())},
            "records": {key: record.to_dict() for key, record in sorted(self.records.items())},
        }
        tmp = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)


class SqliteMutationJournal:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def prepare_intent(self, intent: MutationIntent) -> MutationJournalRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM runtime_mutation_journal WHERE idempotency_key=? OR mutation_id=?",
                (intent.idempotency_key, intent.mutation_id),
            ).fetchone()
            if row:
                record = _mutation_record_from_row(row)
                _assert_same_intent(record.intent, intent)
                connection.commit()
                return record
            connection.execute(
                """
                INSERT INTO runtime_mutation_journal
                (mutation_id, idempotency_key, state, intent_json, approval_id, approved_at,
                 applied_at, failed_at, error_code, receipt_json, owner, updated_at)
                VALUES (?, ?, ?, ?, '', '', '', '', '', '', '', ?)
                """,
                (
                    intent.mutation_id,
                    intent.idempotency_key,
                    MutationState.PREPARED.value,
                    json.dumps(intent.to_dict(), sort_keys=True),
                    utc_now_iso(),
                ),
            )
            connection.commit()
        return self.get(intent.mutation_id)  # type: ignore[return-value]

    def get(self, mutation_id: str) -> MutationJournalRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runtime_mutation_journal WHERE mutation_id=?", (mutation_id,)
            ).fetchone()
        return _mutation_record_from_row(row) if row else None

    def find_by_idempotency_key(self, idempotency_key: str) -> MutationJournalRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runtime_mutation_journal WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
        return _mutation_record_from_row(row) if row else None

    def mark_approved(self, mutation_id: str, *, approval_id: str) -> MutationJournalRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_row(connection, mutation_id)
            if row["state"] != MutationState.APPLIED.value:
                connection.execute(
                    """
                    UPDATE runtime_mutation_journal
                    SET state=?, approval_id=COALESCE(NULLIF(?, ''), approval_id),
                        approved_at=CASE WHEN approved_at='' THEN ? ELSE approved_at END,
                        updated_at=?
                    WHERE mutation_id=?
                    """,
                    (MutationState.APPROVED.value, approval_id, utc_now_iso(), utc_now_iso(), mutation_id),
                )
            connection.commit()
        return self.get(mutation_id)  # type: ignore[return-value]

    def mark_applying(self, mutation_id: str) -> MutationJournalRecord:
        record, _claimed = self.claim_applying(mutation_id)
        return record

    def claim_applying(self, mutation_id: str, *, owner: str = "") -> tuple[MutationJournalRecord, bool]:
        owner = owner or "runtime"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_row(connection, mutation_id)
            if row["state"] == MutationState.APPLIED.value:
                connection.commit()
                return _mutation_record_from_row(row), False
            if row["state"] == MutationState.APPLYING.value and row["owner"] != owner:
                connection.commit()
                return _mutation_record_from_row(row), False
            updated = connection.execute(
                """
                UPDATE runtime_mutation_journal
                SET state=?, owner=?, updated_at=?
                WHERE mutation_id=? AND state IN (?, ?, ?)
                """,
                (
                    MutationState.APPLYING.value,
                    owner,
                    utc_now_iso(),
                    mutation_id,
                    MutationState.PREPARED.value,
                    MutationState.APPROVED.value,
                    MutationState.FAILED.value,
                ),
            )
            claimed = updated.rowcount == 1
            row = self._require_row(connection, mutation_id)
            connection.commit()
        return _mutation_record_from_row(row), claimed

    def record_applied(self, receipt: MutationReceipt) -> MutationJournalRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_row(connection, receipt.mutation_id)
            connection.execute(
                """
                UPDATE runtime_mutation_journal
                SET state=?, applied_at=?, receipt_json=?, error_code='', owner='', updated_at=?
                WHERE mutation_id=?
                """,
                (
                    MutationState.APPLIED.value,
                    receipt.applied_at,
                    json.dumps(receipt.to_dict(), sort_keys=True),
                    utc_now_iso(),
                    receipt.mutation_id,
                ),
            )
            connection.commit()
        return self.get(receipt.mutation_id)  # type: ignore[return-value]

    def record_failed(self, mutation_id: str, *, error_code: str) -> MutationJournalRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_row(connection, mutation_id)
            if row["state"] != MutationState.APPLIED.value:
                connection.execute(
                    """
                    UPDATE runtime_mutation_journal
                    SET state=?, failed_at=?, error_code=?, owner='', updated_at=?
                    WHERE mutation_id=?
                    """,
                    (MutationState.FAILED.value, utc_now_iso(), error_code, utc_now_iso(), mutation_id),
                )
            connection.commit()
        return self.get(mutation_id)  # type: ignore[return-value]

    def prepare_compensation(self, intent: CompensationIntent) -> CompensationJournalRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM runtime_compensation_journal WHERE idempotency_key=? OR compensation_id=?",
                (intent.idempotency_key, intent.compensation_id),
            ).fetchone()
            if row:
                connection.commit()
                return _compensation_record_from_row(row)
            connection.execute(
                """
                INSERT INTO runtime_compensation_journal
                (compensation_id, idempotency_key, original_mutation_id, state, intent_json,
                 compensated_at, failed_at, error_code, receipt_json, owner, updated_at)
                VALUES (?, ?, ?, ?, ?, '', '', '', '', '', ?)
                """,
                (
                    intent.compensation_id,
                    intent.idempotency_key,
                    intent.original_mutation_id,
                    CompensationState.PREPARED.value,
                    json.dumps(intent.to_dict(), sort_keys=True),
                    utc_now_iso(),
                ),
            )
            connection.commit()
        return self.get_compensation(intent.compensation_id)  # type: ignore[return-value]

    def get_compensation(self, compensation_id: str) -> CompensationJournalRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runtime_compensation_journal WHERE compensation_id=?", (compensation_id,)
            ).fetchone()
        return _compensation_record_from_row(row) if row else None

    def claim_compensating(self, compensation_id: str, *, owner: str = "") -> tuple[CompensationJournalRecord, bool]:
        owner = owner or "runtime"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_compensation_row(connection, compensation_id)
            if row["state"] == CompensationState.COMPENSATED.value:
                connection.commit()
                return _compensation_record_from_row(row), False
            if row["state"] == CompensationState.COMPENSATING.value and row["owner"] != owner:
                connection.commit()
                return _compensation_record_from_row(row), False
            updated = connection.execute(
                """
                UPDATE runtime_compensation_journal
                SET state=?, owner=?, updated_at=?
                WHERE compensation_id=? AND state IN (?, ?)
                """,
                (
                    CompensationState.COMPENSATING.value,
                    owner,
                    utc_now_iso(),
                    compensation_id,
                    CompensationState.PREPARED.value,
                    CompensationState.FAILED.value,
                ),
            )
            claimed = updated.rowcount == 1
            row = self._require_compensation_row(connection, compensation_id)
            connection.commit()
        return _compensation_record_from_row(row), claimed

    def record_compensated(self, receipt: CompensationReceipt) -> CompensationJournalRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_compensation_row(connection, receipt.compensation_id)
            connection.execute(
                """
                UPDATE runtime_compensation_journal
                SET state=?, compensated_at=?, receipt_json=?, error_code='', owner='', updated_at=?
                WHERE compensation_id=?
                """,
                (
                    CompensationState.COMPENSATED.value,
                    receipt.compensated_at,
                    json.dumps(receipt.to_dict(), sort_keys=True),
                    utc_now_iso(),
                    receipt.compensation_id,
                ),
            )
            connection.commit()
        return self.get_compensation(receipt.compensation_id)  # type: ignore[return-value]

    def record_compensation_failed(self, compensation_id: str, *, error_code: str) -> CompensationJournalRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_compensation_row(connection, compensation_id)
            if row["state"] != CompensationState.COMPENSATED.value:
                connection.execute(
                    """
                    UPDATE runtime_compensation_journal
                    SET state=?, failed_at=?, error_code=?, owner='', updated_at=?
                    WHERE compensation_id=?
                    """,
                    (CompensationState.FAILED.value, utc_now_iso(), error_code, utc_now_iso(), compensation_id),
                )
            connection.commit()
        return self.get_compensation(compensation_id)  # type: ignore[return-value]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runtime_mutation_journal (
                    mutation_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    intent_json TEXT NOT NULL,
                    approval_id TEXT NOT NULL DEFAULT '',
                    approved_at TEXT NOT NULL DEFAULT '',
                    applied_at TEXT NOT NULL DEFAULT '',
                    failed_at TEXT NOT NULL DEFAULT '',
                    error_code TEXT NOT NULL DEFAULT '',
                    receipt_json TEXT NOT NULL DEFAULT '',
                    owner TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_compensation_journal (
                    compensation_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    original_mutation_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    intent_json TEXT NOT NULL,
                    compensated_at TEXT NOT NULL DEFAULT '',
                    failed_at TEXT NOT NULL DEFAULT '',
                    error_code TEXT NOT NULL DEFAULT '',
                    receipt_json TEXT NOT NULL DEFAULT '',
                    owner TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _require_row(connection: sqlite3.Connection, mutation_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM runtime_mutation_journal WHERE mutation_id=?", (mutation_id,)
        ).fetchone()
        if row is None:
            raise PlaybookExecutionError("MUTATION_INTENT_NOT_FOUND", "Mutation intent was not prepared.")
        return row

    @staticmethod
    def _require_compensation_row(connection: sqlite3.Connection, compensation_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM runtime_compensation_journal WHERE compensation_id=?", (compensation_id,)
        ).fetchone()
        if row is None:
            raise PlaybookExecutionError(
                "COMPENSATION_INTENT_NOT_FOUND",
                "Compensation intent was not prepared.",
                {"compensation_id": compensation_id},
            )
        return row


@dataclass(frozen=True)
class MutationRecoveryResult:
    mutation_id: str
    state: str
    recovered: bool
    action: str


def recover_mutation(
    journal: MutationJournal,
    mutation_id: str,
    *,
    verify_applied: Callable[[MutationIntent], MutationReceipt | None],
) -> MutationRecoveryResult:
    record = journal.get(mutation_id)
    if record is None:
        raise PlaybookExecutionError("MUTATION_INTENT_NOT_FOUND", "Mutation intent was not prepared.")
    if record.state == MutationState.APPLYING.value:
        receipt = verify_applied(record.intent)
        if receipt is not None:
            updated = journal.record_applied(receipt)
            return MutationRecoveryResult(mutation_id, updated.state, True, "marked_applied")
        updated = journal.mark_approved(mutation_id, approval_id=record.approval_id)
        return MutationRecoveryResult(mutation_id, updated.state, True, "returned_to_approved")
    return MutationRecoveryResult(mutation_id, record.state, False, "unchanged")


def _mutation_record_from_row(row: sqlite3.Row) -> MutationJournalRecord:
    receipt_json = str(row["receipt_json"] or "")
    return MutationJournalRecord(
        intent=MutationIntent.from_dict(json.loads(str(row["intent_json"]))),
        state=str(row["state"]),
        approval_id=str(row["approval_id"]),
        approved_at=str(row["approved_at"]),
        applied_at=str(row["applied_at"]),
        failed_at=str(row["failed_at"]),
        error_code=str(row["error_code"]),
        receipt=MutationReceipt.from_dict(json.loads(receipt_json)) if receipt_json else None,
    )


def _compensation_record_from_row(row: sqlite3.Row) -> CompensationJournalRecord:
    receipt_json = str(row["receipt_json"] or "")
    return CompensationJournalRecord(
        intent=CompensationIntent.from_dict(json.loads(str(row["intent_json"]))),
        state=str(row["state"]),
        compensated_at=str(row["compensated_at"]),
        failed_at=str(row["failed_at"]),
        error_code=str(row["error_code"]),
        receipt=CompensationReceipt.from_dict(json.loads(receipt_json)) if receipt_json else None,
    )


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
