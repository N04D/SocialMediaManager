from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from typing import Any

from channel_models import (
    ApprovalRecord,
    ChannelJobLog,
    ContentDerivative,
    MetricJob,
    PostMetricSnapshot,
    PublishJob,
    PublishedPost,
)
from channel_registry import ChannelRegistryEntry, get_channel_registry_entry
from channel_store import (
    ACTIVE_JOB_STATUSES,
    append_channel_job_log,
    find_active_publish_job,
    find_published_post_for_derivative,
    generate_id,
    get_active_approval,
    get_channel_connection,
    get_derivative,
    get_published_post,
    latest_metric_snapshot_for_post,
    list_derivatives,
    list_metric_jobs,
    list_published_posts,
    now_iso,
    save_approval,
    save_derivative,
    save_metric_job,
    save_publish_job,
    save_published_post,
)
from pipeline import AppConfig
from studio_models import ContentItem
from channels.linkedin.worker.urls import LinkedInUrlError, extract_linkedin_external_id, normalize_linkedin_post_url


class ChannelActionError(ValueError):
    """Raised when a channel workflow request cannot be fulfilled safely."""



def _load_plugin_module(channel_id: str, suffix: str):
    return importlib.import_module(f"channels.{channel_id}.{suffix}")



def _plugin_actions(channel_id: str):
    return _load_plugin_module(channel_id, "server.actions")



def _registry_entry_or_error(channel_id: str) -> ChannelRegistryEntry:
    entry = get_channel_registry_entry(channel_id)
    if entry is None:
        raise ChannelActionError(f"Unknown channel plugin: {channel_id}")
    if entry.health == "invalid_manifest":
        raise ChannelActionError(f"Channel plugin {channel_id} is invalid: {'; '.join(entry.errors)}")
    return entry



def generate_derivative_for_document(
    *,
    config: AppConfig,
    source_item: ContentItem,
    channel_id: str,
    output_type: str,
) -> ContentDerivative:
    entry = _registry_entry_or_error(channel_id)
    capabilities = entry.manifest.get("capabilities", {})
    if not capabilities.get("canGenerate"):
        raise ChannelActionError(f"Channel {channel_id} does not support derivative generation.")
    if output_type not in entry.manifest.get("outputTypes", []):
        raise ChannelActionError(f"Channel {channel_id} does not support output type {output_type}.")
    if not source_item.id:
        raise ChannelActionError("Save the canonical document before generating a derivative.")

    plugin_actions = _plugin_actions(channel_id)
    generated = plugin_actions.generate_derivative(
        source_item=source_item,
        config=config,
        output_type=output_type,
    )
    current_time = now_iso()
    derivative = ContentDerivative(
        id=generate_id("derivative"),
        source_document_id=source_item.id,
        channel_id=channel_id,
        output_type=output_type,
        title=str(generated.get("title") or source_item.title or "Derivative draft"),
        body=str(generated.get("body") or "").strip(),
        status="draft",
        generation_metadata_json=dict(generated.get("metadata") or {}) | {"validation": generated.get("validation") or {}},
        created_at=current_time,
        updated_at=current_time,
    )
    save_derivative(derivative)
    append_channel_job_log(
        ChannelJobLog(
            id=generate_id("log"),
            channel_id=channel_id,
            job_type="generate",
            job_id=derivative.id,
            status="success",
            last_step="generated_derivative",
            created_at=current_time,
        )
    )
    return derivative



def validate_derivative_for_channel(derivative: ContentDerivative) -> dict[str, Any]:
    plugin_actions = _plugin_actions(derivative.channel_id)
    return plugin_actions.validate_derivative(
        title=derivative.title,
        body=derivative.body,
        output_type=derivative.output_type,
    )



def save_derivative_edit(derivative_id: str, *, title: str, body: str) -> ContentDerivative:
    derivative = get_derivative(derivative_id)
    if derivative is None:
        raise ChannelActionError("Derivative not found.")
    derivative.title = title.strip() or derivative.title
    derivative.body = body.strip()
    derivative.status = "draft"
    derivative.updated_at = now_iso()
    validation = validate_derivative_for_channel(derivative)
    derivative.generation_metadata_json = dict(derivative.generation_metadata_json or {})
    derivative.generation_metadata_json["validation"] = validation
    save_derivative(derivative)
    return derivative



