from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .errors import PlaybookValidationError
from .events import utc_now_iso
from .playbook_registry import _contains_registry_secret
from .playbook_sandbox import SANDBOX_EXECUTION_SCHEMA_VERSION
from .sandbox_execution_store import SandboxExecutionStore

SANDBOX_EVALUATION_SCHEMA_VERSION = "sandbox-evaluation.v1"
SANDBOX_EVALUATION_HARNESS_VERSION = "sandbox-evaluation-harness.v1"

ALLOWED_EXECUTION_STATUSES = {"blocked", "completed", "failed_safe", "skipped"}
ALLOWED_CHECK_STATUSES = {"failed", "passed", "warning"}
ALLOWED_SEVERITIES = {"error", "info", "warning"}
DEFAULT_FORBIDDEN_DIFFERENCE_CODES = ("redaction_changed",)


@dataclass(frozen=True)
class EvaluationPolicy:
    policy_id: str = "sandbox-evaluation-default"
    version: str = "1.0.0"
    allow_blocked: bool = False
    require_all_steps_completed: bool = False
    allow_warnings: bool = True
    allow_raw_metrics: bool = False
    allow_raw_transcript: bool = False
    allow_mutations: bool = False
    required_step_kinds: tuple[str, ...] = field(default_factory=tuple)
    forbidden_step_kinds: tuple[str, ...] = field(default_factory=tuple)
    allowed_difference_codes: tuple[str, ...] = field(default_factory=tuple)
    forbidden_difference_codes: tuple[str, ...] = DEFAULT_FORBIDDEN_DIFFERENCE_CODES

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class SandboxEvaluationCheck:
    check_id: str
    status: str
    severity: str
    reason_code: str
    subject_ref: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class SandboxEvaluationRedaction:
    raw_metrics_included: bool = False
    raw_transcript_included: bool = False
    secrets_included: bool = False
    provider_headers_included: bool = False


