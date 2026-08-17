from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .approval_request_draft import SAFE_REQUESTED_ACTION_KINDS
from .events import utc_now_iso
from .errors import PlaybookValidationError
from .execution_attempt_ledger import ATTEMPT_MODES, ATTEMPT_STATUSES
from .playbook_registry import _contains_registry_secret
from .promotion_gate import UNSAFE_NEXT_ACTION_MARKERS

EXECUTION_READINESS_REPORT_SCHEMA_VERSION = "execution-readiness-report.v1"
EXECUTION_READINESS_REPORTER_VERSION = "execution-readiness-reporter.v1"

READINESS_STATUSES = ("blocked", "informational", "needs_review", "ready")
READINESS_SAFE_NEXT_ACTIONS = (
    "cancel_preparation",
    "expire_claim",
    "inspect_readiness",
    "open_non_production_attempt",
    "release_claim",
    "replay_sandbox",
    "request_manual_review",
)
UNSAFE_READINESS_ACTIONS = ("execute_production", "publish", "mutate", "send", "call_ai")


@dataclass(frozen=True)
class ExecutionReadinessReportPolicy:
    policy_id: str = "execution-readiness-default"
    version: str = "1.0.0"
    require_approved: bool = True
    require_promotion_eligible: bool = True
    require_eligibility_eligible: bool = True
    require_preparation_ready: bool = True
    require_active_claim: bool = False
    require_no_active_attempt: bool = True
    allow_noop_attempts: bool = True
    allow_warnings: bool = False
    allow_needs_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionReadinessRedaction:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False
    approval_state_mutated: bool = False
    execution_started: bool = False
    production_mutation_used: bool = False
    external_write_used: bool = False
    ai_call_used: bool = False


@dataclass(frozen=True)
class ExecutionReadinessCheck:
    check_id: str
    status: str
    severity: str
    reason_code: str
    subject_ref: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ExecutionReadinessReport:
    report_id: str
    status: str
    subject_scope: dict[str, Any]
    approval_summary: dict[str, Any]
    promotion_summary: dict[str, Any]
    eligibility_summary: dict[str, Any]
    preparation_summary: dict[str, Any]
    claim_summary: dict[str, Any]
    attempt_summary: dict[str, Any]
    consistency_checks: tuple[ExecutionReadinessCheck, ...]
    blockers: tuple[ExecutionReadinessCheck, ...]
    warnings: tuple[ExecutionReadinessCheck, ...]
    safe_next_actions: tuple[str, ...]
    provenance: dict[str, Any]
    redaction: ExecutionReadinessRedaction
    generated_at: str
    schema_version: str = EXECUTION_READINESS_REPORT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class ExecutionReadinessReporter:
    def __init__(self, *, clock=utc_now_iso):
        self.clock = clock

    def build(
        self,
        *,
        approval_request: Any | None = None,
        promotion_decision: Any | None = None,
        eligibility_decision: Any | None = None,
        preparation_record: Any | None = None,
        claim: Any | None = None,
        attempt: Any | None = None,
        policy: ExecutionReadinessReportPolicy | None = None,
    ) -> ExecutionReadinessReport:
        selected_policy = policy or ExecutionReadinessReportPolicy()
        generated_at = self.clock()
        approval = _payload(approval_request)
        promotion = _payload(promotion_decision)
        eligibility = _payload(eligibility_decision)
        preparation = _payload(preparation_record)
        claim_payload = _payload(claim)
        attempt_payload = _payload(attempt)
        checks: list[ExecutionReadinessCheck] = []
        checks.extend(_object_status_checks(approval, promotion, eligibility, preparation, selected_policy))
        checks.extend(_consistency_checks(approval, promotion, eligibility, preparation, claim_payload, attempt_payload))
        checks.extend(_claim_checks(claim_payload, preparation, selected_policy, generated_at))
        checks.extend(_attempt_checks(attempt_payload, preparation, claim_payload, selected_policy))
        checks.extend(_redaction_checks(approval, promotion, eligibility, preparation, claim_payload, attempt_payload))
        checks.extend(_marker_checks(approval, promotion, eligibility, preparation, claim_payload, attempt_payload))
        checks = sorted(checks, key=_check_key)
        blockers = tuple(check for check in checks if check.severity == "error")
        warnings = tuple(check for check in checks if check.severity == "warning")
        status = _report_status(blockers, warnings, selected_policy, attempt_payload)
        report = ExecutionReadinessReport(
            report_id=_report_id(approval, promotion, eligibility, preparation, claim_payload, attempt_payload, selected_policy, generated_at),
            status=status,
            subject_scope=_subject_scope(approval, promotion, eligibility, preparation, claim_payload, attempt_payload),
            approval_summary=_approval_summary(approval),
            promotion_summary=_promotion_summary(promotion),
            eligibility_summary=_eligibility_summary(eligibility),
            preparation_summary=_preparation_summary(preparation),
            claim_summary=_claim_summary(claim_payload, generated_at),
            attempt_summary=_attempt_summary(attempt_payload),
            consistency_checks=tuple(checks),
            blockers=blockers,
            warnings=warnings,
            safe_next_actions=_safe_next_actions(status, claim_payload, attempt_payload),
            provenance=_provenance(approval, promotion, eligibility, preparation, claim_payload, attempt_payload, selected_policy),
            redaction=ExecutionReadinessRedaction(),
            generated_at=generated_at,
        )
        _assert_report_safe(report.to_dict())
        return report

    def summarize(self, report: ExecutionReadinessReport) -> dict[str, Any]:
        return {
            "blockers": [check.reason_code for check in report.blockers],
            "report_id": report.report_id,
            "safe_next_actions": list(report.safe_next_actions),
            "status": report.status,
            "warnings": [check.reason_code for check in report.warnings],
        }