def send_derivative_for_review(derivative_id: str) -> ContentDerivative:
    derivative = get_derivative(derivative_id)
    if derivative is None:
        raise ChannelActionError("Derivative not found.")
    derivative.status = "pending_review"
    derivative.updated_at = now_iso()
    validation = validate_derivative_for_channel(derivative)
    derivative.generation_metadata_json = dict(derivative.generation_metadata_json or {})
    derivative.generation_metadata_json["validation"] = validation
    save_derivative(derivative)
    return derivative



def approve_derivative(derivative_id: str, *, approved_by: str) -> tuple[ContentDerivative, ApprovalRecord]:
    derivative = get_derivative(derivative_id)
    if derivative is None:
        raise ChannelActionError("Derivative not found.")
    current_time = now_iso()
    active_approval = get_active_approval(derivative_id)
    if active_approval is not None:
        active_approval.revoked_at = current_time
        active_approval.status = "revoked"
        save_approval(active_approval)
    approval = ApprovalRecord(
        id=generate_id("approval"),
        derivative_id=derivative.id,
        approved_by=approved_by,
        approved_at=current_time,
        status="approved",
        created_at=current_time,
    )
    derivative.status = "approved"
    derivative.updated_at = current_time
    save_approval(approval)
    save_derivative(derivative)
    return derivative, approval



def reject_derivative(derivative_id: str, *, approved_by: str) -> tuple[ContentDerivative, ApprovalRecord]:
    derivative = get_derivative(derivative_id)
    if derivative is None:
        raise ChannelActionError("Derivative not found.")
    current_time = now_iso()
    active_approval = get_active_approval(derivative_id)
    if active_approval is not None:
        active_approval.revoked_at = current_time
        active_approval.status = "revoked"
        save_approval(active_approval)
    rejection = ApprovalRecord(
        id=generate_id("approval"),
        derivative_id=derivative.id,
        approved_by=approved_by,
        approved_at=current_time,
        status="rejected",
        created_at=current_time,
    )
    derivative.status = "rejected"
    derivative.updated_at = current_time
    save_approval(rejection)
    save_derivative(derivative)
    return derivative, rejection



def return_derivative_to_draft(derivative_id: str) -> ContentDerivative:
    derivative = get_derivative(derivative_id)
    if derivative is None:
        raise ChannelActionError("Derivative not found.")
    active_approval = get_active_approval(derivative_id)
    if active_approval is not None:
        active_approval.revoked_at = now_iso()
        active_approval.status = "revoked"
        save_approval(active_approval)
    derivative.status = "draft"
    derivative.updated_at = now_iso()
    save_derivative(derivative)
    return derivative



def _publish_guard_errors(derivative: ContentDerivative, *, channel_id: str) -> list[str]:
    entry = _registry_entry_or_error(channel_id)
    errors: list[str] = []
    if derivative.channel_id != channel_id:
        errors.append("Derivative does not belong to the requested channel.")
    if derivative.status != "approved":
        errors.append("Only approved derivatives can be published.")
    if get_active_approval(derivative.id) is None:
        errors.append("Approval record is missing or revoked.")
    if not entry.manifest.get("capabilities", {}).get("canPublish"):
        errors.append(f"Channel {channel_id} does not support publishing.")
    connection = get_channel_connection(channel_id)
    if connection is None or connection.status != "connected":
        errors.append(f"Channel {channel_id} is not connected.")
    if find_active_publish_job(channel_id) is not None:
        errors.append(f"Channel {channel_id} already has an active publish job.")
    if entry.manifest.get("capabilities", {}).get("canGenerate"):
        validation = validate_derivative_for_channel(derivative)
        if validation.get("errors"):
            errors.extend(str(item) for item in validation["errors"])
    published_post = find_published_post_for_derivative(derivative.id)
    if published_post is not None and published_post.status in {"confirmed", "manual_confirmed"}:
        errors.append("A published post already exists for this derivative.")
    return errors



