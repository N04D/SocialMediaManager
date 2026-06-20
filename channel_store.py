from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar
from uuid import uuid4

from channel_models import (
    ApprovalRecord,
    ChannelConnection,
    ChannelJobLog,
    ContentDerivative,
    MetricJob,
    PostMetricSnapshot,
    PublishJob,
    PublishedPost,
    WorkerHeartbeat,
)
from channel_storage import locked_json_store


ROOT_DIR = Path(__file__).resolve().parent
STUDIO_DATA_DIR = ROOT_DIR / "studio_data"
LOCKS_DIR = STUDIO_DATA_DIR / "locks"
CHANNEL_CONNECTIONS_PATH = STUDIO_DATA_DIR / "channel_connections.json"
CONTENT_DERIVATIVES_PATH = STUDIO_DATA_DIR / "content_derivatives.json"
APPROVALS_PATH = STUDIO_DATA_DIR / "approvals.json"
PUBLISH_JOBS_PATH = STUDIO_DATA_DIR / "publish_jobs.json"
PUBLISHED_POSTS_PATH = STUDIO_DATA_DIR / "published_posts.json"
METRIC_JOBS_PATH = STUDIO_DATA_DIR / "metric_jobs.json"
POST_METRIC_SNAPSHOTS_PATH = STUDIO_DATA_DIR / "post_metric_snapshots.json"
WORKER_HEARTBEATS_PATH = STUDIO_DATA_DIR / "worker_heartbeats.json"
CHANNEL_JOB_LOGS_PATH = STUDIO_DATA_DIR / "channel_job_logs.json"
CHANNEL_SCREENSHOTS_DIR = ROOT_DIR / "outbox" / "channel_screenshots"
PROFILE_ARCHIVE_DIR = STUDIO_DATA_DIR / "profile_archives"

ACTIVE_JOB_STATUSES = {"queued", "running", "needs_login", "manual_verification_required"}
FINAL_JOB_STATUSES = {"success", "failed", "cancelled", "manual_verification_required", "unknown_result"}
SAFE_PUBLISH_RETRY_STEPS = {"open_browser", "open_composer", "filled_composer", "check_session", "queued", "claimed"}

LOCK_TIMEOUT_SECONDS = float(os.environ.get("CHANNEL_STORE_LOCK_TIMEOUT_SECONDS", "10"))
LOCK_POLL_SECONDS = float(os.environ.get("CHANNEL_STORE_LOCK_POLL_SECONDS", "0.1"))
DEFAULT_WORKER_HEARTBEAT_STALE_SECONDS = int(os.environ.get("CHANNEL_WORKER_STALE_SECONDS", "90"))

T = TypeVar("T")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_channel_store_dirs() -> None:
    STUDIO_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    CHANNEL_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)



def generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"



def _locked_list_store(path: Path):
    ensure_channel_store_dirs()
    return locked_json_store(
        path,
        default_factory=list,
        expect_type=list,
        lock_dir=LOCKS_DIR,
        timeout_seconds=LOCK_TIMEOUT_SECONDS,
        poll_seconds=LOCK_POLL_SECONDS,
    )



def _deserialize_records(payload: list[dict[str, Any]], cls: type[T]) -> list[T]:
    records: list[T] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            records.append(cls(**item))
        except TypeError:
            continue
    return records



def _serialize_records(records: list[Any]) -> list[dict[str, Any]]:
    return [asdict(record) for record in records]



def _load_records(path: Path, cls: type[T]) -> list[T]:
    with _locked_list_store(path) as store:
        payload = store.read()
    return _deserialize_records(payload, cls)



def _save_records(path: Path, records: list[Any]) -> None:
    with _locked_list_store(path) as store:
        store.write(_serialize_records(records))



def _mutate_records(path: Path, cls: type[T], mutator: Callable[[list[T]], tuple[bool, Any]]) -> Any:
    with _locked_list_store(path) as store:
        payload = store.read()
        records = _deserialize_records(payload, cls)
        changed, result = mutator(records)
        if changed:
            store.write(_serialize_records(records))
        return result



def _upsert_inplace(records: list[T], incoming: T, *, key: str = "id") -> None:
    incoming_key = getattr(incoming, key)
    for index, record in enumerate(records):
        if getattr(record, key) == incoming_key:
            records[index] = incoming
            return
    records.append(incoming)



