from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .approval_request_draft import SAFE_REQUESTED_ACTION_KINDS
from .errors import PlaybookValidationError
from .events import utc_now_iso
from .execution_readiness_report import ExecutionReadinessReportPolicy
from .playbook_registry import _contains_registry_secret

CONTROLLED_EXECUTOR_INPUT_SCHEMA_VERSION = "controlled-executor-input.v1"
CONTROLLED_EXECUTOR_RESULT_SCHEMA_VERSION = "controlled-executor-result.v1"
CONTROLLED_EXECUTOR_INTERFACE_VERSION = "controlled-executor-interface.v1"

CONTROLLED_EXECUTOR_MODES = ("no_op", "simulation", "validate_only")
CONTROLLED_EXECUTOR_RESULT_STATUSES = ("blocked", "failed_safe", "not_implemented", "simulated", "validated")
CONTROLLED_EXECUTOR_FORBIDDEN_SIDE_EFFECTS = (
    "ai_call",
    "approval_state_mutation",
    "browser_automation",
    "claim_mutation",
    "external_write",
    "production_mutation",
    "publish",
    "raw_metrics_default",
    "raw_transcript_default",
    "scraping",
    "send",
)
PRODUCTION_CAPABILITY_MARKERS = (
    "calendar" + ".event" + ".create",
    "website" + ".article" + ".publish",
    ".publish",
    ".create",
    ".update",
    ".delete",
    ".send",
    ".mutate",
)


@dataclass(frozen=True)
class ControlledExecutorPolicy:
    policy_id: str = "controlled-executor-default"
    version: str = "1.0.0"
    mode: str = "validate_only"
    allowed_side_effects: tuple[str, ...] = ()
    forbidden_side_effects: tuple[str, ...] = CONTROLLED_EXECUTOR_FORBIDDEN_SIDE_EFFECTS

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ControlledExecutorRedaction:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False
    execution_started: bool = False
    simulation_only: bool = True
    production_mutation_used: bool = False
    external_write_used: bool = False
    ai_call_used: bool = False


@dataclass(frozen=True)
class ControlledExecutorReason:
    reason_code: str
    severity: str
    subject_ref: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ControlledExecutorInput:
    input_id: str
    readiness_report_id: str
    preparation_id: str
    claim_id: str
    playbook_id: str
    playbook_version: str
    requested_action_kind: str
    mode: str
    allowed_side_effects: tuple[str, ...]
    forbidden_side_effects: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    subject_scope: dict[str, Any]
    provenance: dict[str, Any]
    redaction: ControlledExecutorRedaction
    created_at: str
    schema_version: str = CONTROLLED_EXECUTOR_INPUT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ControlledExecutorResult:
    result_id: str
    input_id: str
    status: str
    mode: str
    side_effects_used: tuple[str, ...]
    capabilities_checked: tuple[str, ...]
    blocked_reasons: tuple[ControlledExecutorReason, ...]
    output_summary: dict[str, Any]
    provenance: dict[str, Any]
    redaction: ControlledExecutorRedaction
    created_at: str
    schema_version: str = CONTROLLED_EXECUTOR_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class ControlledExecutorInputBuilder:
    def __init__(self, *, clock=utc_now_iso):
        self.clock = clock

    def build(
        self,
        readiness_report: Any,
        preparation_record: Any,
        claim: Any,
        *,
        policy: ControlledExecutorPolicy | None = None,
        mode: str | None = None,
    ) -> ControlledExecutorInput:
        selected_policy = policy or ControlledExecutorPolicy()
        selected_mode = str(mode or selected_policy.mode or "")
        report = _payload(readiness_report)
        preparation = _payload(preparation_record)
        claim_payload = _payload(claim)
        created_at = self.clock()
        input_record = ControlledExecutorInput(
            input_id=_input_id(report, preparation, claim_payload, selected_mode, selected_policy, created_at),
            readiness_report_id=str(report.get("report_id") or ""),
            preparation_id=str(preparation.get("preparation_id") or ""),
            claim_id=str(claim_payload.get("claim_id") or ""),
            playbook_id=str(preparation.get("playbook_id") or ""),
            playbook_version=str(preparation.get("playbook_version") or ""),
            requested_action_kind=str(preparation.get("requested_action_kind") or ""),
            mode=selected_mode,
            allowed_side_effects=tuple(sorted(str(item) for item in selected_policy.allowed_side_effects if str(item))),
            forbidden_side_effects=tuple(sorted(set(str(item) for item in selected_policy.forbidden_side_effects if str(item)))),
            required_capabilities=tuple(sorted(str(item) for item in preparation.get("required_capabilities") or () if str(item))),
            subject_scope=_subject_scope(report, preparation, claim_payload),
            provenance=_input_provenance(report, preparation, claim_payload, selected_policy),
            redaction=ControlledExecutorRedaction(),
            created_at=created_at,
        )
        _assert_input_safe(input_record.to_dict())
        return input_record


