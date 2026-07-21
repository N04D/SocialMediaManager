from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import asdict, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import channel_store
from channel_storage import locked_json_store
from publication_planning import PublicationPlanningService
from src.core.content import PublicationPlan, PublicationPlanStatus, PublicationTarget, PublicationTargetStatus
from src.core.execution import (
    EXECUTION_ATTEMPT_CONTRACT_VERSION,
    EXECUTION_FRAMEWORK_VERSION,
    EXECUTION_LEASE_CONTRACT_VERSION,
    EXECUTION_RECONCILIATION_CONTRACT_VERSION,
    EXECUTION_RETRY_POLICY_CONTRACT_VERSION,
    PUBLICATION_DISPATCHER_CONTRACT_VERSION,
    DuePublicationTarget,
    ExecutionAttempt,
    ExecutionAttemptStatus,
    ExecutionAuditEvent,
    ExecutionLease,
    ExecutionLeaseStatus,
    ExecutionPhase,
    MutationState,
    ReconciliationClassification,
    ReconciliationResult,
    RetryAction,
    RetryDecision,
    UncertainResolution,
)

T = TypeVar("T")

TERMINAL_ATTEMPTS = {
    ExecutionAttemptStatus.SUCCEEDED.value,
    ExecutionAttemptStatus.FAILED.value,
    ExecutionAttemptStatus.UNCERTAIN.value,
    ExecutionAttemptStatus.CANCELLED.value,
    ExecutionAttemptStatus.ABANDONED.value,
    ExecutionAttemptStatus.SUPERSEDED.value,
}
PRE_MUTATION_STATES = {MutationState.NOT_STARTED.value, MutationState.PREPARED.value}
POST_MUTATION_STATES = {
    MutationState.MUTATION_STARTED.value,
    MutationState.MUTATION_ACKNOWLEDGED.value,
    MutationState.MUTATION_VERIFIED.value,
    MutationState.MUTATION_UNCERTAIN.value,
}


def attempts_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_execution_attempts.json"


def leases_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_execution_leases.json"


def events_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_execution_events.json"


def audit_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_execution_audit.json"


def resolutions_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_uncertain_resolutions.json"


def state_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_execution_state.json"


def _list_store(path: Path):
    return locked_json_store(path, default_factory=list, expect_type=list, lock_dir=channel_store.LOCKS_DIR)


def _dict_store(path: Path):
    return locked_json_store(path, default_factory=dict, expect_type=dict, lock_dir=channel_store.LOCKS_DIR)


def _fields(cls: type) -> set[str]:
    return {field.name for field in fields(cls)}


def _load_records(path: Path, cls: type[T]) -> list[T]:  # noqa: UP047
    with _list_store(path) as store:
        payload = store.read()
    allowed = _fields(cls)
    records: list[T] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            records.append(cls(**{key: value for key, value in item.items() if key in allowed}))
        except TypeError:
            continue
    return records


def _mutate_records(  # noqa: UP047
    path: Path, cls: type[T], mutator: Callable[[list[T]], tuple[bool, Any]]
) -> Any:
    with _list_store(path) as store:
        payload = store.read()
        allowed = _fields(cls)
        records: list[T] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                records.append(cls(**{key: value for key, value in item.items() if key in allowed}))
            except TypeError:
                continue
        changed, result = mutator(records)
        if changed:
            store.write([asdict(record) for record in records])
        return result


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def now_iso(self) -> str:
        return self.now().isoformat(timespec="seconds")


class ExecutionAttemptRepository:
    def create(self, attempt: ExecutionAttempt) -> ExecutionAttempt:
        def mutate(records: list[ExecutionAttempt]):
            records.append(attempt)
            return True, attempt

        return _mutate_records(attempts_path(), ExecutionAttempt, mutate)

    def save(self, attempt: ExecutionAttempt) -> ExecutionAttempt:
        def mutate(records: list[ExecutionAttempt]):
            for index, record in enumerate(records):
                if record.id == attempt.id:
                    records[index] = attempt
                    return True, attempt
            records.append(attempt)
            return True, attempt

        return _mutate_records(attempts_path(), ExecutionAttempt, mutate)

    def get(self, attempt_id: str) -> ExecutionAttempt | None:
        return next((record for record in self.list_all() if record.id == attempt_id), None)

    def list_all(self, *, workspace_id: str = "") -> list[ExecutionAttempt]:
        records = _load_records(attempts_path(), ExecutionAttempt)
        if workspace_id:
            records = [record for record in records if record.workspace_id == workspace_id]
        return sorted(records, key=lambda item: (item.started_at, item.id))

    def list_by_target(self, target_id: str) -> list[ExecutionAttempt]:
        records = [record for record in self.list_all() if record.publication_target_id == target_id]
        return sorted(records, key=lambda item: (item.attempt_number, item.started_at, item.id))

    def latest_for_target(self, target_id: str) -> ExecutionAttempt | None:
        records = self.list_by_target(target_id)
        return records[-1] if records else None

    def next_attempt_number(self, target_id: str) -> int:
        return max((item.attempt_number for item in self.list_by_target(target_id)), default=0) + 1

    def find_by_idempotency_key(self, idempotency_key: str) -> ExecutionAttempt | None:
        return next((record for record in self.list_all() if record.idempotency_key == idempotency_key), None)


