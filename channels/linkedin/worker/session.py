from __future__ import annotations

import re
import time
from typing import Any

from channel_models import ChannelConnection, ChannelJobLog
from channel_store import append_channel_job_log, generate_id, now_iso, update_channel_connection
from pipeline import POST_BUTTON_PATTERNS, AppConfig
from plugin_runtime import get_plugin_runtime
from src.core.browser import BrowserProfileBusyError, BrowserProviderError, BrowserSessionOptions, BrowserTarget
from src.core.plugins import PluginCapabilityError, PluginDependencyError

from .browser import persistent_profile_path
from .runtime import save_channel_worker_heartbeat, worker_id_for_channel

LOGIN_URL_TOKENS = ("/login", "/checkpoint", "/signup")
AUTHENTICATED_SELECTORS = (
    "nav.global-nav",
    "a[href*='/feed/']",
    "button[aria-label*='Start a post']",
    "div.share-box-feed-entry__top-bar",
)


def _current_url(page) -> str:
    try:
        return str(page.url or "")
    except Exception:
        return ""


def _record_url(diagnostics: dict[str, Any] | None, url: str) -> None:
    if diagnostics is None or not url:
        return
    urls = diagnostics.setdefault("current_url_changes", [])
    if not urls or urls[-1] != url:
        urls.append(url)


def attach_navigation_observer(page, diagnostics: dict[str, Any] | None) -> None:
    if diagnostics is None:
        return

    def on_frame_navigated(frame) -> None:
        try:
            if frame != page.main_frame:
                return
        except Exception:
            return
        diagnostics["navigation_count"] = int(diagnostics.get("navigation_count", 0)) + 1
        _record_url(diagnostics, _current_url(page))

    page.on("framenavigated", on_frame_navigated)
    _record_url(diagnostics, _current_url(page))


def navigate_linkedin_once(page, feed_url: str, *, diagnostics: dict[str, Any] | None = None) -> None:
    if diagnostics is not None:
        diagnostics["requested_navigation_count"] = int(diagnostics.get("requested_navigation_count", 0)) + 1
    page.goto(feed_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    _record_url(diagnostics, _current_url(page))


def inspect_linkedin_auth_state(page, *, diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
    current_url = _current_url(page)
    current_url_lower = current_url.lower()
    _record_url(diagnostics, current_url)

    if any(token in current_url_lower for token in LOGIN_URL_TOKENS):
        reason = f"LinkedIn redirected to {current_url or 'the login flow'}."
        if diagnostics is not None:
            diagnostics["last_reason"] = reason
        return {
            "authenticated": False,
            "needs_login": True,
            "reason": reason,
            "marker": "login_url",
            "current_url": current_url,
        }

    for pattern in POST_BUTTON_PATTERNS:
        try:
            locator = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))
            if locator.count():
                if diagnostics is not None:
                    diagnostics["authentication_marker"] = f"post_button:{pattern}"
                return {
                    "authenticated": True,
                    "needs_login": False,
                    "reason": "",
                    "marker": f"post_button:{pattern}",
                    "current_url": current_url,
                }
        except Exception:
            continue

    for selector in AUTHENTICATED_SELECTORS:
        try:
            if page.locator(selector).count():
                if diagnostics is not None:
                    diagnostics["authentication_marker"] = selector
                return {
                    "authenticated": True,
                    "needs_login": False,
                    "reason": "",
                    "marker": selector,
                    "current_url": current_url,
                }
        except Exception:
            continue

    if "linkedin.com/feed" in current_url_lower:
        if diagnostics is not None:
            diagnostics["authentication_marker"] = "feed_url"
        return {
            "authenticated": True,
            "needs_login": False,
            "reason": "",
            "marker": "feed_url",
            "current_url": current_url,
        }

    reason = "Could not confirm an authenticated LinkedIn feed session."
    if diagnostics is not None:
        diagnostics["last_reason"] = reason
    return {
        "authenticated": False,
        "needs_login": False,
        "reason": reason,
        "marker": "",
        "current_url": current_url,
    }


def is_linkedin_logged_in(page, feed_url: str, *, diagnostics: dict[str, Any] | None = None) -> tuple[bool, str]:
    navigate_linkedin_once(page, feed_url, diagnostics=diagnostics)
    result = inspect_linkedin_auth_state(page, diagnostics=diagnostics)
    return bool(result["authenticated"]), str(result["reason"])