def _object_status_checks(
    approval: dict[str, Any],
    promotion: dict[str, Any],
    eligibility: dict[str, Any],
    preparation: dict[str, Any],
    policy: ExecutionReadinessReportPolicy,
) -> list[ExecutionReadinessCheck]:
    checks: list[ExecutionReadinessCheck] = []
    checks.extend(_required_status_check("approval", approval, "approved", policy.require_approved))
    checks.extend(_required_status_check("promotion", promotion, "eligible", policy.require_promotion_eligible))
    checks.extend(_required_status_check("eligibility", eligibility, "eligible", policy.require_eligibility_eligible))
    checks.extend(_required_status_check("preparation", preparation, "ready", policy.require_preparation_ready))
    return checks


def _required_status_check(label: str, payload: dict[str, Any], expected: str, required: bool) -> list[ExecutionReadinessCheck]:
    if not payload:
        return [_check("error" if required else "warning", f"{label}_missing", label)]
    status = _status_of(payload)
    if required and status != expected:
        return [_check("error", f"{label}_{status or 'missing'}_blocks", f"{label}.status", {"status": status})]
    if not required and status and status != expected:
        return [_check("warning", f"{label}_{status}", f"{label}.status", {"status": status})]
    return [_check("info", f"{label}_{expected}", f"{label}.status")]


