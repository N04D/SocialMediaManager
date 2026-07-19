from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from channel_models import ChannelConnection, ChannelJobLog, MetricJob, PostMetricSnapshot
from channel_store import (
    append_channel_job_log,
    generate_id,
    get_metric_job,
    get_published_post,
    latest_metric_snapshot_for_post,
    now_iso,
    save_metric_job,
    save_metric_snapshot,
    update_channel_connection,
)
from pipeline import AppConfig
from plugin_runtime import get_plugin_runtime
from src.core.browser import BrowserProfileBusyError, BrowserProviderError

from .browser import capture_worker_screenshot
from .runtime import save_channel_worker_heartbeat, worker_id_for_channel
from .session import is_linkedin_logged_in
from .urls import LinkedInUrlError, normalize_linkedin_post_url

_METRIC_PATTERNS = {
    "impressions": [r"([0-9][0-9.,]*\s*[KMB]?)\s+impressions?"],
    "views": [r"([0-9][0-9.,]*\s*[KMB]?)\s+views?"],
    "reactions": [r"([0-9][0-9.,]*\s*[KMB]?)\s+reactions?"],
    "comments": [r"([0-9][0-9.,]*\s*[KMB]?)\s+comments?"],
    "reposts": [r"([0-9][0-9.,]*\s*[KMB]?)\s+reposts?"],
    "shares": [r"([0-9][0-9.,]*\s*[KMB]?)\s+shares?"],
    "clicks": [r"([0-9][0-9.,]*\s*[KMB]?)\s+clicks?"],
}



def _update_connection_state(config: AppConfig, *, channel_id: str, status: str, last_error: str = "") -> ChannelConnection:
    current_time = now_iso()

    def mutate(existing: ChannelConnection | None) -> ChannelConnection:
        connection = existing or ChannelConnection(
            id=f"connection_{channel_id}",
            channel_id=channel_id,
            mode="playwright_local",
            status=status,
            local_profile_path=str(config.linkedin_user_data_dir),
            created_at=current_time,
        )
        connection.mode = "playwright_local"
        connection.status = status
        connection.last_checked_at = current_time
        connection.updated_at = current_time
        connection.last_error = last_error
        if status == "connected":
            connection.connected_at = current_time
        return connection

    return update_channel_connection(channel_id, mutate)



def parse_compact_number(raw: str) -> int | None:
    text = raw.strip().upper().replace(" ", "")
    if not text:
        return None

    multiplier = 1
    if text.endswith("K"):
        multiplier = 1_000
        text = text[:-1]
    elif text.endswith("M"):
        multiplier = 1_000_000
        text = text[:-1]
    elif text.endswith("B"):
        multiplier = 1_000_000_000
        text = text[:-1]

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts) == 2 and len(parts[1]) in {1, 2} and multiplier > 1:
            text = ".".join(parts)
        else:
            text = "".join(parts)
    elif "." in text:
        parts = text.split(".")
        if len(parts) == 2 and len(parts[1]) in {1, 2} and multiplier > 1:
            text = ".".join(parts)
        else:
            text = "".join(parts)

    try:
        numeric = float(text)
    except ValueError:
        return None
    return int(numeric * multiplier)



