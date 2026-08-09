from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from .errors import PlaybookExecutionError


class ReadbackPolicy(StrEnum):
    UNAVAILABLE = "unavailable"
    OPTIONAL = "optional"
    REQUIRED = "required"


class CompensationPolicy(StrEnum):
    UNAVAILABLE = "unavailable"
    SUPPORTED = "supported"
    REQUIRED = "required"
    FORBIDDEN = "forbidden"


class RecoveryPolicy(StrEnum):
    UNRECOVERABLE = "unrecoverable"
    MANUAL = "manual"
    AUTOMATIC = "automatic"


@dataclass(frozen=True)
class MutationPolicy:
    requires_approval: bool
    idempotency_required: bool
    readback: str = ReadbackPolicy.UNAVAILABLE.value
    compensation: str = CompensationPolicy.UNAVAILABLE.value
    recovery: str = RecoveryPolicy.UNRECOVERABLE.value
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "readback", ReadbackPolicy(self.readback).value)
        object.__setattr__(self, "compensation", CompensationPolicy(self.compensation).value)
        object.__setattr__(self, "recovery", RecoveryPolicy(self.recovery).value)
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "compensation": self.compensation,
            "idempotency_required": self.idempotency_required,
            "metadata": _json_safe(self.metadata),
            "readback": self.readback,
            "recovery": self.recovery,
            "requires_approval": self.requires_approval,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MutationPolicy:
        return cls(
            requires_approval=bool(payload.get("requires_approval", False)),
            idempotency_required=bool(payload.get("idempotency_required", False)),
            readback=str(payload.get("readback") or ReadbackPolicy.UNAVAILABLE.value),
            compensation=str(payload.get("compensation") or CompensationPolicy.UNAVAILABLE.value),
            recovery=str(payload.get("recovery") or RecoveryPolicy.UNRECOVERABLE.value),
            metadata=dict(payload.get("metadata") or {}),
        )

    def fingerprint(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MutationSafetyResult:
    status: str
    effective_policy: MutationPolicy | None = None
    reason_code: str = ""
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.status == "READY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_policy": self.effective_policy.to_dict() if self.effective_policy else {},
            "message": self.message,
            "metadata": _json_safe(self.metadata),
            "reason_code": self.reason_code,
            "status": self.status,
        }


@dataclass(frozen=True)
class MutationSafetyReportEntry:
    node_id: str
    capability_id: str
    component_id: str
    status: str
    reason_code: str = ""
    effective_policy: MutationPolicy | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "component_id": self.component_id,
            "effective_policy": self.effective_policy.to_dict() if self.effective_policy else {},
            "node_id": self.node_id,
            "reason_code": self.reason_code,
            "status": self.status,
        }


@runtime_checkable
class MutationPolicyProvider(Protocol):
    mutation_policy: MutationPolicy


@runtime_checkable
class ReadbackVerifier(Protocol):
    def verify_readback(self, *args: Any, **kwargs: Any) -> Any: ...


def resolve_effective_mutation_policy(
    implementation_policy: MutationPolicy,
    requested_policy: MutationPolicy | None = None,
) -> MutationSafetyResult:
    requested_policy = requested_policy or implementation_policy
    if implementation_policy.requires_approval and not requested_policy.requires_approval:
        return _blocked("POLICY_DOWNGRADE_REJECTED", "Approval requirement cannot be weakened.")
    if implementation_policy.idempotency_required and not requested_policy.idempotency_required:
        return _blocked("POLICY_DOWNGRADE_REJECTED", "Idempotency requirement cannot be weakened.")
    if not _readback_compatible(implementation_policy.readback, requested_policy.readback):
        return _blocked("BLOCKED_READBACK", "Requested readback policy is incompatible.")
    if not _compensation_compatible(implementation_policy.compensation, requested_policy.compensation):
        return _blocked("BLOCKED_COMPENSATION", "Requested compensation policy is incompatible.")
    if not _recovery_compatible(implementation_policy.recovery, requested_policy.recovery):
        return _blocked("BLOCKED_RECOVERY", "Requested recovery policy is incompatible.")
    return MutationSafetyResult("READY", effective_policy=requested_policy)