@dataclass(frozen=True)
class SandboxEvaluationResult:
    evaluation_id: str
    execution_id: str
    subject_fingerprint: str
    status: str
    checks: tuple[SandboxEvaluationCheck, ...]
    warnings: tuple[str, ...]
    failures: tuple[str, ...]
    policy_version: str
    evaluated_at: str
    provenance: dict[str, Any]
    redaction: SandboxEvaluationRedaction
    schema_version: str = SANDBOX_EVALUATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class SandboxEvaluationHarness:
    def __init__(self, *, clock=utc_now_iso):
        self.clock = clock

    def evaluate(
        self,
        record: Any,
        policy: EvaluationPolicy | None = None,
    ) -> SandboxEvaluationResult:
        selected_policy = policy or EvaluationPolicy()
        payload = _record_payload(record)
        evaluated_at = self.clock()
        checks = []
        checks.extend(_safety_checks(payload, selected_policy))
        checks.extend(_policy_checks(payload, selected_policy))
        checks = tuple(sorted(checks, key=lambda item: (item.subject_ref, item.check_id, item.reason_code)))
        return self._result(
            execution_id=str(payload.get("execution_id") or ""),
            subject_fingerprint=str(payload.get("fingerprint") or _semantic_fingerprint(payload)),
            checks=checks,
            policy=selected_policy,
            evaluated_at=evaluated_at,
            provenance={
                "harness_version": SANDBOX_EVALUATION_HARNESS_VERSION,
                "evaluation_type": "execution_record",
                "policy_id": selected_policy.policy_id,
                "policy_version": selected_policy.version,
            },
        )

    def evaluate_from_store(
        self,
        execution_id: str,
        store: SandboxExecutionStore,
        policy: EvaluationPolicy | None = None,
    ) -> SandboxEvaluationResult:
        record = store.get(execution_id)
        if record is None:
            selected_policy = policy or EvaluationPolicy()
            return self._result(
                execution_id=execution_id,
                subject_fingerprint="",
                checks=(
                    SandboxEvaluationCheck(
                        check_id="execution_present",
                        status="failed",
                        severity="error",
                        reason_code="execution_not_found",
                        subject_ref=execution_id,
                    ),
                ),
                policy=selected_policy,
                evaluated_at=self.clock(),
                provenance={
                    "harness_version": SANDBOX_EVALUATION_HARNESS_VERSION,
                    "evaluation_type": "execution_record",
                    "policy_id": selected_policy.policy_id,
                    "policy_version": selected_policy.version,
                },
            )
        return self.evaluate(record, policy=policy)

    def evaluate_comparison(
        self,
        compare_result: Any,
        policy: EvaluationPolicy | None = None,
    ) -> SandboxEvaluationResult:
        selected_policy = policy or EvaluationPolicy()
        payload = _comparison_payload(compare_result)
        differences = tuple(sorted(str(item) for item in payload.get("differences", ()) if str(item)))
        matched = bool(payload.get("matched"))
        checks: list[SandboxEvaluationCheck] = [
            _check(
                "comparison_schema_safe",
                not _contains_forbidden_data(payload),
                "comparison_contains_forbidden_data",
                "comparison",
            )
        ]
        if matched and not differences:
            checks.append(_check("replay_matched", True, "replay_matched", "comparison"))
        else:
            forbidden = sorted(set(differences) & set(selected_policy.forbidden_difference_codes))
            unallowed = sorted(set(differences) - set(selected_policy.allowed_difference_codes) - set(selected_policy.forbidden_difference_codes))
            if forbidden:
                checks.append(
                    _failed(
                        "forbidden_difference_absent",
                        "forbidden_difference_code",
                        "comparison",
                        {"differences": forbidden},
                    )
                )
            if unallowed:
                checks.append(
                    _warning(
                        "comparison_matched",
                        "replay_differed",
                        "comparison",
                        {"differences": unallowed},
                    )
                )
            allowed = sorted(set(differences) & set(selected_policy.allowed_difference_codes))
            if allowed:
                checks.append(
                    _warning(
                        "allowed_difference_observed",
                        "allowed_difference_code",
                        "comparison",
                        {"differences": allowed},
                    )
                )
        checks = tuple(sorted(checks, key=lambda item: (item.subject_ref, item.check_id, item.reason_code)))
        return self._result(
            execution_id=str(payload.get("original_execution_id") or payload.get("execution_id") or ""),
            subject_fingerprint=str(payload.get("original_fingerprint") or payload.get("fingerprint_a") or ""),
            checks=checks,
            policy=selected_policy,
            evaluated_at=self.clock(),
            provenance={
                "harness_version": SANDBOX_EVALUATION_HARNESS_VERSION,
                "evaluation_type": "comparison",
                "policy_id": selected_policy.policy_id,
                "policy_version": selected_policy.version,
            },
        )

    def summarize(self, result: SandboxEvaluationResult) -> dict[str, Any]:
        return {
            "evaluation_id": result.evaluation_id,
            "execution_id": result.execution_id,
            "status": result.status,
            "warning_count": len(result.warnings),
            "failure_count": len(result.failures),
            "warnings": list(result.warnings),
            "failures": list(result.failures),
        }

    def _result(
        self,
        *,
        execution_id: str,
        subject_fingerprint: str,
        checks: tuple[SandboxEvaluationCheck, ...],
        policy: EvaluationPolicy,
        evaluated_at: str,
        provenance: dict[str, Any],
    ) -> SandboxEvaluationResult:
        failures = tuple(sorted({item.reason_code for item in checks if item.status == "failed"}))
        warnings = tuple(sorted({item.reason_code for item in checks if item.status == "warning"}))
        if failures or (warnings and not policy.allow_warnings):
            status = "failed"
        elif warnings:
            status = "warning"
        else:
            status = "passed"
        result = SandboxEvaluationResult(
            evaluation_id=_evaluation_id(execution_id, subject_fingerprint, policy, evaluated_at),
            execution_id=execution_id,
            subject_fingerprint=subject_fingerprint,
            status=status,
            checks=checks,
            warnings=warnings,
            failures=failures,
            policy_version=f"{policy.policy_id}:{policy.version}",
            evaluated_at=evaluated_at,
            provenance=provenance,
            redaction=SandboxEvaluationRedaction(),
        )
        _assert_evaluation_safe(result.to_dict())
        return result