def create_publish_job_from_derivative(
    derivative_id: str,
    *,
    channel_id: str,
    run_mode: str,
) -> tuple[PublishJob, list[str]]:
    derivative = get_derivative(derivative_id)
    if derivative is None:
        raise ChannelActionError("Derivative not found.")
    if run_mode not in {"dry_run", "live"}:
        raise ChannelActionError("Unsupported publish mode.")
    errors = _publish_guard_errors(derivative, channel_id=channel_id)
    if errors:
        raise ChannelActionError("; ".join(errors))

    entry = _registry_entry_or_error(channel_id)
    warnings: list[str] = []
    if entry.worker_status == "offline":
        warnings.append(f"The {channel_id} worker is currently offline. The job has been queued anyway.")

    current_time = now_iso()
    job = PublishJob(
        id=generate_id("publish"),
        derivative_id=derivative.id,
        channel_id=channel_id,
        status="queued",
        requested_at=current_time,
        last_step="queued",
        created_at=current_time,
        updated_at=current_time,
        run_mode=run_mode,
        max_attempts=2,
    )
    save_publish_job(job)
    append_channel_job_log(
        ChannelJobLog(
            id=generate_id("log"),
            channel_id=channel_id,
            job_type="publish",
            job_id=job.id,
            status=job.status,
            last_step=job.last_step,
            created_at=current_time,
        )
    )
    return job, warnings



def queue_metric_job(*, published_post_id: str, channel_id: str, scheduled_for: str | None = None) -> MetricJob:
    current_time = now_iso()
    schedule_time = scheduled_for or current_time
    for existing in list_metric_jobs(published_post_id=published_post_id):
        if existing.scheduled_for != schedule_time:
            continue
        if existing.status in ACTIVE_JOB_STATUSES or existing.status == "success":
            return existing
    job = MetricJob(
        id=generate_id("metric"),
        published_post_id=published_post_id,
        channel_id=channel_id,
        status="queued",
        scheduled_for=schedule_time,
        requested_at=current_time,
        created_at=current_time,
        updated_at=current_time,
        max_attempts=2,
    )
    save_metric_job(job)
    append_channel_job_log(
        ChannelJobLog(
            id=generate_id("log"),
            channel_id=channel_id,
            job_type="metrics",
            job_id=job.id,
            status=job.status,
            last_step="queued",
            created_at=current_time,
        )
    )
    return job



def schedule_metric_refresh_windows(post: PublishedPost, manifest: dict[str, Any]) -> list[MetricJob]:
    refresh_windows = manifest.get("metrics", {}).get("defaultRefreshWindows", [])
    created_jobs = [queue_metric_job(published_post_id=post.id, channel_id=post.channel_id, scheduled_for=now_iso())]
    for window in refresh_windows:
        if window == "1h":
            delta = timedelta(hours=1)
        elif window == "6h":
            delta = timedelta(hours=6)
        elif window == "24h":
            delta = timedelta(hours=24)
        elif window == "7d":
            delta = timedelta(days=7)
        else:
            continue
        scheduled_for = (replace_datetime(post.published_at) + delta).isoformat(timespec="seconds")
        created_jobs.append(
            queue_metric_job(
                published_post_id=post.id,
                channel_id=post.channel_id,
                scheduled_for=scheduled_for,
            )
        )
    return created_jobs



def replace_datetime(value: str):
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc).astimezone()
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc).astimezone()
    return parsed.astimezone()



def record_confirmed_publish(
    *,
    job: PublishJob,
    derivative: ContentDerivative,
    external_url: str,
    external_id: str,
    status: str,
    raw_result: dict[str, Any] | None = None,
) -> PublishedPost:
    current_time = now_iso()
    normalized_url = normalize_linkedin_post_url(external_url) if external_url else ""
    resolved_external_id = external_id or (extract_linkedin_external_id(normalized_url) if normalized_url else "")
    existing = find_published_post_for_derivative(derivative.id)
    published_post = existing or PublishedPost(
        id=generate_id("published"),
        derivative_id=derivative.id,
        source_document_id=derivative.source_document_id,
        channel_id=derivative.channel_id,
        external_id=resolved_external_id,
        external_url=normalized_url,
        published_at=current_time,
        publish_job_id=job.id,
        status=status,
        raw_result_json=raw_result or {},
        created_at=current_time,
        updated_at=current_time,
    )
    published_post.external_id = resolved_external_id
    published_post.external_url = normalized_url
    published_post.published_at = current_time
    published_post.publish_job_id = job.id
    published_post.status = status
    published_post.raw_result_json = raw_result or {}
    published_post.updated_at = current_time
    save_published_post(published_post)

    derivative.status = "published"
    derivative.updated_at = current_time
    save_derivative(derivative)

    manifest = _registry_entry_or_error(derivative.channel_id).manifest
    if normalized_url:
        schedule_metric_refresh_windows(published_post, manifest)
    return published_post