def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)



def _lease_expired(lease_value: str, *, now: datetime | None = None) -> bool:
    lease = _parse_iso_datetime(lease_value)
    current = now or datetime.now(timezone.utc)
    return lease is None or lease <= current



def _lease_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(seconds, 1))).astimezone().isoformat(timespec="seconds")



def _job_order_value(*values: str) -> datetime:
    fallback = datetime.now(timezone.utc)
    for value in values:
        parsed = _parse_iso_datetime(value)
        if parsed is not None:
            return parsed
    return fallback



def list_channel_connections() -> list[ChannelConnection]:
    return _load_records(CHANNEL_CONNECTIONS_PATH, ChannelConnection)



def get_channel_connection(channel_id: str) -> ChannelConnection | None:
    for connection in list_channel_connections():
        if connection.channel_id == channel_id:
            return connection
    return None



def save_channel_connection(connection: ChannelConnection) -> ChannelConnection:
    def mutate(records: list[ChannelConnection]):
        _upsert_inplace(records, connection)
        return True, connection

    return _mutate_records(CHANNEL_CONNECTIONS_PATH, ChannelConnection, mutate)



def update_channel_connection(channel_id: str, mutator: Callable[[ChannelConnection | None], ChannelConnection]) -> ChannelConnection:
    def mutate(records: list[ChannelConnection]):
        current = next((record for record in records if record.channel_id == channel_id), None)
        updated = mutator(current)
        _upsert_inplace(records, updated)
        return True, updated

    return _mutate_records(CHANNEL_CONNECTIONS_PATH, ChannelConnection, mutate)



def ensure_channel_connection(
    channel_id: str,
    *,
    mode: str,
    status: str,
    local_profile_path: str = "",
    capabilities_snapshot_json: dict[str, Any] | None = None,
) -> ChannelConnection:
    current_time = now_iso()

    def mutate(existing: ChannelConnection | None) -> ChannelConnection:
        if existing is not None:
            return existing
        return ChannelConnection(
            id=f"connection_{channel_id}",
            channel_id=channel_id,
            mode=mode,
            status=status,
            local_profile_path=local_profile_path,
            capabilities_snapshot_json=capabilities_snapshot_json or {},
            created_at=current_time,
            updated_at=current_time,
        )

    return update_channel_connection(channel_id, mutate)



def begin_channel_connect(
    channel_id: str,
    *,
    mode: str,
    local_profile_path: str = "",
    capabilities_snapshot_json: dict[str, Any] | None = None,
) -> tuple[ChannelConnection, bool]:
    current_time = now_iso()
    new_action_id = generate_id("connect")

    def mutate(records: list[ChannelConnection]):
        current = next((record for record in records if record.channel_id == channel_id), None)
        connection = current or ChannelConnection(
            id=f"connection_{channel_id}",
            channel_id=channel_id,
            mode=mode,
            status="not_configured",
            local_profile_path=local_profile_path,
            capabilities_snapshot_json=capabilities_snapshot_json or {},
            created_at=current_time,
            updated_at=current_time,
        )
        if (
            connection.status == "connecting"
            and connection.active_job_type == "connect"
            and bool(connection.active_job_id)
        ):
            connection.updated_at = current_time
            _upsert_inplace(records, connection)
            return True, (connection, False)
        connection.mode = mode
        connection.status = "connecting"
        connection.last_checked_at = current_time
        connection.updated_at = current_time
        connection.last_error = ""
        if local_profile_path:
            connection.local_profile_path = local_profile_path
        if capabilities_snapshot_json is not None:
            connection.capabilities_snapshot_json = capabilities_snapshot_json
        connection.active_job_id = new_action_id
        connection.active_job_type = "connect"
        connection.active_worker_id = ""
        connection.active_claimed_at = ""
        connection.last_connect_diagnostics_json = {}
        _upsert_inplace(records, connection)
        return True, (connection, True)

    return _mutate_records(CHANNEL_CONNECTIONS_PATH, ChannelConnection, mutate)