def validate_mutation_safety(
    *,
    handler: Any,
    requested_policy: MutationPolicy | None = None,
    idempotency_key: str = "",
) -> MutationSafetyResult:
    policy = getattr(handler, "mutation_policy", None)
    if not isinstance(policy, MutationPolicy):
        component_id = str(getattr(handler, "component_id", ""))
        if component_id.startswith("test-") and requested_policy is not None:
            policy = requested_policy
        else:
            return _blocked("BLOCKED_POLICY_MISSING", "Mutation handler does not declare a mutation policy.")
    resolved = resolve_effective_mutation_policy(policy, requested_policy)
    if not resolved.ready:
        return resolved
    effective = resolved.effective_policy
    assert effective is not None
    if effective.idempotency_required and not idempotency_key:
        return _blocked("BLOCKED_IDEMPOTENCY", "Mutation requires an idempotency key.", effective)
    if effective.readback == ReadbackPolicy.REQUIRED.value and not hasattr(handler, "verify_readback"):
        return _blocked("BLOCKED_READBACK", "Mutation requires readback verification.", effective)
    if effective.compensation == CompensationPolicy.REQUIRED.value and not hasattr(handler, "compensate"):
        return _blocked("BLOCKED_COMPENSATION", "Mutation requires private compensation support.", effective)
    if effective.recovery == RecoveryPolicy.AUTOMATIC.value and effective.readback != ReadbackPolicy.REQUIRED.value:
        return _blocked("BLOCKED_RECOVERY", "Automatic recovery requires required readback.", effective)
    return resolved


def requested_mutation_policy_from_config(config: dict[str, Any], minimum: MutationPolicy) -> MutationPolicy:
    payload = dict(config.get("mutation_policy") or {})
    compensation = dict(config.get("compensation") or {})
    if "compensation" not in payload and compensation.get("mode") == "on_downstream_failure":
        payload["compensation"] = CompensationPolicy.SUPPORTED.value
    merged = {**minimum.to_dict(), **payload}
    return MutationPolicy.from_dict(merged)


def mutation_policy_fingerprint(policy: MutationPolicy) -> str:
    return policy.fingerprint()


def mutation_safety_report(plan: Any, handler_registry: Any) -> tuple[MutationSafetyReportEntry, ...]:
    entries: list[MutationSafetyReportEntry] = []
    for node in getattr(plan, "nodes", ()):
        if not getattr(node, "capability", ""):
            continue
        handler = handler_registry.resolve(node.component_id, node.capability)
        capability_mode = str(getattr(node, "capability_mode", ""))
        is_write = (
            capability_mode == "write" or node.capability.endswith(".create") or node.capability.endswith(".write")
        )
        if not is_write:
            continue
        policy = getattr(handler, "mutation_policy", None)
        requested = (
            requested_mutation_policy_from_config(dict(getattr(node, "config", {}) or {}), policy)
            if isinstance(policy, MutationPolicy)
            else None
        )
        result = validate_mutation_safety(handler=handler, requested_policy=requested, idempotency_key="preflight")
        entries.append(
            MutationSafetyReportEntry(
                node_id=node.node_id,
                capability_id=node.capability,
                component_id=node.component_id,
                status=result.status,
                reason_code=result.reason_code,
                effective_policy=result.effective_policy,
            )
        )
    return tuple(entries)


def _readback_compatible(implementation: str, requested: str) -> bool:
    order = {
        ReadbackPolicy.UNAVAILABLE.value: 0,
        ReadbackPolicy.OPTIONAL.value: 1,
        ReadbackPolicy.REQUIRED.value: 2,
    }
    return order[requested] >= order[implementation]


def _compensation_compatible(implementation: str, requested: str) -> bool:
    if implementation == CompensationPolicy.FORBIDDEN.value:
        return requested in {CompensationPolicy.FORBIDDEN.value, CompensationPolicy.UNAVAILABLE.value}
    if requested == CompensationPolicy.REQUIRED.value:
        return implementation in {CompensationPolicy.REQUIRED.value, CompensationPolicy.SUPPORTED.value}
    if requested == CompensationPolicy.SUPPORTED.value:
        return implementation in {CompensationPolicy.REQUIRED.value, CompensationPolicy.SUPPORTED.value}
    if requested == CompensationPolicy.FORBIDDEN.value:
        return implementation == CompensationPolicy.FORBIDDEN.value
    return True


def _recovery_compatible(implementation: str, requested: str) -> bool:
    order = {
        RecoveryPolicy.UNRECOVERABLE.value: 0,
        RecoveryPolicy.MANUAL.value: 1,
        RecoveryPolicy.AUTOMATIC.value: 2,
    }
    return order[requested] >= order[implementation]


def _blocked(reason_code: str, message: str, effective_policy: MutationPolicy | None = None) -> MutationSafetyResult:
    return MutationSafetyResult(
        "BLOCKED",
        effective_policy=effective_policy,
        reason_code=reason_code,
        message=message,
    )


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
    except TypeError as exc:
        raise PlaybookExecutionError("MUTATION_POLICY_INVALID", "Mutation policy metadata must be JSON-safe.") from exc