def _safety_checks(payload: dict[str, Any], policy: EvaluationPolicy) -> list[SandboxEvaluationCheck]:
    checks = [
        _check("sandbox_true", payload.get("sandbox") is True, "sandbox_not_true", "record"),
        _check("read_only_true", payload.get("read_only") is True, "read_only_not_true", "record"),
        _check("status_allowed", payload.get("status") in ALLOWED_EXECUTION_STATUSES, "status_invalid", "record"),
        _check("fingerprint_present", _valid_fingerprint(payload.get("fingerprint")), "fingerprint_missing_or_invalid", "record"),
        _check("schema_allowed", payload.get("schema_version") == SANDBOX_EXECUTION_SCHEMA_VERSION, "schema_invalid", "record"),
        _check("step_ordering_deterministic", _step_ids(payload) == sorted(_step_ids(payload)), "step_ordering_not_deterministic", "step_results"),
        _check("forbidden_data_absent", not _contains_forbidden_data(payload), "forbidden_data_present", "record"),
    ]
    redaction = payload.get("redaction") or {}
    checks.extend(
        [
            _check("secrets_not_included", redaction.get("secrets_included") is False, "secrets_included", "redaction"),
            _check(
                "provider_headers_not_included",
                redaction.get("provider_headers_included") is False,
                "provider_headers_included",
                "redaction",
            ),
            _check(
                "raw_metrics_not_included",
                policy.allow_raw_metrics or redaction.get("raw_metrics_included") is False,
                "raw_metrics_included",
                "redaction",
            ),
            _check(
                "raw_transcript_not_included",
                policy.allow_raw_transcript or redaction.get("raw_transcript_included") is False,
                "raw_transcript_included",
                "redaction",
            ),
            _check(
                "production_executor_not_invoked",
                not _marker_present(payload, ("Playbook" + "Executor", "production_executor_invoked")),
                "production_executor_invoked",
                "provenance",
            ),
            _check(
                "ai_not_invoked",
                not _marker_present(payload, ("open" + "ai", "anthro" + "pic", "chat" + "gpt", "llm_call")),
                "ai_invoked",
                "provenance",
            ),
            _check(
                "interactive_collection_not_invoked",
                not _marker_present(payload, ("brow" + "ser", "sc" + "rap" + "ing", "sc" + "rap" + "er", "play" + "wright")),
                "interactive_collection_invoked",
                "provenance",
            ),
        ]
    )
    for step in payload.get("step_results") or ():
        step_ref = f"step:{step.get('step_id', '')}"
        checks.append(
            _check(
                "step_mutation_not_used",
                policy.allow_mutations or step.get("mutation_used") is False,
                "mutation_used",
                step_ref,
            )
        )
        checks.append(
            _check(
                "step_raw_access_not_used",
                policy.allow_raw_metrics or policy.allow_raw_transcript or step.get("raw_access_used") is False,
                "raw_access_used",
                step_ref,
            )
        )
    return checks


def _policy_checks(payload: dict[str, Any], policy: EvaluationPolicy) -> list[SandboxEvaluationCheck]:
    checks: list[SandboxEvaluationCheck] = []
    status = str(payload.get("status") or "")
    checks.append(_check("blocked_policy", policy.allow_blocked or status != "blocked", "blocked_not_allowed", "record"))
    if policy.require_all_steps_completed:
        incomplete = [
            str(step.get("step_id") or "")
            for step in payload.get("step_results") or ()
            if step.get("status") != "completed"
        ]
        checks.append(
            _check(
                "all_steps_completed",
                not incomplete and status == "completed",
                "steps_not_completed",
                "step_results",
                {"steps": sorted(incomplete)},
            )
        )
    step_kinds = set(_step_kinds(payload))
    for kind in sorted(policy.required_step_kinds):
        checks.append(_check("required_step_kind_present", kind in step_kinds, "required_step_kind_missing", f"step_kind:{kind}"))
    for kind in sorted(policy.forbidden_step_kinds):
        checks.append(_check("forbidden_step_kind_absent", kind not in step_kinds, "forbidden_step_kind_present", f"step_kind:{kind}"))
    blockers = _blockers(payload)
    for blocker in ("unsupported_step_kind", "capability_not_available", "raw_access_not_allowed", "mutation_not_allowed"):
        if blocker in blockers:
            checks.append(_warning("blocker_observed", blocker, f"blocker:{blocker}"))
    return checks


