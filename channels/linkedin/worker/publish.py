from __future__ import annotations

import re

from channel_actions import record_confirmed_publish
from channel_models import ChannelConnection, ChannelJobLog, PublishJob
from channel_store import (
    append_channel_job_log,
    generate_id,
    get_derivative,
    get_publish_job,
    now_iso,
    save_publish_job,
    update_channel_connection,
)
from pipeline import (
    AppConfig,
    dismiss_linkedin_cookie_banner,
    find_composer_editor,
    open_linkedin_post_composer,
    type_into_contenteditable,
)
from plugin_runtime import get_plugin_runtime
from src.core.browser import BrowserProfileBusyError, BrowserProviderError

from .browser import capture_worker_screenshot
from .runtime import save_channel_worker_heartbeat, worker_id_for_channel
from .session import is_linkedin_logged_in
from .urls import LinkedInUrlError, extract_linkedin_external_id, normalize_linkedin_post_url

POST_CONFIRMATION_PATTERNS = [
    r"post was created",
    r"post is now live",
    r"shared with your network",
    r"uw bericht is gepubliceerd",
]



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



def _normalize_text(value: str) -> str:
    cleaned = value.replace("\r\n", "\n").replace("\xa0", " ")
    cleaned = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", cleaned)
    lines = [line.strip() for line in cleaned.strip().split("\n") if line.strip()]
    return "\n".join(lines).strip()



def _line_break_signature(value: str) -> list[str]:
    normalized = value.replace("\r\n", "\n").strip("\n")
    if not normalized:
        return []
    return [line.rstrip() for line in normalized.split("\n")]



def _record_log(job: PublishJob, *, status: str, step: str, worker_id: str, error_code: str = "", error_message: str = "") -> None:
    append_channel_job_log(
        ChannelJobLog(
            id=generate_id("log"),
            channel_id=job.channel_id,
            job_type="publish",
            job_id=job.id,
            status=status,
            last_step=step,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error_code=error_code,
            error_message=error_message,
            screenshot_path=job.screenshot_path,
            result_url=job.result_url,
            created_at=now_iso(),
            worker_id=worker_id,
        )
    )



def _find_composer_dialog_and_editor(page):
    dialogs = page.get_by_role("dialog")
    for index in range(dialogs.count()):
        dialog = dialogs.nth(index)
        try:
            dialog.wait_for(state="visible", timeout=3000)
            editor = find_composer_editor(dialog)
            return dialog, editor
        except Exception:
            continue
    editor = find_composer_editor(page)
    return page, editor


def _final_post_button(dialog):
    candidates = [
        dialog.get_by_role("button", name=re.compile(r"^Post$", re.IGNORECASE)).last,
        dialog.get_by_role("button", name=re.compile(r"^Plaatsen$", re.IGNORECASE)).last,
        dialog.locator("button:has-text('Post')").last,
        dialog.locator("button:has-text('Plaatsen')").last,
    ]
    for candidate in candidates:
        try:
            if candidate.count():
                return candidate
        except Exception:
            continue
    raise RuntimeError("Could not find the final LinkedIn Post button.")