def manual_attach_published_url(derivative_id: str, *, channel_id: str, external_url: str) -> PublishedPost:
    derivative = get_derivative(derivative_id)
    if derivative is None:
        raise ChannelActionError("Derivative not found.")
    try:
        normalized_url = normalize_linkedin_post_url(external_url)
    except LinkedInUrlError as exc:
        raise ChannelActionError(str(exc)) from exc

    placeholder_job = PublishJob(
        id=generate_id("publish"),
        derivative_id=derivative.id,
        channel_id=channel_id,
        status="success",
        requested_at=now_iso(),
        finished_at=now_iso(),
        created_at=now_iso(),
        updated_at=now_iso(),
        run_mode="manual_attach",
        result_url=normalized_url,
        last_step="manual_attach",
        result_external_id=extract_linkedin_external_id(normalized_url),
    )
    save_publish_job(placeholder_job)
    post = record_confirmed_publish(
        job=placeholder_job,
        derivative=derivative,
        external_url=normalized_url,
        external_id=placeholder_job.result_external_id,
        status="manual_confirmed",
        raw_result={"source": "manual_attach"},
    )
    queue_metric_job(published_post_id=post.id, channel_id=channel_id, scheduled_for=now_iso())
    return post



def queue_manual_metric_refresh(post_id: str) -> MetricJob:
    post = get_post_or_error(post_id)
    if not post.external_url:
        raise ChannelActionError("Attach a published post URL before refreshing metrics.")
    for existing in list_metric_jobs(published_post_id=post.id):
        if existing.status in {"queued", "running", "needs_login"}:
            return existing
    return queue_metric_job(published_post_id=post.id, channel_id=post.channel_id, scheduled_for=now_iso())



def get_post_or_error(post_id: str) -> PublishedPost:
    post = get_published_post(post_id)
    if post is None:
        raise ChannelActionError("Published post not found.")
    return post



def engagement_rate(snapshot: PostMetricSnapshot | None) -> tuple[float | None, str]:
    if snapshot is None:
        return None, ""
    numerator = sum(value or 0 for value in [snapshot.reactions, snapshot.comments, snapshot.reposts])
    if snapshot.impressions is not None:
        denominator = snapshot.impressions
        label = "impressions"
    elif snapshot.views is not None:
        denominator = snapshot.views
        label = "views"
    else:
        return None, ""
    if denominator <= 0:
        return None, label
    return numerator / denominator, label



def _sum_nullable(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)



def document_performance(source_document_id: str, *, channel_id: str = "linkedin") -> dict[str, Any]:
    derivatives = [item for item in list_derivatives(source_document_id=source_document_id, channel_id=channel_id)]
    published_posts = list_published_posts(channel_id=channel_id, source_document_id=source_document_id)
    latest_snapshots = [
        snapshot
        for post in published_posts
        for snapshot in [latest_metric_snapshot_for_post(post.id)]
        if snapshot is not None
    ]

    totals = {
        "derivative_count": len(derivatives),
        "published_count": len(published_posts),
        "impressions": _sum_nullable([snapshot.impressions for snapshot in latest_snapshots]),
        "views": _sum_nullable([snapshot.views for snapshot in latest_snapshots]),
        "reactions": _sum_nullable([snapshot.reactions for snapshot in latest_snapshots]),
        "comments": _sum_nullable([snapshot.comments for snapshot in latest_snapshots]),
        "reposts": _sum_nullable([snapshot.reposts for snapshot in latest_snapshots]),
        "latest_snapshot_at": latest_snapshots[0].captured_at if latest_snapshots else "",
    }
    if totals["impressions"] is not None:
        denominator = totals["impressions"]
        denominator_label = "impressions"
    else:
        denominator = totals["views"]
        denominator_label = "views" if totals["views"] is not None else ""
    if denominator is not None and denominator > 0:
        numerator = sum(value or 0 for value in [totals["reactions"], totals["comments"], totals["reposts"]])
        totals["engagement_rate"] = numerator / denominator
        totals["engagement_rate_denominator"] = denominator_label
    else:
        totals["engagement_rate"] = None
        totals["engagement_rate_denominator"] = denominator_label if denominator is not None else ""
    return totals