def _consistency_checks(
    approval: dict[str, Any],
    promotion: dict[str, Any],
    eligibility: dict[str, Any],
    preparation: dict[str, Any],
    claim: dict[str, Any],
    attempt: dict[str, Any],
) -> list[ExecutionReadinessCheck]:
    checks: list[ExecutionReadinessCheck] = []
    checks.extend(_match("approval_id", approval.get("approval_id"), preparation.get("approval_id"), "preparation.approval_id"))
    checks.extend(_match("approval_id", approval.get("approval_id"), eligibility.get("subject_approval_id"), "eligibility.subject_approval_id"))
    checks.extend(_match("promotion_decision_id", promotion.get("decision_id"), preparation.get("promotion_decision_id"), "preparation.promotion_decision_id"))
    checks.extend(_match("promotion_decision_id", promotion.get("decision_id"), eligibility.get("subject_promotion_decision_id"), "eligibility.subject_promotion_decision_id"))
    checks.extend(_match("plan_id", eligibility.get("subject_plan_id"), preparation.get("plan_id"), "preparation.plan_id"))
    checks.extend(_match("playbook_id", _scope_value(approval, "playbook_id"), preparation.get("playbook_id"), "preparation.playbook_id"))
    checks.extend(_match("playbook_version", _scope_value(approval, "playbook_version"), preparation.get("playbook_version"), "preparation.playbook_version"))
    checks.extend(_match("requested_action_kind", approval.get("requested_action_kind"), eligibility.get("requested_action_kind"), "eligibility.requested_action_kind"))
    checks.extend(_match("requested_action_kind", approval.get("requested_action_kind"), preparation.get("requested_action_kind"), "preparation.requested_action_kind"))
    checks.extend(_match("preparation_id", preparation.get("preparation_id"), claim.get("preparation_id"), "claim.preparation_id"))
    checks.extend(_match("preparation_id", preparation.get("preparation_id"), attempt.get("preparation_id"), "attempt.preparation_id"))
    checks.extend(_match("claim_id", claim.get("claim_id"), attempt.get("claim_id"), "attempt.claim_id"))
    checks.extend(_match("idempotency_key", preparation.get("idempotency_key"), claim.get("idempotency_key"), "claim.idempotency_key"))
    checks.extend(_match("idempotency_key", preparation.get("idempotency_key"), attempt.get("idempotency_key"), "attempt.idempotency_key"))
    checks.extend(_match("attempt_playbook_id", preparation.get("playbook_id"), attempt.get("playbook_id"), "attempt.playbook_id"))
    checks.extend(_match("attempt_playbook_version", preparation.get("playbook_version"), attempt.get("playbook_version"), "attempt.playbook_version"))
    checks.extend(_match("attempt_requested_action_kind", preparation.get("requested_action_kind"), attempt.get("requested_action_kind"), "attempt.requested_action_kind"))
    action = str(approval.get("requested_action_kind") or preparation.get("requested_action_kind") or attempt.get("requested_action_kind") or "")
    if action and action not in SAFE_REQUESTED_ACTION_KINDS:
        checks.append(_check("error", "unsafe_action_kind", "requested_action_kind", {"requested_action_kind": action}))
    if any(marker in action for marker in UNSAFE_NEXT_ACTION_MARKERS):
        checks.append(_check("error", "unsafe_action_omitted", "requested_action_kind"))
    return checks


def _match(label: str, expected: Any, actual: Any, subject_ref: str) -> list[ExecutionReadinessCheck]:
    left = str(expected or "")
    right = str(actual or "")
    if not left or not right:
        return []
    if left != right:
        return [_check("error", f"{label}_mismatch", subject_ref, {"actual": right, "expected": left})]
    return [_check("info", f"{label}_matched", subject_ref)]


def _claim_checks(claim: dict[str, Any], preparation: dict[str, Any], policy: ExecutionReadinessReportPolicy, now: str) -> list[ExecutionReadinessCheck]:
    if not claim:
        if policy.require_active_claim:
            return [_check("error", "claim_missing", "claim")]
        return [_check("warning", "claim_missing_optional", "claim")]
    status = str(claim.get("status") or "")
    if policy.require_active_claim and status != "claimed":
        return [_check("error", f"claim_{status or 'missing'}_blocks", "claim.status")]
    checks = [_check("info" if status == "claimed" else "warning", f"claim_{status}", "claim.status")]
    if status == "claimed" and _parse_time(str(claim.get("lease_expires_at") or "")) <= _parse_time(now):
        severity = "error" if policy.require_active_claim else "warning"
        checks.append(_check(severity, "claim_expired", "claim.lease_expires_at"))
    return checks