def wait_for_manual_linkedin_login(
    page,
    *,
    timeout_seconds: int = 600,
    poll_millis: int = 2000,
    diagnostics: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_seconds
    last_reason = "Waiting for manual login."
    if diagnostics is not None:
        diagnostics["manual_login_timeout_seconds"] = timeout_seconds
    while time.monotonic() < deadline:
        result = inspect_linkedin_auth_state(page, diagnostics=diagnostics)
        if result["authenticated"]:
            return True, ""
        last_reason = str(result["reason"] or last_reason)
        page.wait_for_timeout(poll_millis)
    if diagnostics is not None:
        diagnostics["timeout_reason"] = last_reason
    return False, last_reason


def inspect_linkedin_auth_state_session(
    browser_session, *, diagnostics: dict[str, Any] | None = None
) -> dict[str, Any]:
    current_url = browser_session.current_url()
    current_url_lower = current_url.lower()
    _record_url(diagnostics, current_url)
    if any(token in current_url_lower for token in LOGIN_URL_TOKENS):
        reason = f"LinkedIn redirected to {current_url or 'the login flow'}."
        if diagnostics is not None:
            diagnostics["last_reason"] = reason
        return {
            "authenticated": False,
            "needs_login": True,
            "reason": reason,
            "marker": "login_url",
            "current_url": current_url,
        }

    for pattern in POST_BUTTON_PATTERNS:
        target = BrowserTarget(role="button", accessible_name=pattern)
        if browser_session.element_exists(target):
            if diagnostics is not None:
                diagnostics["authentication_marker"] = f"post_button:{pattern}"
            return {
                "authenticated": True,
                "needs_login": False,
                "reason": "",
                "marker": f"post_button:{pattern}",
                "current_url": current_url,
            }

    for selector in AUTHENTICATED_SELECTORS:
        target = BrowserTarget(css=selector)
        if browser_session.element_exists(target):
            if diagnostics is not None:
                diagnostics["authentication_marker"] = selector
            return {
                "authenticated": True,
                "needs_login": False,
                "reason": "",
                "marker": selector,
                "current_url": current_url,
            }

    if "linkedin.com/feed" in current_url_lower:
        if diagnostics is not None:
            diagnostics["authentication_marker"] = "feed_url"
        return {
            "authenticated": True,
            "needs_login": False,
            "reason": "",
            "marker": "feed_url",
            "current_url": current_url,
        }

    reason = "Could not confirm an authenticated LinkedIn feed session."
    if diagnostics is not None:
        diagnostics["last_reason"] = reason
    return {
        "authenticated": False,
        "needs_login": False,
        "reason": reason,
        "marker": "",
        "current_url": current_url,
    }


def wait_for_manual_linkedin_login_session(
    browser_session,
    *,
    timeout_seconds: int = 600,
    poll_millis: int = 2000,
    diagnostics: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_seconds
    last_reason = "Waiting for manual login."
    if diagnostics is not None:
        diagnostics["manual_login_timeout_seconds"] = timeout_seconds
    while time.monotonic() < deadline:
        result = inspect_linkedin_auth_state_session(browser_session, diagnostics=diagnostics)
        if result["authenticated"]:
            return True, ""
        last_reason = str(result["reason"] or last_reason)
        browser_session.wait_for_timeout(poll_millis)
    if diagnostics is not None:
        diagnostics["timeout_reason"] = last_reason
    return False, last_reason


def is_linkedin_logged_in_session(
    browser_session, feed_url: str, *, diagnostics: dict[str, Any] | None = None
) -> tuple[bool, str]:
    if diagnostics is not None:
        diagnostics["requested_navigation_count"] = int(diagnostics.get("requested_navigation_count", 0)) + 1
    browser_session.navigate(feed_url)
    result = inspect_linkedin_auth_state_session(browser_session, diagnostics=diagnostics)
    return bool(result["authenticated"]), str(result["reason"])


def _save_connection_state(
    config: AppConfig, *, channel_id: str, status: str, last_error: str = ""
) -> ChannelConnection:
    current_time = now_iso()

    def mutate(existing: ChannelConnection | None) -> ChannelConnection:
        connection = existing or ChannelConnection(
            id=f"connection_{channel_id}",
            channel_id=channel_id,
            mode="playwright_local",
            status=status,
            local_profile_path=str(persistent_profile_path(config)),
            created_at=current_time,
        )
        connection.mode = "playwright_local"
        connection.status = status
        connection.last_checked_at = current_time
        connection.updated_at = current_time
        connection.last_error = last_error
        connection.local_profile_path = str(persistent_profile_path(config))
        if status == "connected":
            connection.connected_at = current_time
        return connection

    return update_channel_connection(channel_id, mutate)


def _preserve_connected_or_error(config: AppConfig, *, channel_id: str, last_error: str) -> ChannelConnection:
    current_time = now_iso()

    def mutate(existing: ChannelConnection | None) -> ChannelConnection:
        status = existing.status if existing and existing.status == "connected" else "error"
        connection = existing or ChannelConnection(
            id=f"connection_{channel_id}",
            channel_id=channel_id,
            mode="playwright_local",
            status=status,
            local_profile_path=str(persistent_profile_path(config)),
            created_at=current_time,
        )
        connection.mode = "playwright_local"
        connection.status = status
        connection.last_checked_at = current_time
        connection.updated_at = current_time
        connection.last_error = last_error
        connection.local_profile_path = str(persistent_profile_path(config))
        return connection

    return update_channel_connection(channel_id, mutate)


def _browser_error_message(exc: Exception) -> str:
    if isinstance(exc, (BrowserProviderError, PluginCapabilityError, PluginDependencyError)):
        return exc.user_message
    return str(exc) or "Unexpected LinkedIn session check error."


def run_session_check_with_runtime(
    config: AppConfig,
    app_runtime,
    *,
    channel_id: str = "linkedin",
    worker_id: str = "",
    started_at: str = "",
) -> ChannelConnection:
    action_id = generate_id("session_check")
    resolved_worker_id = worker_id or worker_id_for_channel(channel_id)
    diagnostics: dict[str, Any] = {
        "action_id": action_id,
        "worker_id": resolved_worker_id,
        "browser_launch_count": 0,
        "navigation_count": 0,
        "requested_navigation_count": 0,
        "current_url_changes": [],
        "authentication_marker": "",
        "human_takeover_status": "not_required",
    }
    save_channel_worker_heartbeat(
        channel_id,
        status="busy",
        current_job_id=action_id,
        current_job_type="session_check",
        worker_id=resolved_worker_id,
        started_at=started_at,
    )
    append_channel_job_log(
        ChannelJobLog(
            id=generate_id("log"),
            channel_id=channel_id,
            job_type="session_check",
            job_id=action_id,
            status="running",
            last_step="check_session",
            started_at=now_iso(),
            created_at=now_iso(),
            worker_id=resolved_worker_id,
        )
    )
    try:
        provider_runtime = app_runtime.resolve_provider("browser.session")
        provider = provider_runtime.services["browser_provider"]
        diagnostics["browser_provider_id"] = provider_runtime.manifest.id
        browser_session = provider.create_session(
            BrowserSessionOptions(
                profile_id=channel_id,
                headless=True,
                exclusive=True,
                metadata={
                    "owner": f"{resolved_worker_id}:session_check",
                    "purpose": "linkedin.session_check",
                    "job_id": action_id,
                    "channel_id": channel_id,
                },
            )
        )
        diagnostics["browser_launch_count"] = 1
        diagnostics["browser_session_id"] = browser_session.session_id
        diagnostics["browser_session_status"] = "active"
        try:
            logged_in, reason = is_linkedin_logged_in_session(
                browser_session, config.linkedin_feed_url, diagnostics=diagnostics
            )
            log_status = "success" if logged_in else "needs_login"
            if logged_in:
                connection = _save_connection_state(config, channel_id=channel_id, status="connected")
                save_channel_worker_heartbeat(
                    channel_id,
                    status="idle",
                    worker_id=resolved_worker_id,
                    started_at=started_at,
                )
            else:
                connection = _save_connection_state(
                    config,
                    channel_id=channel_id,
                    status="needs_login",
                    last_error=reason,
                )
                save_channel_worker_heartbeat(
                    channel_id,
                    status="error",
                    current_job_id=action_id,
                    current_job_type="session_check",
                    last_error=reason,
                    worker_id=resolved_worker_id,
                    started_at=started_at,
                )
            connection.last_connect_diagnostics_json = dict(diagnostics)
            update_channel_connection(channel_id, lambda existing: connection)
            append_channel_job_log(
                ChannelJobLog(
                    id=generate_id("log"),
                    channel_id=channel_id,
                    job_type="session_check",
                    job_id=action_id,
                    status=log_status,
                    last_step="verified_session" if logged_in else "authentication_required",
                    started_at=started_at,
                    finished_at=now_iso(),
                    created_at=now_iso(),
                    worker_id=resolved_worker_id,
                    error_message=str(diagnostics),
                )
            )
            return connection
        finally:
            browser_session.close()
    except BrowserProfileBusyError as exc:
        connection = _preserve_connected_or_error(
            config, channel_id=channel_id, last_error=f"profile_busy: {exc.user_message}"
        )
        save_channel_worker_heartbeat(
            channel_id,
            status="error",
            current_job_id=action_id,
            current_job_type="session_check",
            last_error=exc.user_message,
            worker_id=resolved_worker_id,
            started_at=started_at,
        )
        return connection
    except Exception as exc:
        message = _browser_error_message(exc)
        _preserve_connected_or_error(config, channel_id=channel_id, last_error=message)
        save_channel_worker_heartbeat(
            channel_id,
            status="error",
            current_job_id=action_id,
            current_job_type="session_check",
            last_error=message,
            worker_id=resolved_worker_id,
            started_at=started_at,
        )
        raise


def run_session_check_action(
    config: AppConfig,
    *,
    channel_id: str = "linkedin",
    worker_id: str = "",
    started_at: str = "",
) -> ChannelConnection:
    return run_session_check_with_runtime(
        config,
        get_plugin_runtime(config, reset=True, strict=True),
        channel_id=channel_id,
        worker_id=worker_id,
        started_at=started_at,
    )