class ControlledExecutor:
    def __init__(self, *, clock=utc_now_iso):
        self.clock = clock

    def validate_input(self, input_record: Any) -> tuple[ControlledExecutorReason, ...]:
        payload = _payload(input_record)
        reasons: list[ControlledExecutorReason] = []
        mode = str(payload.get("mode") or "")
        if mode not in CONTROLLED_EXECUTOR_MODES:
            reasons.append(_error("unsupported_mode", "input.mode", {"mode": mode}))
        if any(str(item) for item in payload.get("allowed_side_effects") or ()):
            reasons.append(_error("side_effects_not_allowed", "input.allowed_side_effects"))
        provenance = payload.get("provenance") or {}
        if str(provenance.get("readiness_status") or "") != "ready":
            reasons.append(_error("readiness_not_ready", "input.provenance.readiness_status", {"status": str(provenance.get("readiness_status") or "")}))
        if str(provenance.get("preparation_status") or "") != "ready":
            reasons.append(_error("preparation_not_ready", "input.provenance.preparation_status", {"status": str(provenance.get("preparation_status") or "")}))
        if str(provenance.get("claim_status") or "") != "claimed":
            reasons.append(_error("claim_not_active", "input.provenance.claim_status", {"status": str(provenance.get("claim_status") or "")}))
        lease = str(provenance.get("lease_expires_at") or "")
        if lease and _parse_time(lease) <= _parse_time(str(payload.get("created_at") or "")):
            reasons.append(_error("claim_expired", "input.provenance.lease_expires_at"))
        missing_forbidden = sorted(set(CONTROLLED_EXECUTOR_FORBIDDEN_SIDE_EFFECTS) - set(payload.get("forbidden_side_effects") or ()))
        if missing_forbidden:
            reasons.append(_error("forbidden_side_effects_missing", "input.forbidden_side_effects", {"missing": missing_forbidden}))
        action = str(payload.get("requested_action_kind") or "")
        if action not in SAFE_REQUESTED_ACTION_KINDS:
            reasons.append(_error("unsafe_action_kind", "input.requested_action_kind", {"requested_action_kind": action}))
        for capability in payload.get("required_capabilities") or ():
            rendered = str(capability)
            if _is_production_capability(rendered):
                reasons.append(_error("production_capability_not_supported", f"capability:{rendered}"))
        reasons.extend(_redaction_reasons("input", payload))
        if _contains_forbidden_data(payload):
            reasons.append(_error("unsafe_payload", "input"))
        return tuple(sorted(reasons, key=_reason_key))

    def run(self, input_record: Any) -> ControlledExecutorResult:
        payload = _payload(input_record)
        created_at = self.clock()
        reasons = self.validate_input(payload)
        mode = str(payload.get("mode") or "")
        if reasons:
            status = "blocked"
            summary = {"checked": True, "side_effects": False}
        elif mode == "validate_only":
            status = "validated"
            summary = {"validated": True, "side_effects": False}
        elif mode == "no_op":
            status = "simulated"
            summary = {
                "completed": True,
                "mode": "no_op",
                "side_effects": False,
                "production_mutation_used": False,
                "external_write_used": False,
                "ai_call_used": False,
                "raw_access_used": False,
            }
        elif mode == "simulation":
            status = "simulated"
            summary = {
                "mode": "simulation",
                "side_effects": False,
                "simulated": True,
                "subject_scope": _stable_scope(payload.get("subject_scope") or {}),
            }
        else:
            status = "not_implemented"
            reasons = (_error("unsupported_mode", "input.mode", {"mode": mode}),)
            summary = {"side_effects": False}
        result = ControlledExecutorResult(
            result_id=_result_id(payload, status, created_at),
            input_id=str(payload.get("input_id") or ""),
            status=status,
            mode=mode,
            side_effects_used=(),
            capabilities_checked=tuple(sorted(str(item) for item in payload.get("required_capabilities") or () if str(item) and not _is_production_capability(str(item)))),
            blocked_reasons=reasons,
            output_summary=dict(sorted(summary.items())),
            provenance={
                "controlled_executor_interface_version": CONTROLLED_EXECUTOR_INTERFACE_VERSION,
                "input_ref": {"id": str(payload.get("input_id") or ""), "schema_version": str(payload.get("schema_version") or "")},
            },
            redaction=ControlledExecutorRedaction(),
            created_at=created_at,
        )
        _assert_result_safe(result.to_dict())
        return result

    def execute(self, input_record: Any) -> ControlledExecutorResult:
        return self.run(input_record)