def _attempt_checks(attempt: dict[str, Any], preparation: dict[str, Any], claim: dict[str, Any], policy: ExecutionReadinessReportPolicy) -> list[ExecutionReadinessCheck]:
    if not attempt:
        return [_check("info", "attempt_missing_optional", "attempt")]
    checks: list[ExecutionReadinessCheck] = []
    mode = str(attempt.get("mode") or "")
    status = str(attempt.get("status") or "")
    if mode not in ATTEMPT_MODES:
        checks.append(_check("error", "attempt_mode_unsupported", "attempt.mode", {"mode": mode}))
    else:
        checks.append(_check("info", "attempt_mode_non_production", "attempt.mode", {"mode": mode}))
    if status not in ATTEMPT_STATUSES:
        checks.append(_check("error", "attempt_status_unsupported", "attempt.status", {"status": status}))
    elif status in {"failed_safe", "blocked"} and not policy.allow_noop_attempts:
        checks.append(_check("error", f"attempt_{status}_blocks", "attempt.status"))
    elif status == "opened" and policy.require_no_active_attempt:
        checks.append(_check("warning", "active_attempt_present", "attempt.status"))
    else:
        checks.append(_check("info", f"attempt_{status}", "attempt.status"))
    rendered_status = json.dumps({"mode": mode, "status": status, "result": attempt.get("result") or {}}, sort_keys=True)
    if any(marker in rendered_status for marker in ("production_completed", "production_failed", "published", "mutated", "executed")):
        checks.append(_check("error", "production_status_marker", "attempt.status"))
    return checks


def _redaction_checks(*payloads: dict[str, Any]) -> list[ExecutionReadinessCheck]:
    checks = []
    for label, payload in zip(("approval", "promotion", "eligibility", "preparation", "claim", "attempt"), payloads):
        if not payload:
            continue
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
                checks.append(_check("error", "unsafe_redaction", f"{label}.redaction.{key}"))
        if _contains_forbidden_data(payload):
            checks.append(_check("error", "unsafe_payload", label))
    return checks


def _marker_checks(*payloads: dict[str, Any]) -> list[ExecutionReadinessCheck]:
    rendered = json.dumps(payloads, sort_keys=True).lower()
    markers = (
        "production_executor_invoked",
        "ai_invoked",
        "llm_call",
        "browser_automation_invoked",
        "scraping_invoked",
        "network_invoked",
        "external_write_invoked",
    )
    return [_check("error", "forbidden_marker_present", "input")] if any(marker in rendered for marker in markers) else []


def _report_status(
    blockers: tuple[ExecutionReadinessCheck, ...],
    warnings: tuple[ExecutionReadinessCheck, ...],
    policy: ExecutionReadinessReportPolicy,
    attempt: dict[str, Any],
) -> str:
    if blockers:
        return "blocked"
    if warnings:
        if policy.allow_needs_review:
            return "needs_review"
        if not policy.allow_warnings:
            return "blocked"
    if attempt and str(attempt.get("status") or "") in {"completed_noop", "cancelled"} and not policy.require_active_claim:
        if not policy.require_approved and not policy.require_promotion_eligible and not policy.require_eligibility_eligible and not policy.require_preparation_ready:
            return "informational"
    return "ready"


def _safe_next_actions(status: str, claim: dict[str, Any], attempt: dict[str, Any]) -> tuple[str, ...]:
    actions = {"inspect_readiness"}
    if status == "needs_review":
        actions.add("request_manual_review")
    if status in {"ready", "informational"}:
        actions.add("replay_sandbox")
    if status == "ready" and not attempt:
        actions.add("open_non_production_attempt")
    if claim and str(claim.get("status") or "") == "claimed":
        actions.update(("expire_claim", "release_claim"))
    return tuple(action for action in READINESS_SAFE_NEXT_ACTIONS if action in actions)


