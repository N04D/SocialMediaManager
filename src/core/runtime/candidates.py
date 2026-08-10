from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .errors import PlaybookExecutionError
from .handlers import CapabilityHandler, CapabilityHandlerRegistry
from .mutation_policies import MutationPolicy


@dataclass(frozen=True)
class MutationHandlerCandidate:
    component_id: str
    capability_id: str
    build_handler: Callable[[], CapabilityHandler]
    mutation_policy: MutationPolicy
    permission_requirements: dict[str, Any] | None = None
    readback_support: dict[str, Any] = field(default_factory=dict)
    recovery_support: dict[str, Any] = field(default_factory=dict)
    handler_identity: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        return compute_candidate_evidence_fingerprint(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "component_id": self.component_id,
            "fingerprint": self.fingerprint(),
            "handler_identity": self.handler_identity or _handler_identity_from_factory(self.build_handler),
            "metadata": _json_safe(self.metadata),
            "mutation_policy": self.mutation_policy.to_dict(),
            "permission_requirements": _json_safe(self.permission_requirements or {}),
            "readback_support": _json_safe(self.readback_support),
            "recovery_support": _json_safe(self.recovery_support),
        }


@dataclass(frozen=True)
class ProductionMutationActivationResult:
    capability_id: str
    component_id: str
    status: str
    activated: bool
    evidence_fingerprint: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    handler: CapabilityHandler | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activated": self.activated,
            "capability_id": self.capability_id,
            "component_id": self.component_id,
            "evidence_fingerprint": self.evidence_fingerprint,
            "metadata": _json_safe(self.metadata),
            "reasons": list(self.reasons),
            "status": self.status,
        }


def compute_candidate_evidence_fingerprint(candidate: MutationHandlerCandidate) -> str:
    handler_identity = candidate.handler_identity or _handler_identity_from_factory(candidate.build_handler)
    payload = {
        "capability_id": candidate.capability_id,
        "component_id": candidate.component_id,
        "handler_identity": handler_identity,
        "mutation_policy": candidate.mutation_policy.to_dict(),
        "permission_requirements": candidate.permission_requirements or {},
        "readback_support": candidate.readback_support,
        "recovery_support": candidate.recovery_support,
    }
    encoded = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def admit_and_register_mutation(
    *,
    candidate: MutationHandlerCandidate,
    component: Any,
    install: Any = None,
    registry: CapabilityHandlerRegistry,
    admission_evaluator: Callable[..., Any],
) -> ProductionMutationActivationResult:
    """Validate candidate admission and register the production mutation handler upon success.

    Registration is the consequence of admission, not evidence for admission.
    No caller-controlled `admitted=True` flag is permitted.
    """
    initial_fingerprint = candidate.fingerprint()
    admission_result = admission_evaluator(component=component, install=install, candidate=candidate)

    if not hasattr(admission_result, "status") or admission_result.status != "ADMITTED":
        reasons = getattr(admission_result, "reasons", ("BLOCKED_ADMISSION_FAILED",))
        return ProductionMutationActivationResult(
            capability_id=candidate.capability_id,
            component_id=candidate.component_id,
            status="BLOCKED",
            activated=False,
            evidence_fingerprint=initial_fingerprint,
            reasons=tuple(reasons),
            metadata={"admission_status": getattr(admission_result, "status", "BLOCKED")},
        )

    # Re-validate candidate evidence fingerprint at activation to prevent stale admission
    current_fingerprint = candidate.fingerprint()
    admission_fingerprint = str(getattr(admission_result, "metadata", {}).get("evidence_fingerprint") or initial_fingerprint)

    if current_fingerprint != initial_fingerprint or current_fingerprint != admission_fingerprint:
        return ProductionMutationActivationResult(
            capability_id=candidate.capability_id,
            component_id=candidate.component_id,
            status="ADMISSION_STALE",
            activated=False,
            evidence_fingerprint=current_fingerprint,
            reasons=("ADMISSION_STALE",),
            metadata={
                "admission_fingerprint": admission_fingerprint,
                "current_fingerprint": current_fingerprint,
            },
        )

    # Build and register the production handler
    try:
        handler = candidate.build_handler()
        if handler.component_id != candidate.component_id or handler.capability_id != candidate.capability_id:
            raise PlaybookExecutionError(
                "CANDIDATE_HANDLER_MISMATCH",
                "Candidate handler metadata does not match descriptor.",
                {
                    "descriptor_component": candidate.component_id,
                    "descriptor_capability": candidate.capability_id,
                    "handler_component": handler.component_id,
                    "handler_capability": handler.capability_id,
                },
            )
        registry.register(handler)
    except PlaybookExecutionError:
        raise
    except Exception as exc:
        return ProductionMutationActivationResult(
            capability_id=candidate.capability_id,
            component_id=candidate.component_id,
            status="ACTIVATION_FAILED",
            activated=False,
            evidence_fingerprint=current_fingerprint,
            reasons=("ACTIVATION_FAILED",),
            metadata={"error": type(exc).__name__},
        )

    return ProductionMutationActivationResult(
        capability_id=candidate.capability_id,
        component_id=candidate.component_id,
        status="ADMITTED",
        activated=True,
        evidence_fingerprint=current_fingerprint,
        reasons=(),
        handler=handler,
        metadata={
            "activation": "successful",
            "evidence_fingerprint": current_fingerprint,
        },
    )


