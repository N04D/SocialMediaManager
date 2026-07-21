from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ExecutionAttemptStatus(StrEnum):
    CREATED = "created"
    CLAIMED = "claimed"
    VALIDATING = "validating"
    DISPATCHING = "dispatching"
    QUEUED = "queued"
    RUNNING = "running"
    RECONCILING = "reconciling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"
    SUPERSEDED = "superseded"


class ExecutionPhase(StrEnum):
    PREFLIGHT = "preflight"
    SNAPSHOT_VALIDATION = "snapshot_validation"
    JOB_CREATION = "job_creation"
    JOB_CLAIM = "job_claim"
    CHANNEL_PREPARE = "channel_prepare"
    REMOTE_MUTATION = "remote_mutation"
    REMOTE_VERIFICATION = "remote_verification"
    EVIDENCE_PERSISTENCE = "evidence_persistence"
    CLEANUP = "cleanup"
    RECONCILIATION = "reconciliation"


class MutationState(StrEnum):
    NOT_STARTED = "not_started"
    PREPARED = "prepared"
    MUTATION_STARTED = "mutation_started"
    MUTATION_ACKNOWLEDGED = "mutation_acknowledged"
    MUTATION_VERIFIED = "mutation_verified"
    MUTATION_UNCERTAIN = "mutation_uncertain"


class ExecutionLeaseStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"
    REVOKED = "revoked"


class RetryAction(StrEnum):
    NO_RETRY = "no_retry"
    RETRY_AUTOMATICALLY = "retry_automatically"
    RETRY_AFTER_REVALIDATION = "retry_after_revalidation"
    WAIT_FOR_PROVIDER = "wait_for_provider"
    WAIT_FOR_AUTHENTICATION = "wait_for_authentication"
    REQUIRE_OPERATOR_CONFIRMATION = "require_operator_confirmation"
    RECONCILE_FIRST = "reconcile_first"
    MARK_UNCERTAIN = "mark_uncertain"
    MARK_FAILED = "mark_failed"


class ReconciliationClassification(StrEnum):
    CONSISTENT_PENDING = "consistent_pending"
    CONSISTENT_RUNNING = "consistent_running"
    CONSISTENT_SUCCEEDED = "consistent_succeeded"
    CONSISTENT_FAILED = "consistent_failed"
    CONSISTENT_UNCERTAIN = "consistent_uncertain"
    LEASE_EXPIRED_PRE_MUTATION = "lease_expired_pre_mutation"
    LEASE_EXPIRED_POST_MUTATION = "lease_expired_post_mutation"
    JOB_MISSING = "job_missing"
    ATTEMPT_MISSING = "attempt_missing"
    EVIDENCE_MISSING = "evidence_missing"
    JOB_SUCCEEDED_EVIDENCE_MISSING = "job_succeeded_evidence_missing"
    EVIDENCE_EXISTS_TARGET_NOT_UPDATED = "evidence_exists_target_not_updated"
    TARGET_QUEUED_JOB_NOT_CLAIMED = "target_queued_job_not_claimed"
    TARGET_RUNNING_JOB_TERMINAL = "target_running_job_terminal"
    DUPLICATE_JOB_DETECTED = "duplicate_job_detected"
    SNAPSHOT_MISMATCH = "snapshot_mismatch"
    REMOTE_VERIFICATION_REQUIRED = "remote_verification_required"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


@dataclass
class ExecutionAttempt:
    id: str
    workspace_id: str
    publication_plan_id: str
    publication_target_id: str
    attempt_number: int
    snapshot_checksum: str
    idempotency_key: str
    status: str = ExecutionAttemptStatus.CREATED.value
    phase: str = ExecutionPhase.PREFLIGHT.value
    trigger: str = "manual"
    worker_id: str = ""
    lease_id: str = ""
    job_id: str = ""
    publication_id: str = ""
    started_at: str = ""
    heartbeat_at: str = ""
    completed_at: str = ""
    next_retry_at: str = ""
    retry_count: int = 0
    error_class: str = ""
    safe_error_code: str = ""
    mutation_state: str = MutationState.NOT_STARTED.value
    remote_verification_state: str = ""
    cleanup_state: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionLease:
    id: str
    target_id: str
    attempt_id: str
    worker_id: str
    claimed_at: str
    heartbeat_at: str
    expires_at: str
    released_at: str = ""
    status: str = ExecutionLeaseStatus.ACTIVE.value
    version: int = 1


@dataclass(frozen=True)
class RetryDecision:
    action: str
    retryable: bool
    automatic: bool
    delay_seconds: int = 0
    next_retry_at: str = ""
    requires_revalidation: bool = True
    requires_confirmation: bool = False
    reason_code: str = ""


@dataclass
class UncertainResolution:
    attempt_id: str
    resolution: str
    resolved_by: str
    resolved_at: str
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DuePublicationTarget:
    publication_plan_id: str
    publication_target_id: str
    workspace_id: str
    scheduled_at: str
    resolved_scheduled_at_utc: str
    position: int
    status: str
    snapshot_checksum: str
    blockers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReconciliationResult:
    classification: str
    target_id: str
    attempt_id: str = ""
    job_id: str = ""
    repaired: bool = False
    status: str = ""
    reason: str = ""


@dataclass
class ExecutionAuditEvent:
    id: str
    workspace_id: str
    action: str
    publication_plan_id: str = ""
    publication_target_id: str = ""
    attempt_id: str = ""
    job_id: str = ""
    actor: str = ""
    reason_code: str = ""
    result: str = "ok"
    snapshot_checksum: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