def claim_channel_connect(channel_id: str, *, action_id: str, worker_id: str) -> ChannelConnection | None:
    current_time = now_iso()

    def mutate(records: list[ChannelConnection]):
        connection = next((record for record in records if record.channel_id == channel_id), None)
        if connection is None:
            return False, None
        if connection.status != "connecting":
            return False, None
        if connection.active_job_type != "connect" or connection.active_job_id != action_id:
            return False, None
        if connection.active_worker_id and connection.active_worker_id != worker_id:
            return False, None
        connection.active_worker_id = worker_id
        connection.active_claimed_at = current_time
        connection.updated_at = current_time
        _upsert_inplace(records, connection)
        return True, connection

    return _mutate_records(CHANNEL_CONNECTIONS_PATH, ChannelConnection, mutate)



def list_derivatives(source_document_id: str | None = None, channel_id: str | None = None) -> list[ContentDerivative]:
    records = _load_records(CONTENT_DERIVATIVES_PATH, ContentDerivative)
    if source_document_id:
        records = [record for record in records if record.source_document_id == source_document_id]
    if channel_id:
        records = [record for record in records if record.channel_id == channel_id]
    return sorted(records, key=lambda item: item.updated_at or item.created_at, reverse=True)



def get_derivative(derivative_id: str) -> ContentDerivative | None:
    for record in _load_records(CONTENT_DERIVATIVES_PATH, ContentDerivative):
        if record.id == derivative_id:
            return record
    return None



def save_derivative(derivative: ContentDerivative) -> ContentDerivative:
    def mutate(records: list[ContentDerivative]):
        _upsert_inplace(records, derivative)
        return True, derivative

    return _mutate_records(CONTENT_DERIVATIVES_PATH, ContentDerivative, mutate)



def list_approvals(derivative_id: str | None = None) -> list[ApprovalRecord]:
    records = _load_records(APPROVALS_PATH, ApprovalRecord)
    if derivative_id:
        records = [record for record in records if record.derivative_id == derivative_id]
    return sorted(records, key=lambda item: item.created_at, reverse=True)



def get_active_approval(derivative_id: str) -> ApprovalRecord | None:
    for record in list_approvals(derivative_id):
        if record.status == "approved" and not record.revoked_at:
            return record
    return None



def save_approval(record: ApprovalRecord) -> ApprovalRecord:
    def mutate(records: list[ApprovalRecord]):
        _upsert_inplace(records, record)
        return True, record

    return _mutate_records(APPROVALS_PATH, ApprovalRecord, mutate)



def list_publish_jobs(channel_id: str | None = None, derivative_id: str | None = None) -> list[PublishJob]:
    records = _load_records(PUBLISH_JOBS_PATH, PublishJob)
    if channel_id:
        records = [record for record in records if record.channel_id == channel_id]
    if derivative_id:
        records = [record for record in records if record.derivative_id == derivative_id]
    return sorted(records, key=lambda item: item.created_at or item.requested_at, reverse=True)



def get_publish_job(job_id: str) -> PublishJob | None:
    for record in _load_records(PUBLISH_JOBS_PATH, PublishJob):
        if record.id == job_id:
            return record
    return None



def save_publish_job(job: PublishJob) -> PublishJob:
    def mutate(records: list[PublishJob]):
        _upsert_inplace(records, job)
        return True, job

    return _mutate_records(PUBLISH_JOBS_PATH, PublishJob, mutate)



def update_publish_job(job_id: str, mutator: Callable[[PublishJob], PublishJob]) -> PublishJob:
    def mutate(records: list[PublishJob]):
        for index, record in enumerate(records):
            if record.id == job_id:
                updated = mutator(record)
                records[index] = updated
                return True, updated
        raise KeyError(job_id)

    return _mutate_records(PUBLISH_JOBS_PATH, PublishJob, mutate)



def find_active_publish_job(channel_id: str) -> PublishJob | None:
    for job in list_publish_jobs(channel_id=channel_id):
        if job.status in ACTIVE_JOB_STATUSES:
            return job
    return None