def _input_provenance(
    report: dict[str, Any],
    preparation: dict[str, Any],
    claim: dict[str, Any],
    policy: ControlledExecutorPolicy,
) -> dict[str, Any]:
    return dict(
        sorted(
            {
                "claim_ref": _ref(claim, "claim_id"),
                "claim_status": str(claim.get("status") or ""),
                "controlled_executor_interface_version": CONTROLLED_EXECUTOR_INTERFACE_VERSION,
                "policy": policy.to_dict(),
                "preparation_ref": _ref(preparation, "preparation_id"),
                "preparation_status": str(preparation.get("store_status") or preparation.get("status") or ""),
                "readiness_report_ref": _ref(report, "report_id"),
                "readiness_status": str(report.get("status") or ""),
                "lease_expires_at": str(claim.get("lease_expires_at") or ""),
            }.items()
        )
    )


def _subject_scope(report: dict[str, Any], preparation: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any]:
    scope = dict(report.get("subject_scope") or {})
    scope.update(
        {
            "claim_id": str(claim.get("claim_id") or scope.get("claim_id") or ""),
            "idempotency_key": str(preparation.get("idempotency_key") or claim.get("idempotency_key") or scope.get("idempotency_key") or ""),
            "playbook_id": str(preparation.get("playbook_id") or scope.get("playbook_id") or ""),
            "playbook_version": str(preparation.get("playbook_version") or scope.get("playbook_version") or ""),
            "preparation_id": str(preparation.get("preparation_id") or scope.get("preparation_id") or ""),
            "readiness_report_id": str(report.get("report_id") or ""),
            "requested_action_kind": str(preparation.get("requested_action_kind") or scope.get("requested_action_kind") or ""),
        }
    )
    return _stable_scope(scope)


def _stable_scope(scope: dict[str, Any]) -> dict[str, Any]:
    return dict(sorted((str(key), _safe_value(value)) for key, value in scope.items() if value not in (None, "")))


def _ref(payload: dict[str, Any], id_key: str) -> dict[str, str]:
    if not payload:
        return {}
    return {"id": str(payload.get(id_key) or ""), "schema_version": str(payload.get("schema_version") or "")}


def _input_id(report: dict[str, Any], preparation: dict[str, Any], claim: dict[str, Any], mode: str, policy: ControlledExecutorPolicy, created_at: str) -> str:
    seed = {
        "claim_id": claim.get("claim_id") or "",
        "created_at": created_at,
        "mode": mode,
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
        "preparation_id": preparation.get("preparation_id") or "",
        "readiness_report_id": report.get("report_id") or "",
    }
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"controlled_executor_input_{digest[:32]}"