class ExecutionLeaseRepository:
    def active_for_target(self, target_id: str, *, now: datetime | None = None) -> ExecutionLease | None:
        current = now or datetime.now(UTC)
        for lease in self.list_all():
            if lease.target_id == target_id and lease.status == ExecutionLeaseStatus.ACTIVE.value:
                expires = _parse_time(lease.expires_at)
                if expires is None or expires <= current:
                    continue
                return lease
        return None

    def list_all(self) -> list[ExecutionLease]:
        return _load_records(leases_path(), ExecutionLease)

    def get(self, lease_id: str) -> ExecutionLease | None:
        return next((record for record in self.list_all() if record.id == lease_id), None)

    def claim(
        self,
        *,
        target_id: str,
        attempt_id: str,
        worker_id: str,
        ttl_seconds: int,
        now: datetime,
    ) -> ExecutionLease:
        def mutate(records: list[ExecutionLease]):
            for record in records:
                if record.target_id != target_id or record.status != ExecutionLeaseStatus.ACTIVE.value:
                    continue
                expires = _parse_time(record.expires_at)
                if expires is not None and expires > now:
                    raise RuntimeError("execution.lease_active")
                record.status = ExecutionLeaseStatus.EXPIRED.value
                record.version += 1
            lease = ExecutionLease(
                id=f"execution_lease_{uuid4().hex}",
                target_id=target_id,
                attempt_id=attempt_id,
                worker_id=worker_id,
                claimed_at=now.isoformat(timespec="seconds"),
                heartbeat_at=now.isoformat(timespec="seconds"),
                expires_at=(now + timedelta(seconds=max(ttl_seconds, 1))).isoformat(timespec="seconds"),
            )
            records.append(lease)
            return True, lease

        return _mutate_records(leases_path(), ExecutionLease, mutate)

    def renew(self, lease_id: str, *, worker_id: str, ttl_seconds: int, now: datetime) -> ExecutionLease:
        def mutate(records: list[ExecutionLease]):
            for record in records:
                if (
                    record.id == lease_id
                    and record.worker_id == worker_id
                    and record.status == ExecutionLeaseStatus.ACTIVE.value
                ):
                    record.heartbeat_at = now.isoformat(timespec="seconds")
                    record.expires_at = (now + timedelta(seconds=max(ttl_seconds, 1))).isoformat(timespec="seconds")
                    record.version += 1
                    return True, record
            raise RuntimeError("execution.lease_not_found")

        return _mutate_records(leases_path(), ExecutionLease, mutate)

    def release(self, lease_id: str, *, worker_id: str, now: datetime) -> ExecutionLease:
        def mutate(records: list[ExecutionLease]):
            for record in records:
                if record.id == lease_id and (not worker_id or record.worker_id == worker_id):
                    record.status = ExecutionLeaseStatus.RELEASED.value
                    record.released_at = now.isoformat(timespec="seconds")
                    record.version += 1
                    return True, record
            raise RuntimeError("execution.lease_not_found")

        return _mutate_records(leases_path(), ExecutionLease, mutate)

    def expire_due(self, *, now: datetime) -> list[ExecutionLease]:
        expired: list[ExecutionLease] = []

        def mutate(records: list[ExecutionLease]):
            changed = False
            for record in records:
                if record.status != ExecutionLeaseStatus.ACTIVE.value:
                    continue
                expires = _parse_time(record.expires_at)
                if expires is not None and expires <= now:
                    record.status = ExecutionLeaseStatus.EXPIRED.value
                    record.version += 1
                    expired.append(record)
                    changed = True
            return changed, expired

        return _mutate_records(leases_path(), ExecutionLease, mutate)


class ExecutionRetryPolicy:
    max_attempts = 3
    max_delay_seconds = 3600

    def decide(
        self,
        *,
        safe_error_code: str,
        phase: str,
        mutation_state: str,
        retry_count: int,
        provider_health: str = "ready",
        account_status: str = "connected",
        now: datetime | None = None,
    ) -> RetryDecision:
        current = now or datetime.now(UTC)
        if mutation_state in {
            MutationState.MUTATION_STARTED.value,
            MutationState.MUTATION_ACKNOWLEDGED.value,
            MutationState.MUTATION_UNCERTAIN.value,
        }:
            return RetryDecision(
                RetryAction.MARK_UNCERTAIN.value,
                retryable=False,
                automatic=False,
                requires_confirmation=True,
                reason_code="mutation_may_have_started",
            )
        if mutation_state == MutationState.MUTATION_VERIFIED.value:
            return RetryDecision(RetryAction.NO_RETRY.value, False, False, reason_code="already_verified")
        if safe_error_code in {"authentication_required", "needs_login"} or account_status in {
            "needs_login",
            "not_configured",
        }:
            return RetryDecision(
                RetryAction.WAIT_FOR_AUTHENTICATION.value,
                retryable=True,
                automatic=False,
                requires_confirmation=True,
                reason_code="authentication_required",
            )
        if safe_error_code in {"global_kill_switch", "account_kill_switch", "target_cancelled"}:
            return RetryDecision(RetryAction.NO_RETRY.value, False, False, reason_code=safe_error_code)
        if retry_count >= self.max_attempts:
            return RetryDecision(RetryAction.MARK_FAILED.value, False, False, reason_code="maximum_attempts")
        if provider_health not in {"ready", "connected", ""}:
            delay = min(300 * (retry_count + 1), self.max_delay_seconds)
            return RetryDecision(
                RetryAction.WAIT_FOR_PROVIDER.value,
                retryable=True,
                automatic=False,
                delay_seconds=delay,
                next_retry_at=(current + timedelta(seconds=delay)).isoformat(timespec="seconds"),
                reason_code="provider_unavailable",
            )
        retryable_codes = {
            "database_lock",
            "jobqueue_unavailable",
            "network_before_mutation",
            "rate_limit_before_mutation",
            "provider_transient",
            "worker_shutdown_before_mutation",
            "expired_lease_pre_mutation",
        }
        if safe_error_code in retryable_codes and phase in {
            ExecutionPhase.PREFLIGHT.value,
            ExecutionPhase.SNAPSHOT_VALIDATION.value,
            ExecutionPhase.JOB_CREATION.value,
            ExecutionPhase.JOB_CLAIM.value,
        }:
            delay = min((2**retry_count) * 30, self.max_delay_seconds)
            return RetryDecision(
                RetryAction.RETRY_AUTOMATICALLY.value,
                retryable=True,
                automatic=True,
                delay_seconds=delay,
                next_retry_at=(current + timedelta(seconds=delay)).isoformat(timespec="seconds"),
                reason_code=safe_error_code,
            )
        return RetryDecision(RetryAction.NO_RETRY.value, False, False, reason_code=safe_error_code or "not_retryable")


