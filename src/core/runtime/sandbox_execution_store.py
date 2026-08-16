from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import PlaybookValidationError
from .events import utc_now_iso
from .playbook_registry import PlaybookSelectionPolicy, _contains_registry_secret
from .playbook_sandbox import (
    SANDBOX_EXECUTION_SCHEMA_VERSION,
    ReadOnlyPlaybookSandbox,
    SandboxExecutionRecord,
)

SANDBOX_EXECUTION_STORE_SCHEMA_VERSION = "sandbox-execution-store.v1"
SANDBOX_REPLAY_SCHEMA_VERSION = "sandbox-replay.v1"


@dataclass(frozen=True)
class SandboxAuditEvent:
    event_id: str
    event_type: str
    execution_id: str
    occurred_at: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    schema_version: str = SANDBOX_EXECUTION_STORE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class SandboxReplayResult:
    original_execution_id: str
    replay_execution_id: str
    matched: bool
    original_fingerprint: str
    replay_fingerprint: str
    differences: tuple[str, ...]
    status: str
    provenance: dict[str, Any]
    schema_version: str = SANDBOX_REPLAY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class SandboxExecutionStore:
    def __init__(self, path: Path | str, *, clock=utc_now_iso):
        self.path = Path(path)
        self.clock = clock

    def save(
        self,
        record: SandboxExecutionRecord,
        *,
        actor: str = "sandbox",
        source: str = "sandbox_execution_store",
        replay_result: SandboxReplayResult | None = None,
    ) -> dict[str, Any]:
        payload = record.to_dict()
        _assert_persisted_record_safe(payload)
        fingerprint = self.fingerprint(payload)
        safe_actor = _safe_actor(actor)
        persisted = {
            **payload,
            "fingerprint": fingerprint,
            "store_schema_version": SANDBOX_EXECUTION_STORE_SCHEMA_VERSION,
        }
        state = self._load_state()
        state["records"][record.execution_id] = persisted
        state["audit_events"].append(
            SandboxAuditEvent(
                event_id=_audit_event_id("saved", record.execution_id, self.clock(), len(state["audit_events"])),
                event_type="saved",
                execution_id=record.execution_id,
                occurred_at=self.clock(),
                source=source,
                sequence=len(state["audit_events"]),
                payload={
                    "actor": safe_actor,
                    "fingerprint": fingerprint,
                    "playbook_id": record.playbook_id,
                    "playbook_version": record.playbook_version,
                    "status": record.status,
                    **({"source_original_execution_id": replay_result.original_execution_id} if replay_result else {}),
                },
            ).to_dict()
        )
        if replay_result is not None:
            state["audit_events"].append(
                SandboxAuditEvent(
                    event_id=_audit_event_id("replay_result_saved", record.execution_id, self.clock(), len(state["audit_events"])),
                    event_type="replay_result_saved",
                    execution_id=record.execution_id,
                    occurred_at=self.clock(),
                    source=source,
                    sequence=len(state["audit_events"]),
                    payload={
                        "actor": safe_actor,
                        "original_execution_id": replay_result.original_execution_id,
                        "matched": replay_result.matched,
                        "original_fingerprint": replay_result.original_fingerprint,
                        "replay_fingerprint": replay_result.replay_fingerprint,
                        "differences": list(replay_result.differences),
                    },
                ).to_dict()
            )
        self._write_state(state)
        return _json_safe(persisted)

    def get(self, execution_id: str) -> dict[str, Any] | None:
        record = self._load_state()["records"].get(execution_id)
        return _json_safe(record) if record is not None else None

    def list(
        self,
        *,
        playbook_id: str | None = None,
        status: str | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records = list(self._load_state()["records"].values())
        if playbook_id is not None:
            records = [item for item in records if item.get("playbook_id") == playbook_id]
        if status is not None:
            records = [item for item in records if item.get("status") == status]
        if since is not None:
            records = [item for item in records if str(item.get("executed_at") or "") >= since]
        records = sorted(records, key=lambda item: (str(item.get("executed_at") or ""), str(item.get("execution_id") or "")))
        if limit is not None:
            records = records[: max(limit, 0)]
        return _json_safe(records)

    def audit_events(self, execution_id: str | None = None) -> list[dict[str, Any]]:
        events = self._load_state()["audit_events"]
        if execution_id is not None:
            events = [item for item in events if item.get("execution_id") == execution_id]
        return _json_safe(
            sorted(
                events,
                key=lambda item: (
                    int(item.get("sequence") or 0),
                    str(item.get("occurred_at") or ""),
                    str(item.get("event_id") or ""),
                ),
            )
        )

    def fingerprint(self, record: SandboxExecutionRecord | dict[str, Any]) -> str:
        payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
        canonical = _canonical_fingerprint_payload(payload)
        rendered = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    def compare(
        self,
        record_a: SandboxExecutionRecord | dict[str, Any],
        record_b: SandboxExecutionRecord | dict[str, Any],
    ) -> dict[str, Any]:
        payload_a = record_a.to_dict() if hasattr(record_a, "to_dict") else dict(record_a)
        payload_b = record_b.to_dict() if hasattr(record_b, "to_dict") else dict(record_b)
        differences = _difference_codes(payload_a, payload_b)
        return {
            "matched": not differences,
            "fingerprint_a": self.fingerprint(payload_a),
            "fingerprint_b": self.fingerprint(payload_b),
            "differences": differences,
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": SANDBOX_EXECUTION_STORE_SCHEMA_VERSION, "records": {}, "audit_events": []}
        with self.path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        return {
            "schema_version": state.get("schema_version") or SANDBOX_EXECUTION_STORE_SCHEMA_VERSION,
            "records": dict(state.get("records") or {}),
            "audit_events": list(state.get("audit_events") or []),
        }

    def _write_state(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(_json_safe(state), sort_keys=True, indent=2, ensure_ascii=True)
        if _contains_registry_secret(json.loads(rendered)):
            raise PlaybookValidationError("sandbox_execution_store.secret_value", "Sandbox store must not persist secrets.")
        self.path.write_text(rendered + "\n", encoding="utf-8")


class SandboxReplayService:
    def __init__(
        self,
        *,
        store: SandboxExecutionStore,
        sandbox: ReadOnlyPlaybookSandbox | None = None,
        clock=utc_now_iso,
    ):
        self.store = store
        self.sandbox = sandbox or ReadOnlyPlaybookSandbox(clock=clock)
        self.clock = clock

    def replay(
        self,
        execution_id: str,
        context: dict[str, Any] | None,
        *,
        plan: Any | None = None,
        policy: PlaybookSelectionPolicy | None = None,
        save_replay: bool = False,
    ) -> SandboxReplayResult:
        original = self.store.get(execution_id)
        if original is None:
            return self._blocked(execution_id, "missing_execution")
        if context is None:
            return self._blocked(execution_id, "missing_context", original=original)
        if plan is None:
            return self._blocked(execution_id, "missing_plan", original=original)

        replay_record = self.sandbox.execute(plan, context, policy=policy)
        original_fingerprint = str(original.get("fingerprint") or self.store.fingerprint(original))
        replay_fingerprint = self.store.fingerprint(replay_record)
        differences = tuple(self.store.compare(original, replay_record.to_dict())["differences"])
        result = SandboxReplayResult(
            original_execution_id=execution_id,
            replay_execution_id=replay_record.execution_id,
            matched=original_fingerprint == replay_fingerprint and not differences,
            original_fingerprint=original_fingerprint,
            replay_fingerprint=replay_fingerprint,
            differences=differences,
            status="completed",
            provenance={
                "replay_schema_version": SANDBOX_REPLAY_SCHEMA_VERSION,
                "source_execution_id": execution_id,
                "save_replay": save_replay,
                "policy_used": _policy_summary(policy),
            },
        )
        if save_replay:
            self.store.save(replay_record, actor="replay", source="sandbox_replay_service", replay_result=result)
        return result

    def compare_replay(
        self,
        execution_id: str,
        context: dict[str, Any] | None,
        *,
        plan: Any | None = None,
        policy: PlaybookSelectionPolicy | None = None,
    ) -> SandboxReplayResult:
        return self.replay(execution_id, context, plan=plan, policy=policy, save_replay=False)

    def _blocked(
        self,
        execution_id: str,
        reason: str,
        *,
        original: dict[str, Any] | None = None,
    ) -> SandboxReplayResult:
        original_fingerprint = ""
        if original is not None:
            original_fingerprint = str(original.get("fingerprint") or self.store.fingerprint(original))
        return SandboxReplayResult(
            original_execution_id=execution_id,
            replay_execution_id="",
            matched=False,
            original_fingerprint=original_fingerprint,
            replay_fingerprint="",
            differences=(reason,),
            status="blocked",
            provenance={
                "replay_schema_version": SANDBOX_REPLAY_SCHEMA_VERSION,
                "source_execution_id": execution_id,
                "blocked_reason": reason,
            },
        )


def _canonical_fingerprint_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = _strip_volatile(_json_safe(payload))
    return cleaned


def _strip_volatile(value: Any) -> Any:
    volatile_keys = {"execution_id", "executed_at", "generated_at", "fingerprint", "store_schema_version"}
    if isinstance(value, dict):
        return {key: _strip_volatile(item) for key, item in sorted(value.items()) if key not in volatile_keys}
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def _difference_codes(record_a: dict[str, Any], record_b: dict[str, Any]) -> tuple[str, ...]:
    differences: set[str] = set()
    if record_a.get("status") != record_b.get("status"):
        differences.add("status_changed")
    if record_a.get("playbook_version") != record_b.get("playbook_version"):
        differences.add("playbook_version_changed")
    if record_a.get("blocked_reasons") != record_b.get("blocked_reasons"):
        differences.add("blocker_changed")
    if record_a.get("redaction") != record_b.get("redaction"):
        differences.add("redaction_changed")
    if (record_a.get("provenance") or {}).get("context_schema_version") != (record_b.get("provenance") or {}).get("context_schema_version"):
        differences.add("context_schema_changed")
    if (record_a.get("provenance") or {}).get("context_ref") != (record_b.get("provenance") or {}).get("context_ref"):
        differences.add("context_ref_changed")
    steps_a = {item.get("step_id"): item for item in record_a.get("step_results") or []}
    steps_b = {item.get("step_id"): item for item in record_b.get("step_results") or []}
    if set(steps_a) != set(steps_b):
        differences.add("step_set_changed")
    for step_id in set(steps_a) & set(steps_b):
        left = steps_a[step_id]
        right = steps_b[step_id]
        if left.get("status") != right.get("status"):
            differences.add("step_status_changed")
        if left.get("blocked_reasons") != right.get("blocked_reasons"):
            differences.add("blocker_changed")
        if left.get("output_ref_or_value") != right.get("output_ref_or_value"):
            differences.add("output_changed")
    if not differences and _canonical_fingerprint_payload(record_a) != _canonical_fingerprint_payload(record_b):
        differences.add("record_changed")
    return tuple(sorted(differences))


def _assert_persisted_record_safe(payload: dict[str, Any]) -> None:
    if not payload.get("sandbox") or not payload.get("read_only"):
        raise PlaybookValidationError("sandbox_execution_store.not_sandbox", "Only read-only sandbox records may be persisted.")
    if payload.get("schema_version") != SANDBOX_EXECUTION_SCHEMA_VERSION:
        raise PlaybookValidationError("sandbox_execution_store.schema", "Unsupported sandbox execution schema.")
    if _contains_registry_secret(payload):
        raise PlaybookValidationError("sandbox_execution_store.secret_value", "Sandbox store must not persist secrets.")
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = ("raw_metrics_payload", "raw_transcript_body", "Authorization", "Bearer ", "SECRET_CANARY")
    if any(item in rendered for item in forbidden):
        raise PlaybookValidationError("sandbox_execution_store.raw_or_secret_value", "Sandbox store contains forbidden raw data.")


def _audit_event_id(event_type: str, execution_id: str, occurred_at: str, index: int) -> str:
    digest = hashlib.sha256(f"{event_type}:{execution_id}:{occurred_at}:{index}".encode("utf-8")).hexdigest()
    return f"sandbox_audit_{digest[:32]}"


def _policy_summary(policy: PlaybookSelectionPolicy | None) -> dict[str, Any]:
    selected = policy or PlaybookSelectionPolicy()
    return {
        "allow_deprecated": selected.allow_deprecated,
        "allow_mutations": selected.allow_mutations,
        "allow_raw_metrics": selected.allow_raw_metrics,
        "allow_raw_transcript": selected.allow_raw_transcript,
        "available_capabilities": sorted(selected.available_capabilities),
    }


def _safe_actor(actor: str) -> str:
    rendered = str(actor or "")
    if _contains_registry_secret({"actor": rendered}):
        return "redacted"
    if any(item in rendered for item in ("Authorization", "Bearer ", "SECRET_CANARY")):
        return "redacted"
    return rendered


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