def _subject_scope(
    approval: dict[str, Any],
    promotion: dict[str, Any],
    eligibility: dict[str, Any],
    preparation: dict[str, Any],
    claim: dict[str, Any],
    attempt: dict[str, Any],
) -> dict[str, Any]:
    scope = {
        "approval_id": str(approval.get("approval_id") or preparation.get("approval_id") or ""),
        "attempt_id": str(attempt.get("attempt_id") or ""),
        "claim_id": str(claim.get("claim_id") or attempt.get("claim_id") or ""),
        "eligibility_decision_id": str(eligibility.get("decision_id") or preparation.get("eligibility_decision_id") or ""),
        "idempotency_key": str(preparation.get("idempotency_key") or claim.get("idempotency_key") or attempt.get("idempotency_key") or ""),
        "plan_id": str(preparation.get("plan_id") or eligibility.get("subject_plan_id") or ""),
        "playbook_id": str(preparation.get("playbook_id") or attempt.get("playbook_id") or ""),
        "playbook_version": str(preparation.get("playbook_version") or attempt.get("playbook_version") or ""),
        "preparation_id": str(preparation.get("preparation_id") or claim.get("preparation_id") or attempt.get("preparation_id") or ""),
        "promotion_decision_id": str(promotion.get("decision_id") or preparation.get("promotion_decision_id") or ""),
        "requested_action_kind": str(preparation.get("requested_action_kind") or approval.get("requested_action_kind") or ""),
    }
    return dict(sorted((key, value) for key, value in scope.items() if value))


def _approval_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return _summary(payload, ("approval_id", "packet_id", "requested_action_kind", "reviewer_role", "status"))


def _promotion_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = _summary(payload, ("decision_id", "policy_id", "policy_version", "status", "subject_execution_id"))
    summary["eligible_next_actions"] = _filter_safe_actions(payload.get("eligible_next_actions") or ())
    return summary


def _eligibility_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return _summary(payload, ("decision_id", "requested_action_kind", "status", "subject_approval_id", "subject_plan_id", "subject_promotion_decision_id"))


def _preparation_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return _summary(payload, ("approval_id", "idempotency_key", "plan_fingerprint", "plan_id", "playbook_id", "playbook_version", "preparation_id", "promotion_decision_id", "requested_action_kind", "status", "store_status"))


def _claim_summary(payload: dict[str, Any], now: str) -> dict[str, Any]:
    summary = _summary(payload, ("claim_id", "claimant_id", "idempotency_key", "lease_expires_at", "preparation_id", "status"))
    if summary:
        summary["active"] = payload.get("status") == "claimed" and _parse_time(str(payload.get("lease_expires_at") or "")) > _parse_time(now)
    return summary


def _attempt_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = _summary(payload, ("attempt_id", "claim_id", "completed_at", "idempotency_key", "mode", "playbook_id", "playbook_version", "preparation_id", "requested_action_kind", "started_at", "status"))
    if summary and payload.get("result"):
        result = payload.get("result") or {}
        summary["result"] = {
            key: result.get(key)
            for key in ("completed", "side_effects", "production_mutation_used", "external_write_used", "ai_call_used", "raw_access_used")
            if key in result
        }
    return summary