def _collect_visible_strings(page) -> list[str]:
    payload = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a, button, span, div'))
          .map((node) => {
            const text = (node.innerText || '').trim();
            const label = (node.getAttribute('aria-label') || '').trim();
            return [text, label].filter(Boolean).join(' | ');
          })
          .filter(Boolean)
          .filter((value) => value.length <= 120)
        """
    )
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload if str(item).strip()]



def extract_visible_linkedin_metrics(page) -> dict[str, Any]:
    visible_strings = _collect_visible_strings(page)
    joined = "\n".join(visible_strings)
    parsed: dict[str, int | None] = {
        "impressions": None,
        "views": None,
        "reactions": None,
        "comments": None,
        "reposts": None,
        "shares": None,
        "clicks": None,
    }
    raw_matches: dict[str, str] = {}
    for field_name, patterns in _METRIC_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, joined, re.IGNORECASE)
            if match:
                raw_matches[field_name] = match.group(1)
                parsed[field_name] = parse_compact_number(match.group(1))
                break
    return {
        "parsed": parsed,
        "raw_matches": raw_matches,
        "visible_strings": visible_strings[:250],
    }



def _delta(current: int | None, previous: int | None) -> int | None:
    if current is None or previous is None:
        return None
    return current - previous



def _record_log(job: MetricJob, *, status: str, step: str, worker_id: str, error_code: str = "", error_message: str = "") -> None:
    append_channel_job_log(
        ChannelJobLog(
            id=generate_id("log"),
            channel_id=job.channel_id,
            job_type="metrics",
            job_id=job.id,
            status=status,
            last_step=step,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error_code=error_code,
            error_message=error_message,
            screenshot_path=job.screenshot_path,
            created_at=now_iso(),
            worker_id=worker_id,
        )
    )



def _set_profile_busy(job: MetricJob, message: str) -> MetricJob:
    job.status = "queued"
    job.updated_at = now_iso()
    job.error_code = "profile_busy"
    job.error_message = message
    job.claimed_by = ""
    job.claimed_at = ""
    job.lease_expires_at = ""
    job.heartbeat_at = ""
    return save_metric_job(job)



def run_metric_job_with_runtime(
    config: AppConfig,
    app_runtime,
    job_id: str,
    *,
    worker_id: str = "",
    started_at: str = "",
):
    job = get_metric_job(job_id)
    if job is None:
        raise RuntimeError(f"Metric job {job_id} not found.")
    post = get_published_post(job.published_post_id)
    if post is None:
        raise RuntimeError(f"Published post {job.published_post_id} not found.")

    resolved_worker_id = worker_id or worker_id_for_channel(job.channel_id)
    save_channel_worker_heartbeat(
        job.channel_id,
        status="busy",
        current_job_id=job.id,
        current_job_type="metrics",
        worker_id=resolved_worker_id,
        started_at=started_at,
    )
    _record_log(job, status="running", step="claimed", worker_id=resolved_worker_id)

    try:
        trusted_url = normalize_linkedin_post_url(post.external_url)
    except LinkedInUrlError as exc:
        job.status = "failed"
        job.error_code = "untrusted_url"
        job.error_message = str(exc)
        job.finished_at = now_iso()
        job.updated_at = now_iso()
        job.claimed_by = ""
        job.claimed_at = ""
        job.lease_expires_at = ""
        job.heartbeat_at = ""
        save_metric_job(job)
        _record_log(job, status=job.status, step="validate_url", worker_id=resolved_worker_id, error_code=job.error_code, error_message=job.error_message)
        return job

    try:
        provider = app_runtime.browser_provider(preferred_provider_id=str(getattr(config, "linkedin_browser_provider_id", "") or ""))
        with provider.acquire_legacy_execution_session(
            profile_id=job.channel_id,
            purpose="linkedin.metrics",
            job_id=job.id,
            headless=True,
        ) as browser_session:
            page = browser_session.page
            session_label = browser_session.session_label
            try:
                logged_in, reason = is_linkedin_logged_in(page, config.linkedin_feed_url)
                if not logged_in:
                    _update_connection_state(config, channel_id=job.channel_id, status="needs_login", last_error=reason)
                    job.status = "needs_login"
                    job.error_code = "needs_login"
                    job.error_message = reason
                    job.finished_at = now_iso()
                    job.updated_at = now_iso()
                    job.claimed_by = ""
                    job.claimed_at = ""
                    job.lease_expires_at = ""
                    job.heartbeat_at = ""
                    save_metric_job(job)
                    save_channel_worker_heartbeat(
                        job.channel_id,
                        status="error",
                        current_job_id=job.id,
                        current_job_type="metrics",
                        last_error=reason,
                        worker_id=resolved_worker_id,
                        started_at=started_at,
                    )
                    _record_log(job, status=job.status, step="needs_login", worker_id=resolved_worker_id, error_code=job.error_code, error_message=job.error_message)
                    return job

                _update_connection_state(config, channel_id=job.channel_id, status="connected")
                page.goto(trusted_url, wait_until="domcontentloaded")
                page.bring_to_front()
                page.wait_for_timeout(2500)
                extraction = extract_visible_linkedin_metrics(page)
                job.screenshot_path = capture_worker_screenshot(
                    page,
                    channel_id=job.channel_id,
                    job_type="metrics",
                    job_id=job.id,
                    step="snapshot",
                )
                parsed = extraction.get("parsed", {})
                previous = latest_metric_snapshot_for_post(post.id)
                captured_at = now_iso()
                seconds_since_previous_snapshot = None
                if previous is not None:
                    try:
                        current_dt = datetime.fromisoformat(captured_at)
                        previous_dt = datetime.fromisoformat(previous.captured_at)
                        seconds_since_previous_snapshot = int((current_dt - previous_dt).total_seconds())
                    except Exception:
                        seconds_since_previous_snapshot = None
                snapshot = PostMetricSnapshot(
                    id=generate_id("snapshot"),
                    published_post_id=post.id,
                    channel_id=post.channel_id,
                    captured_at=captured_at,
                    impressions=parsed.get("impressions"),
                    views=parsed.get("views"),
                    reactions=parsed.get("reactions"),
                    comments=parsed.get("comments"),
                    reposts=parsed.get("reposts"),
                    shares=parsed.get("shares"),
                    clicks=parsed.get("clicks"),
                    raw_metrics_json={
                        "session_label": session_label,
                        "source_url": trusted_url,
                        "visible_strings": extraction.get("visible_strings", []),
                        "raw_matches": extraction.get("raw_matches", {}),
                    },
                    screenshot_path=job.screenshot_path,
                    created_at=captured_at,
                    delta_views=_delta(parsed.get("views"), previous.views if previous else None),
                    delta_impressions=_delta(parsed.get("impressions"), previous.impressions if previous else None),
                    delta_reactions=_delta(parsed.get("reactions"), previous.reactions if previous else None),
                    delta_comments=_delta(parsed.get("comments"), previous.comments if previous else None),
                    delta_reposts=_delta(parsed.get("reposts"), previous.reposts if previous else None),
                    seconds_since_previous_snapshot=seconds_since_previous_snapshot,
                )
                save_metric_snapshot(snapshot)
                job.status = "success"
                job.finished_at = now_iso()
                job.updated_at = now_iso()
                job.claimed_by = ""
                job.claimed_at = ""
                job.lease_expires_at = ""
                job.heartbeat_at = ""
                save_metric_job(job)
                save_channel_worker_heartbeat(
                    job.channel_id,
                    status="idle",
                    worker_id=resolved_worker_id,
                    started_at=started_at,
                )
                _record_log(job, status=job.status, step="metrics_captured", worker_id=resolved_worker_id)
                return job
            finally:
                pass
    except BrowserProfileBusyError as exc:
        job = _set_profile_busy(job, exc.user_message)
        save_channel_worker_heartbeat(
            job.channel_id,
            status="error",
            current_job_id=job.id,
            current_job_type="metrics",
            last_error=exc.user_message,
            worker_id=resolved_worker_id,
            started_at=started_at,
        )
        _record_log(job, status=job.status, step="profile_busy", worker_id=resolved_worker_id, error_code=job.error_code, error_message=job.error_message)
        return job
    except BrowserProviderError as exc:
        job.status = "failed"
        job.error_code = exc.code
        job.error_message = exc.user_message
        job.finished_at = now_iso()
        job.updated_at = now_iso()
        job.claimed_by = ""
        job.claimed_at = ""
        job.lease_expires_at = ""
        job.heartbeat_at = ""
        save_metric_job(job)
        save_channel_worker_heartbeat(
            job.channel_id,
            status="error",
            current_job_id=job.id,
            current_job_type="metrics",
            last_error=exc.user_message,
            worker_id=resolved_worker_id,
            started_at=started_at,
        )
        _record_log(job, status=job.status, step="metrics_error", worker_id=resolved_worker_id, error_code=job.error_code, error_message=job.error_message)
        return job
    except Exception as exc:
        job.status = "failed"
        job.error_code = "metrics_error"
        job.error_message = str(exc)
        job.finished_at = now_iso()
        job.updated_at = now_iso()
        job.claimed_by = ""
        job.claimed_at = ""
        job.lease_expires_at = ""
        job.heartbeat_at = ""
        save_metric_job(job)
        save_channel_worker_heartbeat(
            job.channel_id,
            status="error",
            current_job_id=job.id,
            current_job_type="metrics",
            last_error=str(exc),
            worker_id=resolved_worker_id,
            started_at=started_at,
        )
        _record_log(job, status=job.status, step="metrics_error", worker_id=resolved_worker_id, error_code=job.error_code, error_message=job.error_message)
        raise


def run_metric_job(
    config: AppConfig,
    job_id: str,
    *,
    worker_id: str = "",
    started_at: str = "",
) -> MetricJob:
    return run_metric_job_with_runtime(
        config,
        get_plugin_runtime(config, reset=True, strict=True),
        job_id,
        worker_id=worker_id,
        started_at=started_at,
    )