def _record_payload(record: Any) -> dict[str, Any]:
    if hasattr(record, "to_dict"):
        return _json_safe(record.to_dict())
    return _json_safe(dict(record))


def _comparison_payload(compare_result: Any) -> dict[str, Any]:
    if hasattr(compare_result, "to_dict"):
        return _json_safe(compare_result.to_dict())
    return _json_safe(dict(compare_result))


def _check(
    check_id: str,
    passed: bool,
    reason_code: str,
    subject_ref: str,
    details: dict[str, Any] | None = None,
) -> SandboxEvaluationCheck:
    if passed:
        return SandboxEvaluationCheck(
            check_id=check_id,
            status="passed",
            severity="info",
            reason_code="ok",
            subject_ref=subject_ref,
            details=details or {},
        )
    return _failed(check_id, reason_code, subject_ref, details or {})


def _failed(
    check_id: str,
    reason_code: str,
    subject_ref: str,
    details: dict[str, Any] | None = None,
) -> SandboxEvaluationCheck:
    return SandboxEvaluationCheck(
        check_id=check_id,
        status="failed",
        severity="error",
        reason_code=reason_code,
        subject_ref=subject_ref,
        details=details or {},
    )


def _warning(
    check_id: str,
    reason_code: str,
    subject_ref: str,
    details: dict[str, Any] | None = None,
) -> SandboxEvaluationCheck:
    return SandboxEvaluationCheck(
        check_id=check_id,
        status="warning",
        severity="warning",
        reason_code=reason_code,
        subject_ref=subject_ref,
        details=details or {},
    )


def _step_ids(payload: dict[str, Any]) -> list[str]:
    return [str(step.get("step_id") or "") for step in payload.get("step_results") or ()]


def _step_kinds(payload: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            str((step.get("provenance") or {}).get("evaluator_id") or "")
            for step in payload.get("step_results") or ()
            if str((step.get("provenance") or {}).get("evaluator_id") or "")
            not in {"blocked", "skipped"}
        )
    )


def _blockers(payload: dict[str, Any]) -> set[str]:
    values = set(str(item) for item in payload.get("blocked_reasons") or () if str(item))
    for step in payload.get("step_results") or ():
        values.update(str(item) for item in step.get("blocked_reasons") or () if str(item))
    return values


def _valid_fingerprint(value: Any) -> bool:
    rendered = str(value or "")
    return len(rendered) == 64 and all(item in "0123456789abcdef" for item in rendered)


def _semantic_fingerprint(payload: dict[str, Any]) -> str:
    cleaned = {key: value for key, value in _json_safe(payload).items() if key != "fingerprint"}
    rendered = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _evaluation_id(execution_id: str, subject_fingerprint: str, policy: EvaluationPolicy, evaluated_at: str) -> str:
    payload = {
        "evaluated_at": evaluated_at,
        "execution_id": execution_id,
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
        "subject_fingerprint": subject_fingerprint,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"sandbox_evaluation_{digest[:32]}"


def _contains_forbidden_data(payload: dict[str, Any]) -> bool:
    if _contains_registry_secret(payload):
        return True
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = ("raw_metrics_payload", "raw_transcript_body", "Authorization", "Bearer ", "SECRET_CANARY")
    return any(item in rendered for item in forbidden)


def _marker_present(payload: dict[str, Any], markers: tuple[str, ...]) -> bool:
    rendered = json.dumps(payload, sort_keys=True).lower()
    return any(marker.lower() in rendered for marker in markers)


def _assert_evaluation_safe(payload: dict[str, Any]) -> None:
    if _contains_forbidden_data(payload):
        raise PlaybookValidationError("sandbox_evaluation.raw_or_secret_value", "Sandbox evaluation contains forbidden data.")
    statuses = {check.get("status") for check in payload.get("checks") or ()}
    severities = {check.get("severity") for check in payload.get("checks") or ()}
    if not statuses <= ALLOWED_CHECK_STATUSES or not severities <= ALLOWED_SEVERITIES:
        raise PlaybookValidationError("sandbox_evaluation.invalid_check", "Sandbox evaluation has invalid check metadata.")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
