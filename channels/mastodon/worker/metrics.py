from __future__ import annotations

from typing import Any

from channel_models import MetricJob, PostMetricSnapshot
from channel_store import get_metric_job, get_published_post, now_iso, save_metric_job, save_metric_snapshot
from src.core.analytics import ChannelMetricObservationInput

from ..client import MastodonApiClient
from ..errors import MastodonMetricsError, MastodonRemoteStatusNotFoundError
from ..metric_definitions import MASTODON_METRICS_SOURCE_VERSION
from ..storage import MastodonAccountRepository, MastodonSecretStore, append_audit, append_event


def run_metric_job_with_runtime(
    config: Any, app_runtime, job_id: str, *, worker_id: str = "", started_at: str = ""
) -> MetricJob:
    job = get_metric_job(job_id)
    if job is None:
        raise RuntimeError(f"Metric job {job_id} not found.")
    post = get_published_post(job.published_post_id)
    if post is None:
        raise MastodonMetricsError("mastodon.metrics.publication_missing", "Published Mastodon status was not found.")
    account = MastodonAccountRepository().get(post.channel_id)
    if account is None or account.connection_status != "connected":
        raise MastodonMetricsError("authentication_required", "Mastodon account is not connected.")
    local_status_id = str((post.raw_result_json or {}).get("local_status_id") or "")
    if not local_status_id:
        raise MastodonMetricsError("mastodon.metrics.local_status_missing", "Mastodon local status ID is missing.")
    client = MastodonApiClient(
        origin=account.instance_origin,
        transport=app_runtime.get_plugin_service("channel.mastodon", "channel_runtime").transport,
        access_token=MastodonSecretStore().get(account.token_secret_ref),
    )
    status = client.get_status(local_status_id)
    if str(status.get("uri") or "") != post.external_id:
        raise MastodonRemoteStatusNotFoundError(
            "mastodon.metrics.status_identity_mismatch", "Mastodon status identity mismatched."
        )
    observed_at = now_iso()
    raw = {
        "favourites": _int(status.get("favourites_count")),
        "replies": _int(status.get("replies_count")),
        "reblogs": _int(status.get("reblogs_count")),
    }
    if "quotes_count" in status:
        raw["quotes"] = _int(status.get("quotes_count"))
    snapshot = PostMetricSnapshot(
        id=f"metric_snapshot_{job.id}",
        published_post_id=post.id,
        channel_id=post.channel_id,
        captured_at=observed_at,
        raw_metrics_json={"mastodon": raw, "unavailable_by_channel": ["impressions", "reach", "views", "clicks"]},
        created_at=observed_at,
    )
    save_metric_snapshot(snapshot)
    inputs = [
        ChannelMetricObservationInput(
            remote_publication_id=post.external_id,
            publication_id=post.id,
            metric_key=key,
            value=value,
            observed_at=observed_at,
            window_start=post.published_at,
            window_end=observed_at,
            source_version=MASTODON_METRICS_SOURCE_VERSION,
            source_evidence_reference=snapshot.id,
            metadata={"measurement_window": "lifetime_to_date"},
        )
        for key, value in raw.items()
        if value is not None
    ]
    result = app_runtime.analytics_ingestion_service(config).ingest_observations(
        workspace_id=account.workspace_id,
        channel_plugin_id="channel.mastodon",
        channel_account_id=account.channel_account_id,
        inputs=inputs,
        source_type="mastodon_status_resource",
        source_run_id=f"analytics_run_{job.id}",
    )
    job.status = "done" if not result.get("failures") else "failed"
    job.finished_at = observed_at
    job.updated_at = observed_at
    job.claimed_by = job.claimed_at = job.lease_expires_at = job.heartbeat_at = ""
    save_metric_job(job)
    append_event(
        "channel.mastodon.metrics.collected",
        workspace_id=account.workspace_id,
        account_id=account.channel_account_id,
        metadata={"publication_id": post.id, "observations": len(inputs)},
    )
    append_audit(
        "metrics.collect", workspace_id=account.workspace_id, account_id=account.channel_account_id, result=job.status
    )
    return job


def _int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