class ExecutionReconciliationService:
    def __init__(self, execution_service: PublicationExecutionService) -> None:
        self.execution_service = execution_service

    def reconcile_target(self, target_id: str, *, workspace_id: str, dry_run: bool = False) -> ReconciliationResult:
        service = self.execution_service
        target = service.planning_service.target_repository.get(target_id)
        if target is None or target.workspace_id != workspace_id:
            return ReconciliationResult(ReconciliationClassification.ATTEMPT_MISSING.value, target_id)
        attempts = service.attempt_repository.list_by_target(target.id)
        attempt = attempts[-1] if attempts else None
        if attempt is None:
            return ReconciliationResult(ReconciliationClassification.ATTEMPT_MISSING.value, target.id)
        job = (
            channel_store.get_publish_job(attempt.job_id or target.job_id)
            if (attempt.job_id or target.job_id)
            else None
        )
        publication = channel_store.find_published_post_for_derivative(job.derivative_id) if job is not None else None
        classification = ReconciliationClassification.CONSISTENT_PENDING.value
        if job is None and target.status == PublicationTargetStatus.QUEUED.value:
            classification = ReconciliationClassification.JOB_MISSING.value
            if not dry_run:
                target.status = PublicationTargetStatus.READY.value
                service.planning_service.target_repository.save(target)
        elif job is not None and job.status == "running":
            classification = ReconciliationClassification.CONSISTENT_RUNNING.value
            if not dry_run:
                target.status = PublicationTargetStatus.RUNNING.value
                attempt.status = ExecutionAttemptStatus.RUNNING.value
                attempt.phase = ExecutionPhase.REMOTE_MUTATION.value
                service.attempt_repository.save(attempt)
                service.planning_service.target_repository.save(target)
        elif job is not None and job.status == "success":
            if publication is None:
                classification = ReconciliationClassification.JOB_SUCCEEDED_EVIDENCE_MISSING.value
            else:
                classification = ReconciliationClassification.CONSISTENT_SUCCEEDED.value
                if not dry_run:
                    target.status = PublicationTargetStatus.PUBLISHED.value
                    target.publication_id = publication.id
                    attempt.status = ExecutionAttemptStatus.SUCCEEDED.value
                    attempt.publication_id = publication.id
                    attempt.completed_at = service.clock.now_iso()
                    attempt.phase = ExecutionPhase.RECONCILIATION.value
                    attempt.mutation_state = MutationState.MUTATION_VERIFIED.value
                    attempt.remote_verification_state = "verified"
                    service.attempt_repository.save(attempt)
                    service.planning_service.target_repository.save(target)
        elif job is not None and job.status == "manual_verification_required":
            classification = ReconciliationClassification.CONSISTENT_UNCERTAIN.value
            if not dry_run:
                target.status = PublicationTargetStatus.UNCERTAIN.value
                attempt.status = ExecutionAttemptStatus.UNCERTAIN.value
                attempt.mutation_state = MutationState.MUTATION_UNCERTAIN.value
                attempt.remote_verification_state = "manual_review_required"
                attempt.completed_at = service.clock.now_iso()
                service.attempt_repository.save(attempt)
                service.planning_service.target_repository.save(target)
        elif job is not None and job.status in {"failed", "cancelled"}:
            classification = ReconciliationClassification.CONSISTENT_FAILED.value
            if not dry_run:
                target.status = (
                    PublicationTargetStatus.FAILED.value
                    if job.status == "failed"
                    else PublicationTargetStatus.CANCELLED.value
                )
                attempt.status = (
                    ExecutionAttemptStatus.FAILED.value
                    if job.status == "failed"
                    else ExecutionAttemptStatus.CANCELLED.value
                )
                attempt.safe_error_code = job.error_code
                attempt.completed_at = service.clock.now_iso()
                service.attempt_repository.save(attempt)
                service.planning_service.target_repository.save(target)
        if not dry_run:
            service.derive_plan_status(target.publication_plan_id, workspace_id=workspace_id)
        return ReconciliationResult(
            classification, target.id, attempt.id, job.id if job else "", not dry_run, target.status
        )