def _extract_post_url(page) -> tuple[str, str]:
    anchors = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href]'))
          .map((anchor) => anchor.href)
          .filter((href) => href.includes('/feed/update/') || href.includes('/posts/'))
        """
    )
    if isinstance(anchors, list):
        for href in anchors:
            try:
                normalized = normalize_linkedin_post_url(str(href))
            except LinkedInUrlError:
                continue
            return normalized, extract_linkedin_external_id(normalized)
    return "", ""



def _assert_live_submit_allowed(job: PublishJob) -> None:
    if job.run_mode != "live":
        raise RuntimeError("Dry-run protection blocked the final LinkedIn submit click.")


def _headed_default_for_publish(job: PublishJob) -> bool:
    return job.run_mode == "live"



def _set_profile_busy(job: PublishJob, message: str) -> PublishJob:
    job.status = "queued"
    job.updated_at = now_iso()
    job.last_step = "profile_busy"
    job.error_code = "profile_busy"
    job.error_message = message
    job.claimed_by = ""
    job.claimed_at = ""
    job.lease_expires_at = ""
    job.heartbeat_at = ""
    return save_publish_job(job)



def run_publish_job_with_runtime(
    config: AppConfig,
    app_runtime,
    job_id: str,
    *,
    worker_id: str = "",
    started_at: str = "",
) -> PublishJob:
    job = get_publish_job(job_id)
    if job is None:
        raise RuntimeError(f"Publish job {job_id} not found.")
    derivative = get_derivative(job.derivative_id)
    if derivative is None:
        raise RuntimeError(f"Derivative {job.derivative_id} not found.")

    resolved_worker_id = worker_id or worker_id_for_channel(job.channel_id)
    save_channel_worker_heartbeat(
        job.channel_id,
        status="busy",
        current_job_id=job.id,
        current_job_type="publish",
        worker_id=resolved_worker_id,
        started_at=started_at,
    )
    _record_log(job, status="running", step=job.last_step or "claimed", worker_id=resolved_worker_id)

    try:
        provider = app_runtime.browser_provider(preferred_provider_id=str(getattr(config, "linkedin_browser_provider_id", "") or ""))
        with provider.acquire_legacy_execution_session(
            profile_id=job.channel_id,
            purpose="linkedin.publish",
            job_id=job.id,
            headless=not _headed_default_for_publish(job),
        ) as browser_session:
            page = browser_session.page
            session_label = browser_session.session_label
            try:
                logged_in, reason = is_linkedin_logged_in(page, config.linkedin_feed_url)
                if not logged_in:
                    _update_connection_state(config, channel_id=job.channel_id, status="needs_login", last_error=reason)
                    job.status = "needs_login"
                    job.finished_at = now_iso()
                    job.updated_at = now_iso()
                    job.error_code = "needs_login"
                    job.error_message = reason
                    job.claimed_by = ""
                    job.claimed_at = ""
                    job.lease_expires_at = ""
                    job.heartbeat_at = ""
                    save_publish_job(job)
                    save_channel_worker_heartbeat(
                        job.channel_id,
                        status="error",
                        current_job_id=job.id,
                        current_job_type="publish",
                        last_error=reason,
                        worker_id=resolved_worker_id,
                        started_at=started_at,
                    )
                    _record_log(job, status=job.status, step="needs_login", worker_id=resolved_worker_id, error_code=job.error_code, error_message=reason)
                    return job

                _update_connection_state(config, channel_id=job.channel_id, status="connected")
                page.goto(config.linkedin_feed_url, wait_until="domcontentloaded")
                page.bring_to_front()
                dismiss_linkedin_cookie_banner(page)
                page.wait_for_timeout(int(config.linkedin_wait_after_open_seconds * 1000))
                job.last_step = "open_composer"
                job.updated_at = now_iso()
                save_publish_job(job)
                open_linkedin_post_composer(page)

                dialog, editor = _find_composer_dialog_and_editor(page)
                job.last_step = "fill_composer"
                job.updated_at = now_iso()
                save_publish_job(job)
                type_into_contenteditable(page, editor, derivative.body)
                rendered_text = editor.inner_text().strip()
                expected_normalized = _normalize_text(derivative.body)
                actual_normalized = _normalize_text(rendered_text)
                content_match = expected_normalized == actual_normalized
                line_breaks_match = _line_break_signature(derivative.body) == _line_break_signature(rendered_text)
                dry_run_details = {
                    "expected_character_count": len(derivative.body),
                    "actual_character_count": len(rendered_text),
                    "content_match": content_match,
                    "line_breaks_match": line_breaks_match,
                    "composer_detected": True,
                    "final_submit_clicked": False,
                    "session_label": session_label,
                }
                job.last_step = "filled_composer"
                job.screenshot_path = capture_worker_screenshot(
                    page,
                    channel_id=job.channel_id,
                    job_type="publish",
                    job_id=job.id,
                    step="filled",
                )
                job.result_details_json = dict(job.result_details_json or {}) | dry_run_details
                job.updated_at = now_iso()
                save_publish_job(job)
                if not content_match:
                    raise RuntimeError("LinkedIn composer content validation failed after fill.")

                if job.run_mode != "live":
                    job.status = "success"
                    job.finished_at = now_iso()
                    job.updated_at = now_iso()
                    job.last_step = "dry_run_complete"
                    job.result_url = ""
                    job.claimed_by = ""
                    job.claimed_at = ""
                    job.lease_expires_at = ""
                    job.heartbeat_at = ""
                    save_publish_job(job)
                    save_channel_worker_heartbeat(
                        job.channel_id,
                        status="idle",
                        worker_id=resolved_worker_id,
                        started_at=started_at,
                    )
                    _record_log(job, status=job.status, step=job.last_step, worker_id=resolved_worker_id)
                    return job

                job.last_step = "submit_post"
                job.submitted_at = now_iso()
                job.updated_at = job.submitted_at
                save_publish_job(job)
                _assert_live_submit_allowed(job)
                submit_button = _final_post_button(dialog)
                submit_button.click(timeout=8000, force=True)
                page.wait_for_timeout(2500)

                confirmed = False
                confirmation_signal = ""
                for pattern in POST_CONFIRMATION_PATTERNS:
                    try:
                        page.get_by_text(re.compile(pattern, re.IGNORECASE)).first.wait_for(
                            state="visible",
                            timeout=4000,
                        )
                        confirmed = True
                        confirmation_signal = pattern
                        break
                    except Exception:
                        continue

                result_url, external_id = _extract_post_url(page)
                job.screenshot_path = capture_worker_screenshot(
                    page,
                    channel_id=job.channel_id,
                    job_type="publish",
                    job_id=job.id,
                    step="submitted",
                )
                job.result_details_json = dict(job.result_details_json or {}) | {
                    "confirmation_seen": confirmed,
                    "confirmation_signal": confirmation_signal,
                    "published_url_pending": confirmed and not bool(result_url),
                    "final_submit_clicked": True,
                }
                if not confirmed and not result_url:
                    job.status = "manual_verification_required"
                    job.finished_at = now_iso()
                    job.updated_at = now_iso()
                    job.last_step = "manual_verification_required"
                    job.error_code = "unknown_result"
                    job.error_message = "The LinkedIn publish action may have succeeded, but no confirmation or trusted post URL was captured."
                    job.unknown_result = True
                    job.manual_verification_required = True
                    job.claimed_by = ""
                    job.claimed_at = ""
                    job.lease_expires_at = ""
                    job.heartbeat_at = ""
                    save_publish_job(job)
                    save_channel_worker_heartbeat(
                        job.channel_id,
                        status="error",
                        current_job_id=job.id,
                        current_job_type="publish",
                        last_error=job.error_message,
                        worker_id=resolved_worker_id,
                        started_at=started_at,
                    )
                    _record_log(job, status=job.status, step=job.last_step, worker_id=resolved_worker_id, error_code=job.error_code, error_message=job.error_message)
                    return job

                record_confirmed_publish(
                    job=job,
                    derivative=derivative,
                    external_url=result_url,
                    external_id=external_id,
                    status="confirmed" if result_url else "confirmed_missing_url",
                    raw_result={
                        "confirmation_seen": confirmed,
                        "confirmation_signal": confirmation_signal,
                        "session_label": session_label,
                    },
                )
                job.status = "success"
                job.finished_at = now_iso()
                job.updated_at = now_iso()
                job.last_step = "publish_confirmed"
                job.result_url = result_url
                job.result_external_id = external_id
                job.claimed_by = ""
                job.claimed_at = ""
                job.lease_expires_at = ""
                job.heartbeat_at = ""
                save_publish_job(job)
                save_channel_worker_heartbeat(
                    job.channel_id,
                    status="idle",
                    worker_id=resolved_worker_id,
                    started_at=started_at,
                )
                _record_log(job, status=job.status, step=job.last_step, worker_id=resolved_worker_id)
                return job
            finally:
                pass
    except BrowserProfileBusyError as exc:
        job = _set_profile_busy(job, exc.user_message)
        save_channel_worker_heartbeat(
            job.channel_id,
            status="error",
            current_job_id=job.id,
            current_job_type="publish",
            last_error=exc.user_message,
            worker_id=resolved_worker_id,
            started_at=started_at,
        )
        _record_log(job, status=job.status, step=job.last_step, worker_id=resolved_worker_id, error_code=job.error_code, error_message=job.error_message)
        return job
    except BrowserProviderError as exc:
        job.status = "failed"
        job.finished_at = now_iso()
        job.updated_at = now_iso()
        job.error_code = exc.code
        job.error_message = exc.user_message
        job.claimed_by = ""
        job.claimed_at = ""
        job.lease_expires_at = ""
        job.heartbeat_at = ""
        save_publish_job(job)
        save_channel_worker_heartbeat(
            job.channel_id,
            status="error",
            current_job_id=job.id,
            current_job_type="publish",
            last_error=exc.user_message,
            worker_id=resolved_worker_id,
            started_at=started_at,
        )
        _record_log(job, status=job.status, step=job.last_step or "publish_error", worker_id=resolved_worker_id, error_code=job.error_code, error_message=job.error_message)
        return job
    except Exception as exc:
        job.status = "failed"
        job.finished_at = now_iso()
        job.updated_at = now_iso()
        job.error_code = "publish_error"
        job.error_message = str(exc)
        job.claimed_by = ""
        job.claimed_at = ""
        job.lease_expires_at = ""
        job.heartbeat_at = ""
        save_publish_job(job)
        save_channel_worker_heartbeat(
            job.channel_id,
            status="error",
            current_job_id=job.id,
            current_job_type="publish",
            last_error=str(exc),
            worker_id=resolved_worker_id,
            started_at=started_at,
        )
        _record_log(job, status=job.status, step=job.last_step or "publish_error", worker_id=resolved_worker_id, error_code=job.error_code, error_message=job.error_message)
        raise


def run_publish_job(
    config: AppConfig,
    job_id: str,
    *,
    worker_id: str = "",
    started_at: str = "",
) -> PublishJob:
    return run_publish_job_with_runtime(
        config,
        get_plugin_runtime(config, reset=True, strict=True),
        job_id,
        worker_id=worker_id,
        started_at=started_at,
    )