def _summary(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return dict(sorted((key, _json_safe(payload.get(key))) for key in keys if payload.get(key) not in (None, "")))


def _filter_safe_actions(actions: Any) -> tuple[str, ...]:
    safe = []
    for action in actions:
        rendered = str(action)
        if rendered in READINESS_SAFE_NEXT_ACTIONS and not any(marker in rendered for marker in UNSAFE_READINESS_ACTIONS):
            safe.append(rendered)
    return tuple(sorted(set(safe)))


def _provenance(
    approval: dict[str, Any],
    promotion: dict[str, Any],
    eligibility: dict[str, Any],
    preparation: dict[str, Any],
    claim: dict[str, Any],
    attempt: dict[str, Any],
    policy: ExecutionReadinessReportPolicy,
) -> dict[str, Any]:
    return dict(
        sorted(
            {
                "approval_ref": _ref(approval, "approval_id"),
                "attempt_ref": _ref(attempt, "attempt_id"),
                "claim_ref": _ref(claim, "claim_id"),
                "eligibility_ref": _ref(eligibility, "decision_id"),
                "preparation_ref": _ref(preparation, "preparation_id"),
                "promotion_ref": _ref(promotion, "decision_id"),
                "policy": policy.to_dict(),
                "reporter_version": EXECUTION_READINESS_REPORTER_VERSION,
            }.items()
        )
    )


def _ref(payload: dict[str, Any], id_key: str) -> dict[str, str]:
    if not payload:
        return {}
    return {"id": str(payload.get(id_key) or ""), "schema_version": str(payload.get("schema_version") or "")}


def _report_id(
    approval: dict[str, Any],
    promotion: dict[str, Any],
    eligibility: dict[str, Any],
    preparation: dict[str, Any],
    claim: dict[str, Any],
    attempt: dict[str, Any],
    policy: ExecutionReadinessReportPolicy,
    generated_at: str,
) -> str:
    seed = {
        "approval_id": approval.get("approval_id") or "",
        "attempt_id": attempt.get("attempt_id") or "",
        "claim_id": claim.get("claim_id") or "",
        "eligibility_decision_id": eligibility.get("decision_id") or "",
        "generated_at": generated_at,
        "preparation_id": preparation.get("preparation_id") or "",
        "promotion_decision_id": promotion.get("decision_id") or "",
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
    }
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"execution_readiness_report_{digest[:32]}"


def _check(severity: str, reason_code: str, subject_ref: str, details: dict[str, Any] | None = None) -> ExecutionReadinessCheck:
    status = "passed" if severity == "info" else "warning" if severity == "warning" else "failed"
    seed = {"reason_code": reason_code, "severity": severity, "subject_ref": subject_ref, "details": details or {}}
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return ExecutionReadinessCheck(
        check_id=f"execution_readiness_check_{digest[:24]}",
        status=status,
        severity=severity,
        reason_code=reason_code,
        subject_ref=subject_ref,
        details=details or {},
    )


def _check_key(check: ExecutionReadinessCheck) -> tuple[str, str, str, str]:
    severity_order = {"error": "0", "warning": "1", "info": "2"}
    return (severity_order.get(check.severity, "9"), check.subject_ref, check.reason_code, check.check_id)


def _scope_value(payload: dict[str, Any], key: str) -> str:
    return str((payload.get("scope") or {}).get(key) or "")


def _status_of(payload: dict[str, Any]) -> str:
    return str(payload.get("store_status") or payload.get("status") or "")


def _payload(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return _json_safe(dict(value))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value or "1970-01-01T00:00:00Z").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _assert_report_safe(payload: dict[str, Any]) -> None:
    if str(payload.get("status") or "") not in READINESS_STATUSES:
        raise PlaybookValidationError("execution_readiness_report.invalid_status", "Execution readiness report status is invalid.")
    if _contains_registry_secret(payload) or _contains_forbidden_data(payload):
        raise PlaybookValidationError("execution_readiness_report.unsafe_payload", "Execution readiness report contains unsafe data.")
    redaction = payload.get("redaction") or {}
    for key in (
        "ai_call_used",
        "approval_state_mutated",
        "execution_started",
        "external_write_used",
        "production_mutation_used",
        "provider_headers_included",
        "raw_metrics_included",
        "raw_transcript_included",
        "secrets_included",
    ):
        if redaction.get(key, False) is not False:
            raise PlaybookValidationError("execution_readiness_report.unsafe_redaction", "Execution readiness report redaction is unsafe.")
    if any(action not in READINESS_SAFE_NEXT_ACTIONS for action in payload.get("safe_next_actions") or ()):
        raise PlaybookValidationError("execution_readiness_report.unsafe_action", "Execution readiness report contains unsafe next action.")


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


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
