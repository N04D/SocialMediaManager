from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
from channels.linkedin.provider_config import preferred_browser_provider_id
from channels.linkedin.targets import composer
from plugin_runtime import get_plugin_runtime
from src.core.browser import BrowserProfileBusyError, BrowserProviderError, BrowserSessionOptions, BrowserTarget
from src.core.media import MediaError, MediaMimeTypeError

from .runtime import save_channel_worker_heartbeat, worker_id_for_channel
from .session import is_linkedin_logged_in_session
from .urls import LinkedInUrlError, extract_linkedin_external_id, normalize_linkedin_post_url


def _update_connection_state(config: Any, *, channel_id: str, status: str, last_error: str = "") -> ChannelConnection:
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


def _record_log(
    job: PublishJob, *, status: str, step: str, worker_id: str, error_code: str = "", error_message: str = ""
) -> None:
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


def _capture_session_screenshot(browser_session) -> str:
    artifact = browser_session.screenshot(full_page=True)
    if artifact.path:
        return str(artifact.path)
    return artifact.id


def _safe_click_first(browser_session, targets: list[BrowserTarget], *, timeout_millis: int = 3000) -> bool:
    for target in targets:
        if not browser_session.element_exists(target, timeout_millis=timeout_millis):
            continue
        if not browser_session.element_enabled(target, timeout_millis=timeout_millis):
            continue
        browser_session.click(target)
        return True
    return False


def _dismiss_cookie_banner(browser_session) -> None:
    _safe_click_first(browser_session, composer.COOKIE_ACCEPT_TARGETS, timeout_millis=1000)


def _open_linkedin_post_composer(browser_session) -> None:
    if not _safe_click_first(browser_session, composer.OPEN_COMPOSER_TARGETS, timeout_millis=5000):
        raise RuntimeError("Could not find the LinkedIn post composer button.")
    if not browser_session.wait_for(composer.COMPOSER_EDITOR, state="visible", timeout_millis=10000):
        raise RuntimeError("Could not find the LinkedIn composer editor.")


def _fill_composer(browser_session, text: str) -> str:
    rendered = browser_session.evaluate(
        """
        (text) => {
          const selectors = [
            "div[role='dialog'] [contenteditable='true']",
            "div[role='dialog'] [role='textbox']",
            "[contenteditable='true']"
          ];
          const editor = selectors.map((selector) => document.querySelector(selector)).find(Boolean);
          if (!editor) return "";
          editor.focus();
          editor.innerText = text;
          editor.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
          return editor.innerText || "";
        }
        """,
        text,
    )
    if isinstance(rendered, str) and rendered.strip():
        return rendered
    return browser_session.text_content(composer.COMPOSER_EDITOR).strip()


def _upload_images(browser_session, image_paths: list[Path]) -> None:
    for image_path in image_paths:
        browser_session.upload(composer.MEDIA_INPUT, image_path)