def _recover_publish_job(job: PublishJob, *, now: datetime) -> PublishJob:
    timestamp = now.astimezone().isoformat(timespec="seconds")
    if job.run_mode == "live" and (job.submitted_at or job.unknown_result or job.manual_verification_required):
        job.status = "manual_verification_required"
        job.finished_at = timestamp
        job.updated_at = timestamp
        job.error_code = job.error_code or "manual_verification_required"
        job.error_message = job.error_message or "A previous live publish may already have been submitted. Verify the result manually before retrying."
        job.unknown_result = True
        job.manual_verification_required = True
    elif job.attempt_count >= job.max_attempts:
        job.status = "failed"
        job.finished_at = timestamp
        job.updated_at = timestamp
        job.error_code = job.error_code or "lease_expired"
        job.error_message = job.error_message or "Worker lease expired and retry limit was reached."
    else:
        job.status = "queued"
        job.updated_at = timestamp
        job.last_step = "requeued_after_stale_lease"
        job.error_code = "stale_recovered"
        job.error_message = "Worker lease expired before publish completion. The job was re-queued safely."
        job.started_at = ""
    job.claimed_by = ""
    job.claimed_at = ""
    job.lease_expires_at = ""
    job.heartbeat_at = ""
    return job



def claim_next_publish_job(channel_id: str | None, *, worker_id: str, lease_seconds: int) -> PublishJob | None:
    def mutate(records: list[PublishJob]):
        now = datetime.now(timezone.utc)
        changed = False
        for index, job in enumerate(records):
            if channel_id and job.channel_id != channel_id:
                continue
            if job.status == "running" and _lease_expired(job.lease_expires_at, now=now):
                records[index] = _recover_publish_job(job, now=now)
                changed = True

        running_by_channel: dict[str, bool] = {}
        for job in records:
            if job.status == "running" and not _lease_expired(job.lease_expires_at, now=now):
                running_by_channel[job.channel_id] = True

        candidates = [
            job
            for job in records
            if job.status == "queued" and (not channel_id or job.channel_id == channel_id)
        ]
        candidates.sort(key=lambda item: _job_order_value(item.requested_at, item.created_at))

        for candidate in candidates:
            if running_by_channel.get(candidate.channel_id):
                continue
            candidate.status = "running"
            candidate.started_at = now.astimezone().isoformat(timespec="seconds")
            candidate.updated_at = candidate.started_at
            candidate.attempt_count += 1
            candidate.last_step = candidate.last_step or "claimed"
            candidate.claimed_by = worker_id
            candidate.claimed_at = candidate.started_at
            candidate.heartbeat_at = candidate.started_at
            candidate.lease_expires_at = (now + timedelta(seconds=max(lease_seconds, 1))).astimezone().isoformat(timespec="seconds")
            candidate.error_code = ""
            candidate.error_message = ""
            running_by_channel[candidate.channel_id] = True
            changed = True
            return changed, candidate
        return changed, None

    return _mutate_records(PUBLISH_JOBS_PATH, PublishJob, mutate)



def heartbeat_publish_job(job_id: str, *, worker_id: str, lease_seconds: int) -> PublishJob | None:
    def mutate(records: list[PublishJob]):
        for index, record in enumerate(records):
            if record.id != job_id:
                continue
            if record.claimed_by and record.claimed_by != worker_id:
                return False, None
            if record.status != "running":
                return False, record
            timestamp = now_iso()
            record.heartbeat_at = timestamp
            record.lease_expires_at = _lease_iso(lease_seconds)
            records[index] = record
            return True, record
        return False, None

    return _mutate_records(PUBLISH_JOBS_PATH, PublishJob, mutate)



def list_published_posts(channel_id: str | None = None, derivative_id: str | None = None, source_document_id: str | None = None) -> list[PublishedPost]:
    records = _load_records(PUBLISHED_POSTS_PATH, PublishedPost)
    if channel_id:
        records = [record for record in records if record.channel_id == channel_id]
    if derivative_id:
        records = [record for record in records if record.derivative_id == derivative_id]
    if source_document_id:
        records = [record for record in records if record.source_document_id == source_document_id]
    return sorted(records, key=lambda item: item.published_at or item.created_at, reverse=True)



def get_published_post(post_id: str) -> PublishedPost | None:
    for record in _load_records(PUBLISHED_POSTS_PATH, PublishedPost):
        if record.id == post_id:
            return record
    return None



def save_published_post(post: PublishedPost) -> PublishedPost:
    def mutate(records: list[PublishedPost]):
        _upsert_inplace(records, post)
        return True, post

    return _mutate_records(PUBLISHED_POSTS_PATH, PublishedPost, mutate)