def _result_id(payload: dict[str, Any], status: str, created_at: str) -> str:
    seed = {"created_at": created_at, "input_id": payload.get("input_id") or "", "mode": payload.get("mode") or "", "status": status}
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"controlled_executor_result_{digest[:32]}"


def _is_production_capability(capability: str) -> bool:
    return any(marker in capability for marker in PRODUCTION_CAPABILITY_MARKERS)


def _redaction_reasons(label: str, payload: dict[str, Any]) -> list[ControlledExecutorReason]:
    reasons = []
    redaction = payload.get("redaction") or {}
    for key in (
        "ai_call_used",
        "execution_started",
        "external_write_used",
        "production_mutation_used",
        "provider_headers_included",
        "raw_metrics_included",
        "raw_transcript_included",
        "secrets_included",
    ):
        if redaction.get(key, False) is not False:
            reasons.append(_error("unsafe_redaction", f"{label}.redaction.{key}"))
    return reasons


def _payload(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return _json_safe(dict(value))


def _safe_value(value: Any) -> Any:
    rendered = _json_safe(value)
    if _contains_registry_secret({"value": rendered}) or _contains_forbidden_data({"value": rendered}):
        return "redacted"
    return rendered


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value or "1970-01-01T00:00:00Z").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _assert_input_safe(payload: dict[str, Any]) -> None:
    if str(payload.get("mode") or "") not in CONTROLLED_EXECUTOR_MODES:
        return
    if _contains_registry_secret(payload) or _contains_forbidden_data(payload):
        raise PlaybookValidationError("controlled_executor_input.unsafe_payload", "Controlled executor input contains unsafe data.")
    _assert_redaction_safe(payload, "controlled_executor_input")


def _assert_result_safe(payload: dict[str, Any]) -> None:
    if str(payload.get("status") or "") not in CONTROLLED_EXECUTOR_RESULT_STATUSES:
        raise PlaybookValidationError("controlled_executor_result.invalid_status", "Controlled executor result status is invalid.")
    if payload.get("side_effects_used"):
        raise PlaybookValidationError("controlled_executor_result.side_effect", "Controlled executor result recorded side effects.")
    if _contains_registry_secret(payload) or _contains_forbidden_data(payload):
        raise PlaybookValidationError("controlled_executor_result.unsafe_payload", "Controlled executor result contains unsafe data.")
    _assert_redaction_safe(payload, "controlled_executor_result")


def _assert_redaction_safe(payload: dict[str, Any], code: str) -> None:
    redaction = payload.get("redaction") or {}
    for key in (
        "ai_call_used",
        "external_write_used",
        "production_mutation_used",
        "provider_headers_included",
        "raw_metrics_included",
        "raw_transcript_included",
        "secrets_included",
    ):
        if redaction.get(key, False) is not False:
            raise PlaybookValidationError(f"{code}.unsafe_redaction", "Controlled executor redaction is unsafe.")


def _contains_forbidden_data(payload: dict[str, Any]) -> bool:
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = (
        "Authorization",
        "Bearer",
        "SECRET_CANARY",
        "access_token",
        "api_key",
        "oauth_token",
        "raw_metrics_payload",
        "raw_transcript_body",
        "refresh_token",
    )
    markers = (
        "ai_invoked",
        "browser_automation_invoked",
        "external_write_invoked",
        "network_invoked",
        "production_executor_invoked",
        "scraping_invoked",
    )
    return any(item in rendered for item in forbidden) or any(item in rendered.lower() for item in markers)


def _error(reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ControlledExecutorReason:
    return ControlledExecutorReason(reason_code=reason_code, severity="error", subject_ref=subject_ref, details=details or {})


def _reason_key(reason: ControlledExecutorReason) -> tuple[str, str, str]:
    return (reason.severity, reason.subject_ref, reason.reason_code)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