class PublicationExecutionService:
    def __init__(
        self,
        *,
        app_runtime,
        config,
        planning_service: PublicationPlanningService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.app_runtime = app_runtime
        self.config = config
        self.planning_service = planning_service or app_runtime.publication_planning_service(config)
        self.attempt_repository = ExecutionAttemptRepository()
        self.lease_repository = ExecutionLeaseRepository()
        self.retry_policy = ExecutionRetryPolicy()
        self.clock = clock or Clock()
        self.reconciliation_service = ExecutionReconciliationService(self)

    def find_due_targets(
        self, *, workspace_id: str = "", batch_size: int = 25, dry_run: bool = True
    ) -> list[DuePublicationTarget]:
        now = self.clock.now()
        candidates: list[DuePublicationTarget] = []
        for target in self.planning_service.target_repository.list_all(workspace_id=workspace_id):
            plan = self.planning_service.plan_repository.get(target.publication_plan_id)
            if plan is None:
                continue
            due = self._due_candidate(plan, target, now=now)
            if due is not None:
                if due.blockers and not dry_run:
                    continue
                candidates.append(due)
        candidates.sort(
            key=lambda item: (item.resolved_scheduled_at_utc or "", item.position, item.publication_target_id)
        )
        return candidates[: max(min(batch_size, 100), 1)]

    def claim_target(
        self, target_id: str, *, worker_id: str = "", ttl_seconds: int = 300, trigger: str = "manual"
    ) -> ExecutionAttempt:
        target = self._target_or_error(target_id)
        plan = self._plan_or_error(target.publication_plan_id)
        self._ensure_no_active_or_terminal_attempt(target)
        attempt = ExecutionAttempt(
            id=f"execution_attempt_{uuid4().hex}",
            workspace_id=target.workspace_id,
            publication_plan_id=plan.id,
            publication_target_id=target.id,
            attempt_number=self.attempt_repository.next_attempt_number(target.id),
            snapshot_checksum=target.snapshot_checksum,
            idempotency_key=self._idempotency_key(target),
            status=ExecutionAttemptStatus.CREATED.value,
            trigger=trigger,
            worker_id=worker_id or self._worker_id(),
            started_at=self.clock.now_iso(),
            heartbeat_at=self.clock.now_iso(),
        )
        attempt = self.attempt_repository.create(attempt)
        try:
            lease = self.lease_repository.claim(
                target_id=target.id,
                attempt_id=attempt.id,
                worker_id=attempt.worker_id,
                ttl_seconds=ttl_seconds,
                now=self.clock.now(),
            )
        except Exception:
            attempt.status = ExecutionAttemptStatus.BLOCKED.value
            attempt.safe_error_code = "lease_conflict"
            self.attempt_repository.save(attempt)
            raise
        attempt.lease_id = lease.id
        attempt.status = ExecutionAttemptStatus.CLAIMED.value
        self.attempt_repository.save(attempt)
        self._event("publication.target.claimed", target.workspace_id, plan.id, target.id, attempt.id)
        self._audit("claim", target.workspace_id, plan.id, target.id, attempt.id, actor=attempt.worker_id)
        return attempt

    def renew_claim(self, lease_id: str, *, worker_id: str, ttl_seconds: int = 300) -> ExecutionLease:
        lease = self.lease_repository.renew(
            lease_id, worker_id=worker_id, ttl_seconds=ttl_seconds, now=self.clock.now()
        )
        attempt = self.attempt_repository.get(lease.attempt_id)
        if attempt is not None:
            attempt.heartbeat_at = lease.heartbeat_at
            self.attempt_repository.save(attempt)
        self._event("publication.target.lease_renewed", "", "", lease.target_id, lease.attempt_id)
        return lease

    def release_claim(self, lease_id: str, *, worker_id: str = "") -> ExecutionLease:
        return self.lease_repository.release(lease_id, worker_id=worker_id, now=self.clock.now())

    def dispatch_target(
        self,
        target_id: str,
        *,
        worker_id: str = "",
        actor: str = "system",
        confirmation: bool = False,
        ttl_seconds: int = 300,
    ) -> ExecutionAttempt:
        target = self._target_or_error(target_id)
        attempt = self.claim_target(target_id, worker_id=worker_id, ttl_seconds=ttl_seconds, trigger=actor)
        try:
            attempt.status = ExecutionAttemptStatus.VALIDATING.value
            attempt.phase = ExecutionPhase.SNAPSHOT_VALIDATION.value
            self.attempt_repository.save(attempt)
            self._preflight_or_raise(target, attempt, confirmation=confirmation)
            attempt.status = ExecutionAttemptStatus.DISPATCHING.value
            attempt.phase = ExecutionPhase.JOB_CREATION.value
            self.attempt_repository.save(attempt)
            queued = self.planning_service.queue_target(
                target.id,
                workspace_id=target.workspace_id,
                actor=actor,
                confirmation=True,
            )
            attempt.job_id = queued.job_id
            attempt.status = ExecutionAttemptStatus.QUEUED.value
            attempt.phase = ExecutionPhase.JOB_CLAIM.value
            attempt.mutation_state = MutationState.NOT_STARTED.value
            attempt.metadata = {**attempt.metadata, "dispatch_generation": self._generation(target)}
            self.attempt_repository.save(attempt)
            self.release_claim(attempt.lease_id, worker_id=attempt.worker_id)
            self._event(
                "publication.target.dispatched", target.workspace_id, attempt.publication_plan_id, target.id, attempt.id
            )
            self._audit(
                "dispatch",
                target.workspace_id,
                attempt.publication_plan_id,
                target.id,
                attempt.id,
                job_id=attempt.job_id,
                actor=actor,
            )
            self.derive_plan_status(target.publication_plan_id, workspace_id=target.workspace_id)
            return attempt
        except Exception as exc:
            attempt.status = ExecutionAttemptStatus.BLOCKED.value
            attempt.safe_error_code = getattr(exc, "code", str(exc))
            attempt.completed_at = self.clock.now_iso()
            self.attempt_repository.save(attempt)
            try:
                self.release_claim(attempt.lease_id, worker_id=attempt.worker_id)
            except Exception:
                pass
            target.status = (
                PublicationTargetStatus.STALE.value
                if attempt.safe_error_code == "publication.target_stale"
                else "blocked"
            )
            self.planning_service.target_repository.save(target)
            self._event(
                "publication.target.blocked", target.workspace_id, attempt.publication_plan_id, target.id, attempt.id
            )
            self._audit(
                "dispatch",
                target.workspace_id,
                attempt.publication_plan_id,
                target.id,
                attempt.id,
                actor=actor,
                result="blocked",
                reason_code=attempt.safe_error_code,
            )
            raise

    def dispatch_due_targets(
        self, *, workspace_id: str = "", batch_size: int = 10, dry_run: bool = False, worker_id: str = ""
    ) -> dict[str, Any]:
        due = self.find_due_targets(workspace_id=workspace_id, batch_size=batch_size, dry_run=dry_run)
        if dry_run:
            return {"dry_run": True, "due": [asdict(item) for item in due], "dispatched": []}
        dispatched: list[dict[str, str]] = []
        blocked: list[dict[str, str]] = []
        for item in due:
            try:
                attempt = self.dispatch_target(
                    item.publication_target_id,
                    worker_id=worker_id or self._worker_id(),
                    actor="dispatcher",
                    confirmation=True,
                )
                dispatched.append(
                    {"target_id": item.publication_target_id, "attempt_id": attempt.id, "job_id": attempt.job_id}
                )
            except Exception as exc:
                blocked.append({"target_id": item.publication_target_id, "code": getattr(exc, "code", str(exc))})
        self._state_update("last_dispatch_run_at", self.clock.now_iso())
        if dispatched:
            self._state_update("last_successful_dispatch_run_at", self.clock.now_iso())
        return {"dry_run": False, "due": [asdict(item) for item in due], "dispatched": dispatched, "blocked": blocked}

    def reconcile_target(self, target_id: str, *, workspace_id: str, dry_run: bool = False) -> ReconciliationResult:
        result = self.reconciliation_service.reconcile_target(target_id, workspace_id=workspace_id, dry_run=dry_run)
        self._state_update("last_reconciliation_at", self.clock.now_iso())
        return result

    def reconcile_plan(self, plan_id: str, *, workspace_id: str, dry_run: bool = False) -> list[ReconciliationResult]:
        results = [
            self.reconcile_target(target.id, workspace_id=workspace_id, dry_run=dry_run)
            for target in self.planning_service.target_repository.list_by_plan(plan_id)
        ]
        if not dry_run:
            self.derive_plan_status(plan_id, workspace_id=workspace_id)
        return results

    def cancel_target_execution(
        self, target_id: str, *, workspace_id: str, actor: str = "", reason: str = ""
    ) -> PublicationTarget:
        target = self._target_or_error(target_id, workspace_id=workspace_id)
        attempt = self.attempt_repository.latest_for_target(target.id)
        if attempt and attempt.status not in TERMINAL_ATTEMPTS:
            if attempt.mutation_state in POST_MUTATION_STATES:
                target.status = PublicationTargetStatus.UNCERTAIN.value
                attempt.status = ExecutionAttemptStatus.UNCERTAIN.value
                attempt.mutation_state = MutationState.MUTATION_UNCERTAIN.value
            else:
                target.status = PublicationTargetStatus.CANCELLED.value
                attempt.status = ExecutionAttemptStatus.CANCELLED.value
            attempt.completed_at = self.clock.now_iso()
            self.attempt_repository.save(attempt)
        else:
            target.status = PublicationTargetStatus.CANCELLED.value
        target.updated_at = channel_store.now_iso()
        self.planning_service.target_repository.save(target)
        self.derive_plan_status(target.publication_plan_id, workspace_id=workspace_id)
        self._event(
            "publication.target.cancelled",
            workspace_id,
            target.publication_plan_id,
            target.id,
            attempt.id if attempt else "",
        )
        self._audit(
            "cancellation",
            workspace_id,
            target.publication_plan_id,
            target.id,
            attempt.id if attempt else "",
            actor=actor,
            reason_code=reason,
        )
        return target

    def retry_target(
        self, target_id: str, *, workspace_id: str, actor: str = "", confirmation: bool = False
    ) -> RetryDecision:
        target = self._target_or_error(target_id, workspace_id=workspace_id)
        latest = self.attempt_repository.latest_for_target(target.id)
        if latest is None:
            return RetryDecision(
                RetryAction.RETRY_AFTER_REVALIDATION.value,
                True,
                False,
                requires_confirmation=True,
                reason_code="attempt_missing",
            )
        decision = self.retry_policy.decide(
            safe_error_code=latest.safe_error_code,
            phase=latest.phase,
            mutation_state=latest.mutation_state,
            retry_count=latest.retry_count,
            account_status=(channel_store.get_channel_connection(target.channel_account_id) or object()).status
            if channel_store.get_channel_connection(target.channel_account_id)
            else "",
            now=self.clock.now(),
        )
        if decision.automatic or (confirmation and decision.retryable and latest.mutation_state in PRE_MUTATION_STATES):
            latest.retry_count += 1
            latest.next_retry_at = decision.next_retry_at
            latest.status = ExecutionAttemptStatus.SUPERSEDED.value
            self.attempt_repository.save(latest)
            target.status = PublicationTargetStatus.READY.value
            target.job_id = ""
            self.planning_service.target_repository.save(target)
            self._audit(
                "manual_retry" if confirmation else "automatic_retry",
                workspace_id,
                target.publication_plan_id,
                target.id,
                latest.id,
                actor=actor,
                reason_code=decision.reason_code,
            )
        return decision

    def recover_expired_claims(self) -> list[ReconciliationResult]:
        expired = self.lease_repository.expire_due(now=self.clock.now())
        results: list[ReconciliationResult] = []
        for lease in expired:
            attempt = self.attempt_repository.get(lease.attempt_id)
            if attempt is None:
                results.append(
                    ReconciliationResult(ReconciliationClassification.ATTEMPT_MISSING.value, lease.target_id)
                )
                continue
            target = self.planning_service.target_repository.get(lease.target_id)
            if target is None:
                continue
            if attempt.mutation_state in PRE_MUTATION_STATES:
                attempt.status = ExecutionAttemptStatus.ABANDONED.value
                attempt.safe_error_code = "expired_lease_pre_mutation"
                attempt.completed_at = self.clock.now_iso()
                target.status = PublicationTargetStatus.READY.value
                classification = ReconciliationClassification.LEASE_EXPIRED_PRE_MUTATION.value
            else:
                attempt.status = ExecutionAttemptStatus.UNCERTAIN.value
                attempt.mutation_state = MutationState.MUTATION_UNCERTAIN.value
                attempt.safe_error_code = "expired_lease_post_mutation"
                attempt.completed_at = self.clock.now_iso()
                target.status = PublicationTargetStatus.UNCERTAIN.value
                classification = ReconciliationClassification.LEASE_EXPIRED_POST_MUTATION.value
            self.attempt_repository.save(attempt)
            self.planning_service.target_repository.save(target)
            self._event(
                "publication.attempt.abandoned",
                attempt.workspace_id,
                attempt.publication_plan_id,
                target.id,
                attempt.id,
            )
            results.append(
                ReconciliationResult(classification, target.id, attempt.id, attempt.job_id, True, target.status)
            )
        self._state_update("last_recovery_at", self.clock.now_iso())
        return results

    def resolve_uncertain(
        self,
        attempt_id: str,
        *,
        resolution: str,
        resolved_by: str,
        reason: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> UncertainResolution:
        attempt = self.attempt_repository.get(attempt_id)
        if attempt is None:
            raise RuntimeError("execution.attempt_not_found")
        target = self._target_or_error(attempt.publication_target_id, workspace_id=attempt.workspace_id)
        record = UncertainResolution(
            attempt_id=attempt.id,
            resolution=resolution,
            resolved_by=resolved_by,
            resolved_at=self.clock.now_iso(),
            reason=reason,
            evidence=_safe_metadata(evidence),
        )
        with _list_store(resolutions_path()) as store:
            records = store.read()
            records.append(asdict(record))
            store.write(records)
        if resolution == "published_verified":
            target.status = PublicationTargetStatus.PUBLISHED.value
            attempt.status = ExecutionAttemptStatus.SUCCEEDED.value
            attempt.mutation_state = MutationState.MUTATION_VERIFIED.value
        elif resolution == "not_published_verified":
            target.status = PublicationTargetStatus.FAILED.value
            attempt.status = ExecutionAttemptStatus.FAILED.value
        else:
            target.status = PublicationTargetStatus.UNCERTAIN.value if resolution == "cannot_determine" else "blocked"
            attempt.status = ExecutionAttemptStatus.UNCERTAIN.value
        attempt.remote_verification_state = resolution
        attempt.completed_at = self.clock.now_iso()
        self.attempt_repository.save(attempt)
        self.planning_service.target_repository.save(target)
        self._audit(
            "uncertain_resolution",
            attempt.workspace_id,
            attempt.publication_plan_id,
            target.id,
            attempt.id,
            actor=resolved_by,
            reason_code=resolution,
        )
        return record

    def report_job_phase(
        self,
        *,
        job_id: str,
        phase: str,
        mutation_state: str | None = None,
        status: str | None = None,
        remote_verification_state: str = "",
        safe_error_code: str = "",
    ) -> ExecutionAttempt | None:
        attempt = next((item for item in self.attempt_repository.list_all() if item.job_id == job_id), None)
        if attempt is None:
            return None
        attempt.phase = phase
        attempt.heartbeat_at = self.clock.now_iso()
        if mutation_state is not None:
            attempt.mutation_state = mutation_state
        if status is not None:
            attempt.status = status
        if remote_verification_state:
            attempt.remote_verification_state = remote_verification_state
        if safe_error_code:
            attempt.safe_error_code = safe_error_code
        self.attempt_repository.save(attempt)
        return attempt

    def derive_plan_status(self, plan_id: str, *, workspace_id: str) -> PublicationPlan:
        plan = self._plan_or_error(plan_id, workspace_id=workspace_id)
        targets = self.planning_service.target_repository.list_by_plan(plan.id)
        old_status = plan.status
        statuses = {target.status for target in targets}
        if not targets:
            plan.status = PublicationPlanStatus.DRAFT.value
        elif statuses <= {PublicationTargetStatus.CANCELLED.value}:
            plan.status = PublicationPlanStatus.CANCELLED.value
        elif PublicationTargetStatus.UNCERTAIN.value in statuses:
            plan.status = "attention_required"
        elif statuses <= {PublicationTargetStatus.PUBLISHED.value}:
            plan.status = PublicationPlanStatus.COMPLETED.value
        elif PublicationTargetStatus.PUBLISHED.value in statuses and (
            PublicationTargetStatus.FAILED.value in statuses or "blocked" in statuses
        ):
            plan.status = "partially_failed"
        elif PublicationTargetStatus.PUBLISHED.value in statuses:
            plan.status = PublicationPlanStatus.PARTIALLY_COMPLETED.value
        elif PublicationTargetStatus.RUNNING.value in statuses or PublicationTargetStatus.QUEUED.value in statuses:
            plan.status = PublicationPlanStatus.RUNNING.value
        elif statuses <= {
            PublicationTargetStatus.READY.value,
            "scheduled",
            PublicationTargetStatus.AWAITING_CONFIRMATION.value,
        }:
            plan.status = (
                PublicationPlanStatus.SCHEDULED.value if "scheduled" in statuses else PublicationPlanStatus.READY.value
            )
        elif (
            PublicationTargetStatus.INVALID.value in statuses
            or PublicationTargetStatus.STALE.value in statuses
            or "blocked" in statuses
        ):
            plan.status = PublicationPlanStatus.BLOCKED.value
        else:
            plan.status = PublicationPlanStatus.DRAFT.value
        plan.updated_at = channel_store.now_iso()
        saved = self.planning_service.plan_repository.save(plan)
        if old_status != plan.status:
            self._event("publication.plan.status_changed", workspace_id, plan.id, "", "")
            self._audit(
                "plan_status_changed", workspace_id, plan.id, "", "", reason_code=f"{old_status}->{plan.status}"
            )
        return saved

    def health_check(self) -> dict[str, Any]:
        leases = self.lease_repository.list_all()
        attempts = self.attempt_repository.list_all()
        due = self.find_due_targets(batch_size=100, dry_run=True)
        state = {}
        with _dict_store(state_path()) as store:
            state = store.read()
        return {
            "status": "ready",
            "execution_framework_version": EXECUTION_FRAMEWORK_VERSION,
            "dispatcher_contract_version": PUBLICATION_DISPATCHER_CONTRACT_VERSION,
            "attempt_contract_version": EXECUTION_ATTEMPT_CONTRACT_VERSION,
            "lease_contract_version": EXECUTION_LEASE_CONTRACT_VERSION,
            "reconciliation_contract_version": EXECUTION_RECONCILIATION_CONTRACT_VERSION,
            "retry_policy_contract_version": EXECUTION_RETRY_POLICY_CONTRACT_VERSION,
            "active_leases": sum(1 for lease in leases if lease.status == ExecutionLeaseStatus.ACTIVE.value),
            "expired_leases": sum(1 for lease in leases if lease.status == ExecutionLeaseStatus.EXPIRED.value),
            "due_targets": len(due),
            "blocked_targets": sum(1 for attempt in attempts if attempt.status == ExecutionAttemptStatus.BLOCKED.value),
            "uncertain_targets": sum(
                1 for attempt in attempts if attempt.status == ExecutionAttemptStatus.UNCERTAIN.value
            ),
            "last_dispatch_run_at": state.get("last_dispatch_run_at", ""),
            "last_successful_dispatch_run_at": state.get("last_successful_dispatch_run_at", ""),
            "last_reconciliation_at": state.get("last_reconciliation_at", ""),
        }

    def _due_candidate(
        self, plan: PublicationPlan, target: PublicationTarget, *, now: datetime
    ) -> DuePublicationTarget | None:
        blockers: list[str] = []
        if plan.status in {
            PublicationPlanStatus.CANCELLED.value,
            PublicationPlanStatus.BLOCKED.value,
            PublicationPlanStatus.ARCHIVED.value,
        }:
            return None
        if target.status not in {
            PublicationTargetStatus.READY.value,
            "scheduled",
            PublicationTargetStatus.AWAITING_CONFIRMATION.value,
        }:
            return None
        resolved_at, error = _scheduled_utc(target.scheduled_at, target.timezone)
        if error:
            blockers.append(error)
        if resolved_at and resolved_at > now:
            return None
        if not target.snapshot_checksum:
            blockers.append("snapshot_missing")
        stale = self.planning_service.is_target_stale(target.id, workspace_id=target.workspace_id)
        if stale.get("stale"):
            blockers.append("target_stale")
        if self.lease_repository.active_for_target(target.id, now=now):
            blockers.append("active_lease")
        if any(
            attempt.status == ExecutionAttemptStatus.SUCCEEDED.value
            for attempt in self.attempt_repository.list_by_target(target.id)
        ):
            blockers.append("successful_attempt_exists")
        if any(
            attempt.status == ExecutionAttemptStatus.UNCERTAIN.value
            for attempt in self.attempt_repository.list_by_target(target.id)
        ):
            blockers.append("uncertain_attempt_requires_review")
        connection = channel_store.get_channel_connection(target.channel_account_id)
        if connection is None:
            blockers.append("authentication_required")
        elif connection.status not in {"connected", "ready"}:
            blockers.append("authentication_required")
        if getattr(self.config, "publication_execution_kill_switch", False):
            blockers.append("global_kill_switch")
        if target.channel_account_id in set(
            getattr(self.config, "publication_execution_account_kill_switches", []) or []
        ):
            blockers.append("account_kill_switch")
        return DuePublicationTarget(
            publication_plan_id=plan.id,
            publication_target_id=target.id,
            workspace_id=target.workspace_id,
            scheduled_at=target.scheduled_at,
            resolved_scheduled_at_utc=(resolved_at or now).isoformat(timespec="seconds"),
            position=target.position,
            status=target.status,
            snapshot_checksum=target.snapshot_checksum,
            blockers=tuple(blockers),
        )

    def _preflight_or_raise(self, target: PublicationTarget, attempt: ExecutionAttempt, *, confirmation: bool) -> None:
        if not confirmation:
            raise RuntimeError("confirmation_required")
        if target.status == PublicationTargetStatus.CANCELLED.value:
            raise RuntimeError("target_cancelled")
        plan = self._plan_or_error(target.publication_plan_id, workspace_id=target.workspace_id)
        if plan.status == PublicationPlanStatus.CANCELLED.value:
            raise RuntimeError("plan_cancelled")
        if not target.snapshot_checksum or target.snapshot_checksum != attempt.snapshot_checksum:
            raise RuntimeError("snapshot_mismatch")
        stale = self.planning_service.is_target_stale(target.id, workspace_id=target.workspace_id)
        if stale.get("stale"):
            raise RuntimeError("publication.target_stale")
        connection = channel_store.get_channel_connection(target.channel_account_id)
        if connection is None or connection.status not in {"connected", "ready"}:
            raise RuntimeError("authentication_required")
        if getattr(self.config, "publication_execution_kill_switch", False):
            raise RuntimeError("global_kill_switch")
        if target.channel_account_id in set(
            getattr(self.config, "publication_execution_account_kill_switches", []) or []
        ):
            raise RuntimeError("account_kill_switch")
        latest = self.attempt_repository.latest_for_target(target.id)
        if (
            latest
            and latest.id != attempt.id
            and latest.status in {ExecutionAttemptStatus.SUCCEEDED.value, ExecutionAttemptStatus.UNCERTAIN.value}
        ):
            raise RuntimeError("terminal_or_uncertain_attempt_exists")

    def _ensure_no_active_or_terminal_attempt(self, target: PublicationTarget) -> None:
        for attempt in self.attempt_repository.list_by_target(target.id):
            if attempt.status in {ExecutionAttemptStatus.SUCCEEDED.value, ExecutionAttemptStatus.UNCERTAIN.value}:
                raise RuntimeError("execution.terminal_attempt_exists")
            if attempt.status not in TERMINAL_ATTEMPTS:
                if attempt.snapshot_checksum == target.snapshot_checksum and attempt.job_id:
                    raise RuntimeError("execution.active_attempt_exists")
                if self.lease_repository.active_for_target(target.id, now=self.clock.now()):
                    raise RuntimeError("execution.active_attempt_exists")

    def _idempotency_key(self, target: PublicationTarget) -> str:
        scheduled = target.scheduled_at or ""
        generation = self._generation(target)
        return hashlib.sha256(
            f"{target.id}|{target.snapshot_checksum}|{target.channel_account_id}|{target.capability}|{generation}|{scheduled}".encode()
        ).hexdigest()

    @staticmethod
    def _generation(target: PublicationTarget) -> str:
        return str((target.metadata or {}).get("execution_generation") or "1")

    @staticmethod
    def _worker_id() -> str:
        return f"worker_{os.getpid()}_{uuid4().hex[:8]}"

    def _target_or_error(self, target_id: str, *, workspace_id: str = "") -> PublicationTarget:
        target = self.planning_service.target_repository.get(target_id)
        if target is None or (workspace_id and target.workspace_id != workspace_id):
            raise RuntimeError("publication.target_not_found")
        return target

    def _plan_or_error(self, plan_id: str, *, workspace_id: str = "") -> PublicationPlan:
        plan = self.planning_service.plan_repository.get(plan_id)
        if plan is None or (workspace_id and plan.workspace_id != workspace_id):
            raise RuntimeError("publication.plan_not_found")
        return plan

    def _event(self, action: str, workspace_id: str, plan_id: str, target_id: str, attempt_id: str) -> None:
        with _list_store(events_path()) as store:
            records = store.read()
            records.append(
                {
                    "id": f"execution_event_{uuid4().hex}",
                    "workspace_id": workspace_id,
                    "action": action,
                    "publication_plan_id": plan_id,
                    "publication_target_id": target_id,
                    "attempt_id": attempt_id,
                    "created_at": self.clock.now_iso(),
                }
            )
            store.write(records)

    def _audit(
        self,
        action: str,
        workspace_id: str,
        plan_id: str,
        target_id: str,
        attempt_id: str,
        *,
        job_id: str = "",
        actor: str = "",
        reason_code: str = "",
        result: str = "ok",
    ) -> None:
        event = ExecutionAuditEvent(
            id=f"execution_audit_{uuid4().hex}",
            workspace_id=workspace_id,
            action=action,
            publication_plan_id=plan_id,
            publication_target_id=target_id,
            attempt_id=attempt_id,
            job_id=job_id,
            actor=actor,
            reason_code=reason_code,
            result=result,
            snapshot_checksum=(
                self.attempt_repository.get(attempt_id).snapshot_checksum[:16]
                if attempt_id and self.attempt_repository.get(attempt_id)
                else ""
            ),
            created_at=self.clock.now_iso(),
        )
        with _list_store(audit_path()) as store:
            records = store.read()
            records.append(asdict(event))
            store.write(records)

    def _state_update(self, key: str, value: str) -> None:
        with _dict_store(state_path()) as store:
            payload = store.read()
            payload[key] = value
            store.write(payload)


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _scheduled_utc(value: str, timezone_id: str) -> tuple[datetime | None, str]:
    if not value:
        return None, ""
    try:
        zone = ZoneInfo(timezone_id or "UTC")
    except ZoneInfoNotFoundError:
        return None, "invalid_timezone"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None, "invalid_scheduled_time"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(UTC), ""


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in dict(metadata or {}).items():
        lowered = str(key).lower()
        if "path" in lowered or "storage" in lowered or "secret" in lowered or "token" in lowered:
            continue
        if isinstance(value, dict):
            safe[str(key)] = _safe_metadata(value)
        elif isinstance(value, list):
            safe[str(key)] = [str(item)[:200] for item in value if not isinstance(item, dict)]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
    return safe