def find_published_post_for_derivative(derivative_id: str) -> PublishedPost | None:
    for record in list_published_posts(derivative_id=derivative_id):
        return record
    return None



def list_metric_jobs(channel_id: str | None = None, published_post_id: str | None = None) -> list[MetricJob]:
    records = _load_records(METRIC_JOBS_PATH, MetricJob)
    if channel_id:
        records = [record for record in records if record.channel_id == channel_id]
    if published_post_id:
        records = [record for record in records if record.published_post_id == published_post_id]
    return sorted(records, key=lambda item: item.scheduled_for or item.requested_at, reverse=True)



def get_metric_job(job_id: str) -> MetricJob | None:
    for record in _load_records(METRIC_JOBS_PATH, MetricJob):
        if record.id == job_id:
            return record
    return None



def save_metric_job(job: MetricJob) -> MetricJob:
    def mutate(records: list[MetricJob]):
        _upsert_inplace(records, job)
        return True, job

    return _mutate_records(METRIC_JOBS_PATH, MetricJob, mutate)



def update_metric_job(job_id: str, mutator: Callable[[MetricJob], MetricJob]) -> MetricJob:
    def mutate(records: list[MetricJob]):
        for index, record in enumerate(records):
            if record.id == job_id:
                updated = mutator(record)
                records[index] = updated
                return True, updated
        raise KeyError(job_id)

    return _mutate_records(METRIC_JOBS_PATH, MetricJob, mutate)



def _recover_metric_job(job: MetricJob, *, now: datetime) -> MetricJob:
    timestamp = now.astimezone().isoformat(timespec="seconds")
    if job.attempt_count >= job.max_attempts:
        job.status = "failed"
        job.finished_at = timestamp
        job.updated_at = timestamp
        job.error_code = job.error_code or "lease_expired"
        job.error_message = job.error_message or "Worker lease expired and retry limit was reached."
    else:
        job.status = "queued"
        job.updated_at = timestamp
        job.error_code = "stale_recovered"
        job.error_message = "Worker lease expired before metrics collection completed. The job was re-queued safely."
        job.started_at = ""
    job.claimed_by = ""
    job.claimed_at = ""
    job.lease_expires_at = ""
    job.heartbeat_at = ""
    return job



def claim_next_metric_job(channel_id: str | None, *, worker_id: str, lease_seconds: int) -> MetricJob | None:
    def mutate(records: list[MetricJob]):
        now = datetime.now(timezone.utc)
        changed = False
        for index, job in enumerate(records):
            if channel_id and job.channel_id != channel_id:
                continue
            if job.status == "running" and _lease_expired(job.lease_expires_at, now=now):
                records[index] = _recover_metric_job(job, now=now)
                changed = True

        candidates = [
            job
            for job in records
            if job.status == "queued" and (not channel_id or job.channel_id == channel_id)
        ]
        candidates.sort(key=lambda item: _job_order_value(item.scheduled_for, item.requested_at, item.created_at))
        for candidate in candidates:
            scheduled_for = _parse_iso_datetime(candidate.scheduled_for or candidate.requested_at)
            if scheduled_for and scheduled_for > now:
                continue
            candidate.status = "running"
            candidate.started_at = now.astimezone().isoformat(timespec="seconds")
            candidate.updated_at = candidate.started_at
            candidate.attempt_count += 1
            candidate.claimed_by = worker_id
            candidate.claimed_at = candidate.started_at
            candidate.heartbeat_at = candidate.started_at
            candidate.lease_expires_at = (now + timedelta(seconds=max(lease_seconds, 1))).astimezone().isoformat(timespec="seconds")
            candidate.error_code = ""
            candidate.error_message = ""
            changed = True
            return changed, candidate
        return changed, None

    return _mutate_records(METRIC_JOBS_PATH, MetricJob, mutate)



def heartbeat_metric_job(job_id: str, *, worker_id: str, lease_seconds: int) -> MetricJob | None:
    def mutate(records: list[MetricJob]):
        for index, record in enumerate(records):
            if record.id != job_id:
                continue
            if record.claimed_by and record.claimed_by != worker_id:
                return False, None
            if record.status != "running":
                return False, record
            timestamp = now_iso()
            record.heartbeat_at = timestamp
            record.lease_expires_at = _lease_iso(lease_seconds)
            records[index] = record
            return True, record
        return False, None

    return _mutate_records(METRIC_JOBS_PATH, MetricJob, mutate)



