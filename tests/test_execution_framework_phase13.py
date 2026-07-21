from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import channel_store
from channel_models import ChannelConnection
from publication_execution import Clock
from src.core.execution import (
    EXECUTION_ATTEMPT_CONTRACT_VERSION,
    EXECUTION_FRAMEWORK_VERSION,
    EXECUTION_LEASE_CONTRACT_VERSION,
    EXECUTION_RECONCILIATION_CONTRACT_VERSION,
    EXECUTION_RETRY_POLICY_CONTRACT_VERSION,
    PUBLICATION_DISPATCHER_CONTRACT_VERSION,
    ExecutionAttemptStatus,
    ExecutionPhase,
    MutationState,
    RetryAction,
)
from tests.test_media_library_phase11 import Phase11Config, runtime_with_library
from tests.test_support import isolated_channel_store


class FixedClock(Clock):
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


class ExecutionFrameworkPhase13Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Phase11Config()
        self.config.media_dir = Path(self.tmp.name) / "tmp_media"
        self.config.content_dir = Path(self.tmp.name) / "content"
        self.config.media_storage_root = Path(self.tmp.name) / "media-root"
        self.config.linkedin_user_data_dir = Path(self.tmp.name) / "profile"
        self.config.media_dir.mkdir()
        self.config.content_dir.mkdir()
        self.config.linkedin_user_data_dir.mkdir()
        self.runtime = runtime_with_library(self.config)
        self.runtime.content_service(self.config)
        self.runtime.publication_planning_service(self.config)
        self.runtime.publication_execution_service(self.config)
        self.execution = self.runtime.publication_execution_service(self.config)
        self.execution.clock = FixedClock(datetime(2026, 7, 21, 12, 0, tzinfo=UTC))
        self.planning = self.runtime.publication_planning_service(self.config)
        self.content_service = self.runtime.content_service(self.config)
        channel_store.save_channel_connection(
            ChannelConnection(
                id="connection_linkedin",
                channel_id="linkedin",
                mode="playwright_local",
                status="connected",
                created_at=channel_store.now_iso(),
                updated_at=channel_store.now_iso(),
            )
        )

    def prepared_target(self, *, scheduled_at: str = "", timezone: str = "UTC"):
        item = self.content_service.create_content(
            workspace_id="linkedin",
            title="Canonical",
            body="Ready body",
            created_by="tester",
        )
        plan = self.planning.create_plan(workspace_id="linkedin", content_item_id=item.id, name="Plan")
        target = self.planning.add_target(
            plan.id,
            workspace_id="linkedin",
            channel_plugin_id="channel.linkedin",
            channel_account_id="linkedin",
            capability="channel.publish.text",
            scheduled_at=scheduled_at,
            timezone=timezone,
        )
        target = self.planning.prepare_target(target.id, workspace_id="linkedin")
        return plan, target

    def test_contract_versions_and_health(self) -> None:
        self.assertEqual(EXECUTION_FRAMEWORK_VERSION, "0.1.0")
        self.assertEqual(PUBLICATION_DISPATCHER_CONTRACT_VERSION, "1.0")
        self.assertEqual(EXECUTION_ATTEMPT_CONTRACT_VERSION, "1.0")
        self.assertEqual(EXECUTION_LEASE_CONTRACT_VERSION, "1.0")
        self.assertEqual(EXECUTION_RECONCILIATION_CONTRACT_VERSION, "1.0")
        self.assertEqual(EXECUTION_RETRY_POLICY_CONTRACT_VERSION, "1.0")
        self.assertEqual(self.execution.health_check()["status"], "ready")

    def test_due_selection_timezones_ordering_and_batch_limit(self) -> None:
        _plan_a, target_a = self.prepared_target(scheduled_at="2026-07-21T13:00:00", timezone="Europe/Amsterdam")
        _plan_b, target_b = self.prepared_target(scheduled_at="2026-07-21T11:30:00+00:00")
        _plan_future, _future = self.prepared_target(scheduled_at="2026-07-22T12:30:00+00:00")
        due = self.execution.find_due_targets(workspace_id="linkedin", batch_size=1, dry_run=True)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].publication_target_id, target_a.id)
        due_all = self.execution.find_due_targets(workspace_id="linkedin", batch_size=10, dry_run=True)
        self.assertEqual([item.publication_target_id for item in due_all], [target_a.id, target_b.id])

    def test_due_selection_blocks_invalid_cancelled_stale_success_uncertain_and_active_lease(self) -> None:
        _plan, target = self.prepared_target(scheduled_at="2026-07-21T11:00:00", timezone="Invalid/Zone")
        self.assertIn(
            "invalid_timezone", self.execution.find_due_targets(workspace_id="linkedin", dry_run=True)[0].blockers
        )
        target.timezone = "UTC"
        target.status = "cancelled"
        self.planning.target_repository.save(target)
        self.assertEqual(self.execution.find_due_targets(workspace_id="linkedin", dry_run=True), [])
        _plan2, target2 = self.prepared_target()
        attempt = self.execution.claim_target(target2.id, worker_id="worker-a")
        blocked = self.execution.find_due_targets(workspace_id="linkedin", dry_run=True)
        self.assertIn(
            "active_lease", next(item for item in blocked if item.publication_target_id == target2.id).blockers
        )
        attempt.status = ExecutionAttemptStatus.UNCERTAIN.value
        self.execution.attempt_repository.save(attempt)
        self.execution.release_claim(attempt.lease_id, worker_id="worker-a")
        blocked = self.execution.find_due_targets(workspace_id="linkedin", dry_run=True)
        self.assertIn(
            "uncertain_attempt_requires_review",
            next(item for item in blocked if item.publication_target_id == target2.id).blockers,
        )

    def test_claim_lease_heartbeat_release_and_second_claim_rejected(self) -> None:
        _plan, target = self.prepared_target()
        attempt = self.execution.claim_target(target.id, worker_id="worker-a", ttl_seconds=60)
        self.assertEqual(attempt.status, ExecutionAttemptStatus.CLAIMED.value)
        with self.assertRaises(RuntimeError):
            self.execution.claim_target(target.id, worker_id="worker-b")
        lease = self.execution.renew_claim(attempt.lease_id, worker_id="worker-a", ttl_seconds=120)
        self.assertEqual(lease.version, 2)
        released = self.execution.release_claim(attempt.lease_id, worker_id="worker-a")
        self.assertEqual(released.status, "released")

    def test_dispatch_creates_existing_job_idempotently_without_browser(self) -> None:
        _plan, target = self.prepared_target()
        attempt = self.execution.dispatch_target(target.id, worker_id="worker-a", confirmation=True)
        self.assertEqual(attempt.status, ExecutionAttemptStatus.QUEUED.value)
        job = channel_store.get_publish_job(attempt.job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job.result_details_json["publication_target_id"], target.id)
        with self.assertRaises(RuntimeError):
            self.execution.dispatch_target(target.id, worker_id="worker-b", confirmation=True)
        self.assertEqual(self.runtime.browser_provider().actions, [])

    def test_dispatch_blocks_missing_confirmation_provider_and_stale_snapshot(self) -> None:
        _plan, target = self.prepared_target()
        with self.assertRaises(RuntimeError):
            self.execution.dispatch_target(target.id, confirmation=False)
        target.snapshot_checksum = "changed"
        self.planning.target_repository.save(target)
        with self.assertRaises(RuntimeError):
            self.execution.dispatch_target(target.id, confirmation=True)

    def test_retry_policy_pre_mutation_only_and_uncertain_resolution(self) -> None:
        decision = self.execution.retry_policy.decide(
            safe_error_code="network_before_mutation",
            phase=ExecutionPhase.JOB_CREATION.value,
            mutation_state=MutationState.NOT_STARTED.value,
            retry_count=0,
            now=self.execution.clock.now(),
        )
        self.assertEqual(decision.action, RetryAction.RETRY_AUTOMATICALLY.value)
        no_retry = self.execution.retry_policy.decide(
            safe_error_code="network_after_submit",
            phase=ExecutionPhase.REMOTE_MUTATION.value,
            mutation_state=MutationState.MUTATION_STARTED.value,
            retry_count=0,
            now=self.execution.clock.now(),
        )
        self.assertEqual(no_retry.action, RetryAction.MARK_UNCERTAIN.value)
        _plan, target = self.prepared_target()
        attempt = self.execution.claim_target(target.id, worker_id="worker-a")
        attempt.status = ExecutionAttemptStatus.UNCERTAIN.value
        attempt.mutation_state = MutationState.MUTATION_UNCERTAIN.value
        self.execution.attempt_repository.save(attempt)
        resolution = self.execution.resolve_uncertain(
            attempt.id,
            resolution="not_published_verified",
            resolved_by="operator",
            evidence={"remote_id": "safe"},
        )
        self.assertEqual(resolution.resolution, "not_published_verified")
        self.assertEqual(self.execution.attempt_repository.get(attempt.id).status, ExecutionAttemptStatus.FAILED.value)

    def test_recovery_pre_and_post_mutation(self) -> None:
        _plan, target = self.prepared_target()
        attempt = self.execution.claim_target(target.id, worker_id="worker-a", ttl_seconds=1)
        self.execution.clock.current += timedelta(seconds=2)
        result = self.execution.recover_expired_claims()[0]
        self.assertEqual(result.classification, "lease_expired_pre_mutation")
        self.assertEqual(
            self.execution.attempt_repository.get(attempt.id).status, ExecutionAttemptStatus.ABANDONED.value
        )
        _plan2, target2 = self.prepared_target()
        attempt2 = self.execution.claim_target(target2.id, worker_id="worker-a", ttl_seconds=1)
        attempt2.mutation_state = MutationState.MUTATION_STARTED.value
        self.execution.attempt_repository.save(attempt2)
        self.execution.clock.current += timedelta(seconds=2)
        result2 = self.execution.recover_expired_claims()[-1]
        self.assertEqual(result2.classification, "lease_expired_post_mutation")
        self.assertEqual(self.planning.target_repository.get(target2.id).status, "uncertain")

    def test_reconciliation_and_aggregate_status(self) -> None:
        plan, target = self.prepared_target()
        attempt = self.execution.dispatch_target(target.id, worker_id="worker-a", confirmation=True)
        job = channel_store.get_publish_job(attempt.job_id)
        job.status = "success"
        channel_store.save_publish_job(job)
        result = self.execution.reconcile_target(target.id, workspace_id="linkedin")
        self.assertEqual(result.classification, "job_succeeded_evidence_missing")
        job.status = "manual_verification_required"
        channel_store.save_publish_job(job)
        uncertain = self.execution.reconcile_target(target.id, workspace_id="linkedin")
        self.assertEqual(uncertain.classification, "consistent_uncertain")
        self.assertEqual(self.planning.plan_repository.get(plan.id).status, "attention_required")

    def test_cancellation_before_and_after_mutation(self) -> None:
        _plan, target = self.prepared_target()
        cancelled = self.execution.cancel_target_execution(target.id, workspace_id="linkedin", actor="operator")
        self.assertEqual(cancelled.status, "cancelled")
        _plan2, target2 = self.prepared_target()
        attempt = self.execution.claim_target(target2.id, worker_id="worker-a")
        attempt.mutation_state = MutationState.MUTATION_STARTED.value
        self.execution.attempt_repository.save(attempt)
        uncertain = self.execution.cancel_target_execution(target2.id, workspace_id="linkedin", actor="operator")
        self.assertEqual(uncertain.status, "uncertain")

    def test_attempt_payloads_have_no_paths_and_boundaries_hold(self) -> None:
        _plan, target = self.prepared_target()
        attempt = self.execution.dispatch_target(target.id, worker_id="worker-a", confirmation=True)
        serialized = json.dumps(attempt.__dict__)
        self.assertNotIn("local_path", serialized)
        self.assertNotIn("storage_reference", serialized)
        core_sources = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/core/execution").glob("*.py"))
        self.assertNotIn("channels.", core_sources)
        service_source = Path("publication_execution.py").read_text(encoding="utf-8")
        self.assertNotIn("LinkedIn", service_source)
        self.assertNotIn("browser_provider(", service_source)
        linkedin_publish = Path("channels/linkedin/worker/publish.py").read_text(encoding="utf-8")
        self.assertNotIn("ExecutionAttemptRepository", linkedin_publish)
        self.assertNotIn("ExecutionLeaseRepository", linkedin_publish)