@dataclass(frozen=True)
class ExternalSourceCandidate:
    component_id: str
    source_id: str
    event_type: str
    build_source: Callable[[], Any]
    read_only: bool = True
    bounded_polling: bool = True
    page_size_limit: int = 50
    max_pages_limit: int = 10
    first_poll_policy: str = "FROM_NOW"
    gap_detection: bool = True
    stable_external_identity: bool = True
    checkpoint_support: bool = True
    required_egress: tuple[str, ...] = field(default_factory=tuple)
    required_secrets: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        payload = {
            "bounded_polling": self.bounded_polling,
            "checkpoint_support": self.checkpoint_support,
            "component_id": self.component_id,
            "event_type": self.event_type,
            "first_poll_policy": self.first_poll_policy,
            "gap_detection": self.gap_detection,
            "max_pages_limit": self.max_pages_limit,
            "page_size_limit": self.page_size_limit,
            "read_only": self.read_only,
            "required_egress": list(self.required_egress),
            "required_secrets": list(self.required_secrets),
            "source_id": self.source_id,
            "stable_external_identity": self.stable_external_identity,
        }
        encoded = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ProductionExternalSourceActivationResult:
    source_id: str
    component_id: str
    status: str
    activated: bool
    evidence_fingerprint: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    source: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activated": self.activated,
            "component_id": self.component_id,
            "evidence_fingerprint": self.evidence_fingerprint,
            "metadata": _json_safe(self.metadata),
            "reasons": list(self.reasons),
            "source_id": self.source_id,
            "status": self.status,
        }


def admit_and_activate_external_source(
    *,
    candidate: ExternalSourceCandidate,
    component: Any,
    install: Any = None,
    source_registry: dict[tuple[str, str], Any] | None = None,
    admission_evaluator: Callable[..., Any],
) -> ProductionExternalSourceActivationResult:
    initial_fingerprint = candidate.fingerprint()
    admission_result = admission_evaluator(component=component, install=install, candidate=candidate)

    if not hasattr(admission_result, "status") or admission_result.status != "ADMITTED":
        reasons = getattr(admission_result, "reasons", ("BLOCKED_ADMISSION_FAILED",))
        return ProductionExternalSourceActivationResult(
            source_id=candidate.source_id,
            component_id=candidate.component_id,
            status=getattr(admission_result, "status", "BLOCKED_ADMISSION_FAILED"),
            activated=False,
            evidence_fingerprint=initial_fingerprint,
            reasons=tuple(reasons),
            metadata=dict(getattr(admission_result, "metadata", {})),
        )

    current_fingerprint = candidate.fingerprint()
    if initial_fingerprint != current_fingerprint:
        return ProductionExternalSourceActivationResult(
            source_id=candidate.source_id,
            component_id=candidate.component_id,
            status="BLOCKED_CANDIDATE_MUTATED",
            activated=False,
            evidence_fingerprint=current_fingerprint,
            reasons=("BLOCKED_CANDIDATE_MUTATED",),
        )

    try:
        source_instance = candidate.build_source()
        if source_registry is not None:
            source_registry[(candidate.component_id, candidate.source_id)] = source_instance
    except Exception as exc:
        return ProductionExternalSourceActivationResult(
            source_id=candidate.source_id,
            component_id=candidate.component_id,
            status="ACTIVATION_FAILED",
            activated=False,
            evidence_fingerprint=current_fingerprint,
            reasons=("ACTIVATION_FAILED",),
            metadata={"error": type(exc).__name__},
        )

    return ProductionExternalSourceActivationResult(
        source_id=candidate.source_id,
        component_id=candidate.component_id,
        status="ADMITTED",
        activated=True,
        evidence_fingerprint=current_fingerprint,
        reasons=(),
        source=source_instance,
        metadata={"activation": "successful", "evidence_fingerprint": current_fingerprint},
    )


def _handler_identity_from_factory(factory: Callable[[], CapabilityHandler]) -> str:
    if hasattr(factory, "__qualname__"):
        return f"{factory.__module__}.{factory.__qualname__}"
    return type(factory).__name__


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value