def metric_job_exists(published_post_id: str, scheduled_for: str, *, include_finished: bool = True) -> bool:
    for job in list_metric_jobs(published_post_id=published_post_id):
        if job.scheduled_for != scheduled_for:
            continue
        if include_finished or job.status not in {"failed", "cancelled"}:
            return True
    return False



def list_metric_snapshots(published_post_id: str | None = None) -> list[PostMetricSnapshot]:
    records = _load_records(POST_METRIC_SNAPSHOTS_PATH, PostMetricSnapshot)
    if published_post_id:
        records = [record for record in records if record.published_post_id == published_post_id]
    return sorted(records, key=lambda item: item.captured_at, reverse=True)



def save_metric_snapshot(snapshot: PostMetricSnapshot) -> PostMetricSnapshot:
    def mutate(records: list[PostMetricSnapshot]):
        _upsert_inplace(records, snapshot)
        return True, snapshot

    return _mutate_records(POST_METRIC_SNAPSHOTS_PATH, PostMetricSnapshot, mutate)



def latest_metric_snapshot_for_post(published_post_id: str) -> PostMetricSnapshot | None:
    snapshots = list_metric_snapshots(published_post_id)
    return snapshots[0] if snapshots else None



def latest_metric_snapshot_for_derivative(derivative_id: str) -> PostMetricSnapshot | None:
    post = find_published_post_for_derivative(derivative_id)
    if not post:
        return None
    return latest_metric_snapshot_for_post(post.id)



def list_worker_heartbeats(channel_id: str | None = None) -> list[WorkerHeartbeat]:
    records = _load_records(WORKER_HEARTBEATS_PATH, WorkerHeartbeat)
    if channel_id:
        records = [record for record in records if record.channel_id == channel_id]
    return sorted(records, key=lambda item: item.last_seen_at, reverse=True)



def save_worker_heartbeat(heartbeat: WorkerHeartbeat) -> WorkerHeartbeat:
    def mutate(records: list[WorkerHeartbeat]):
        _upsert_inplace(records, heartbeat, key="worker_id")
        return True, heartbeat

    return _mutate_records(WORKER_HEARTBEATS_PATH, WorkerHeartbeat, mutate)



def latest_worker_heartbeat(channel_id: str) -> WorkerHeartbeat | None:
    records = list_worker_heartbeats(channel_id)
    return records[0] if records else None



def worker_status_from_heartbeat(channel_id: str, *, timeout_seconds: int | None = None) -> tuple[str, WorkerHeartbeat | None]:
    heartbeat = latest_worker_heartbeat(channel_id)
    if not heartbeat:
        return "offline", None
    seen_at = _parse_iso_datetime(heartbeat.last_seen_at)
    if seen_at is None:
        return "offline", heartbeat
    freshness = timeout_seconds if timeout_seconds is not None else DEFAULT_WORKER_HEARTBEAT_STALE_SECONDS
    age_seconds = (datetime.now(timezone.utc) - seen_at).total_seconds()
    if heartbeat.status == "offline" or age_seconds > freshness:
        return "offline", heartbeat
    return heartbeat.status, heartbeat



def list_channel_job_logs(channel_id: str | None = None, job_type: str | None = None, job_id: str | None = None, limit: int = 100) -> list[ChannelJobLog]:
    records = _load_records(CHANNEL_JOB_LOGS_PATH, ChannelJobLog)
    if channel_id:
        records = [record for record in records if record.channel_id == channel_id]
    if job_type:
        records = [record for record in records if record.job_type == job_type]
    if job_id:
        records = [record for record in records if record.job_id == job_id]
    return sorted(records, key=lambda item: item.created_at, reverse=True)[:limit]



def append_channel_job_log(log_record: ChannelJobLog) -> ChannelJobLog:
    def mutate(records: list[ChannelJobLog]):
        records.append(log_record)
        records[:] = sorted(records, key=lambda item: item.created_at)[-250:]
        return True, log_record

    return _mutate_records(CHANNEL_JOB_LOGS_PATH, ChannelJobLog, mutate)