def _derivative_media_asset_ids(derivative) -> list[str]:
    metadata = dict(derivative.generation_metadata_json or {})
    raw_ids = metadata.get("media_asset_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    return [str(item) for item in raw_ids if str(item).strip()] if isinstance(raw_ids, list) else []


def _derivative_image_paths(derivative) -> list[Path]:
    metadata = dict(derivative.generation_metadata_json or {})
    raw_paths = metadata.get("image_paths") or metadata.get("media_paths") or []
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    paths: list[Path] = []
    if isinstance(raw_paths, list):
        for item in raw_paths:
            if str(item).strip():
                paths.append(Path(str(item)))
    return paths


def _media_assets_for_publish(config: Any, app_runtime, derivative) -> list[str]:
    media_asset_ids = _derivative_media_asset_ids(derivative)
    if media_asset_ids:
        return media_asset_ids
    legacy_paths = _derivative_image_paths(derivative)
    if not legacy_paths:
        return []
    media_runtime = app_runtime.media_runtime(config)
    imported: list[str] = []
    for image_path in legacy_paths:
        asset = media_runtime.import_legacy_path(image_path, workspace_id=derivative.channel_id, derivative=derivative)
        imported.append(asset.id)
    return imported


def _upload_media_assets(config: Any, app_runtime, browser_session, derivative, media_asset_ids: list[str]) -> None:
    media_runtime = app_runtime.media_runtime(config)
    for asset_id in media_asset_ids:
        asset = media_runtime.get_asset(asset_id, workspace_id=derivative.channel_id)
        if asset.mime_type not in {"image/jpeg", "image/png"}:
            raise MediaMimeTypeError(
                "media.linkedin_unsupported_mime", "LinkedIn image publish does not support this media type."
            )
        with media_runtime.materialize(
            asset.id, workspace_id=derivative.channel_id, purpose="linkedin.image_publish"
        ) as materialized:
            browser_session.upload(composer.MEDIA_INPUT, materialized.local_path)


def _extract_post_url(browser_session) -> tuple[str, str]:
    anchors = browser_session.evaluate(
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


def _confirmation_seen(browser_session) -> tuple[bool, str]:
    for target in composer.CONFIRMATION_TARGETS:
        if browser_session.element_exists(target, timeout_millis=4000):
            return True, target.text
    return False, ""


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
    config: Any,
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
        provider = app_runtime.browser_provider(
            preferred_provider_id=preferred_browser_provider_id(config, channel_id=job.channel_id)
        )
        browser_session = provider.create_session(
            BrowserSessionOptions(
                profile_id=job.channel_id,
                headless=not _headed_default_for_publish(job),
                exclusive=True,
                metadata={"purpose": "linkedin.publish", "job_id": job.id, "channel_id": job.channel_id},
            )
        )
        session_label = str(getattr(browser_session, "session_label", browser_session.session_id))
        try:
            logged_in, reason = is_linkedin_logged_in_session(browser_session, config.linkedin_feed_url)
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
                _record_log(
                    job,
                    status=job.status,
                    step="needs_login",
                    worker_id=resolved_worker_id,
                    error_code=job.error_code,
                    error_message=reason,
                )
                return job

            _update_connection_state(config, channel_id=job.channel_id, status="connected")
            browser_session.navigate(config.linkedin_feed_url)
            _dismiss_cookie_banner(browser_session)
            browser_session.wait_for_timeout(int(config.linkedin_wait_after_open_seconds * 1000))
            job.last_step = "open_composer"
            job.updated_at = now_iso()
            save_publish_job(job)
            _open_linkedin_post_composer(browser_session)

            job.last_step = "fill_composer"
            job.updated_at = now_iso()
            save_publish_job(job)
            rendered_text = _fill_composer(browser_session, derivative.body)
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
            media_asset_ids = _media_assets_for_publish(config, app_runtime, derivative)
            if media_asset_ids:
                job.last_step = "upload_media"
                job.updated_at = now_iso()
                save_publish_job(job)
                _upload_media_assets(config, app_runtime, browser_session, derivative, media_asset_ids)
                dry_run_details["uploaded_image_count"] = len(media_asset_ids)
                dry_run_details["media_asset_ids"] = media_asset_ids
            job.last_step = "filled_composer"
            job.screenshot_path = _capture_session_screenshot(browser_session)
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
            if not _safe_click_first(browser_session, composer.FINAL_POST_TARGETS, timeout_millis=8000):
                raise RuntimeError("Could not find the final LinkedIn Post button.")
            browser_session.wait_for_timeout(2500)

            confirmed, confirmation_signal = _confirmation_seen(browser_session)

            result_url, external_id = _extract_post_url(browser_session)
            job.screenshot_path = _capture_session_screenshot(browser_session)
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
                _record_log(
                    job,
                    status=job.status,
                    step=job.last_step,
                    worker_id=resolved_worker_id,
                    error_code=job.error_code,
                    error_message=job.error_message,
                )
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
            browser_session.close()
    except MediaError as exc:
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
        _record_log(
            job,
            status=job.status,
            step=job.last_step or "media",
            worker_id=resolved_worker_id,
            error_code=exc.code,
            error_message=exc.user_message,
        )
        return job
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
        _record_log(
            job,
            status=job.status,
            step=job.last_step,
            worker_id=resolved_worker_id,
            error_code=job.error_code,
            error_message=job.error_message,
        )
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
        _record_log(
            job,
            status=job.status,
            step=job.last_step or "publish_error",
            worker_id=resolved_worker_id,
            error_code=job.error_code,
            error_message=job.error_message,
        )
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
        _record_log(
            job,
            status=job.status,
            step=job.last_step or "publish_error",
            worker_id=resolved_worker_id,
            error_code=job.error_code,
            error_message=job.error_message,
        )
        raise


def run_publish_job(
    config: Any,
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
