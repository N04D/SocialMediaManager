from __future__ import annotations

from channel_models import ChannelConnection, ChannelJobLog
from channel_store import (
    append_channel_job_log,
    claim_channel_connect,
    generate_id,
    now_iso,
    update_channel_connection,
)
from pipeline import AppConfig
from plugin_runtime import get_plugin_runtime
from src.core.browser import (
    BrowserProfileBusyError,
    BrowserProviderError,
    BrowserSessionOptions,
    BrowserUnavailableError,
    HumanTakeoverRequest,
)
from src.core.plugins import PluginCapabilityError, PluginDependencyError

from .browser import persistent_profile_path
from .runtime import save_channel_worker_heartbeat, worker_id_for_channel
from .session import (
    attach_navigation_observer,
    inspect_linkedin_auth_state,
    wait_for_manual_linkedin_login,
)


def _finalize_connect_state(
    config: AppConfig,
    *,
    channel_id: str,
    status: str,
    diagnostics: dict,
    last_error: str = "",
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
        connection.local_profile_path = str(persistent_profile_path(config))
        connection.capabilities_snapshot_json = {
            "canConnect": True,
            "canPublish": True,
            "canFetchMetrics": True,
        }
        connection.last_error = last_error
        connection.last_connect_diagnostics_json = dict(diagnostics)
        connection.active_job_id = ""
        connection.active_job_type = ""
        connection.active_worker_id = ""
        connection.active_claimed_at = ""
        if status == "connected":
            connection.connected_at = current_time
        return connection

    return update_channel_connection(channel_id, mutate)


def _preserve_connected_or_error(
    config: AppConfig,
    *,
    channel_id: str,
    diagnostics: dict,
    last_error: str,
) -> ChannelConnection:
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
        connection.local_profile_path = str(persistent_profile_path(config))
        connection.last_error = last_error
        connection.last_connect_diagnostics_json = dict(diagnostics)
        connection.active_job_id = ""
        connection.active_job_type = ""
        connection.active_worker_id = ""
        connection.active_claimed_at = ""
        return connection

    return update_channel_connection(channel_id, mutate)


def _write_connect_log(
    *,
    channel_id: str,
    action_id: str,
    worker_id: str,
    status: str,
    last_step: str,
    diagnostics: dict,
    started_at: str = "",
    error_code: str = "",
    error_message: str = "",
) -> None:
    append_channel_job_log(
        ChannelJobLog(
            id=generate_id("log"),
            channel_id=channel_id,
            job_type="connect",
            job_id=action_id,
            status=status,
            last_step=last_step,
            started_at=started_at,
            finished_at=now_iso() if status != "running" else "",
            created_at=now_iso(),
            worker_id=worker_id,
            error_code=error_code,
            error_message=str({**diagnostics, "message": error_message} if error_message else diagnostics),
        )
    )


def normalize_connection_status(status: str) -> str:
    mapping = {
        "not_configured": "disconnected",
        "needs_login": "authentication_required",
        "connecting": "connecting",
        "connected": "connected",
        "error": "error",
        "disabled": "disconnected",
    }
    return mapping.get(status, status)


def browser_error_to_connection_status(error: Exception) -> str:
    if isinstance(error, BrowserProfileBusyError):
        return "error"
    if isinstance(error, BrowserUnavailableError):
        return "authentication_required"
    if isinstance(error, (PluginCapabilityError, PluginDependencyError)):
        return "error"
    return "error"


def safe_error_message(error: Exception) -> str:
    if isinstance(error, (BrowserProviderError, PluginCapabilityError, PluginDependencyError)):
        return error.user_message
    return str(error) or "Unexpected LinkedIn Connect error."


def run_connect_action(
    config: AppConfig,
    *,
    channel_id: str = "linkedin",
    action_id: str = "",
    worker_id: str = "",
    started_at: str = "",
) -> ChannelConnection | None:
    resolved_action_id = action_id or generate_id("connect")
    resolved_worker_id = worker_id or worker_id_for_channel(channel_id)
    diagnostics: dict[str, object] = {
        "action_id": resolved_action_id,
        "worker_id": resolved_worker_id,
        "browser_launch_count": 0,
        "navigation_count": 0,
        "requested_navigation_count": 0,
        "current_url_changes": [],
        "authentication_marker": "",
        "timeout_reason": "",
        "cancellation_reason": "",
    }
    claimed = claim_channel_connect(channel_id, action_id=resolved_action_id, worker_id=resolved_worker_id)
    if claimed is None:
        diagnostics["cancellation_reason"] = "connect_action_not_claimed"
        _write_connect_log(
            channel_id=channel_id,
            action_id=resolved_action_id,
            worker_id=resolved_worker_id,
            status="cancelled",
            last_step="claim_connect_action",
            diagnostics=diagnostics,
            started_at=started_at,
            error_code="connect_not_claimed",
            error_message="Connect action was already claimed, completed, or replaced.",
        )
        save_channel_worker_heartbeat(
            channel_id,
            status="idle",
            worker_id=resolved_worker_id,
            started_at=started_at,
        )
        return None

    save_channel_worker_heartbeat(
        channel_id,
        status="busy",
        current_job_id=resolved_action_id,
        current_job_type="connect",
        worker_id=resolved_worker_id,
        started_at=started_at,
    )
    _write_connect_log(
        channel_id=channel_id,
        action_id=resolved_action_id,
        worker_id=resolved_worker_id,
        status="running",
        last_step="claim_connect_action",
        diagnostics=diagnostics,
        started_at=started_at,
    )

    try:
        runtime = get_plugin_runtime(config, reset=True, strict=True)
        provider_runtime = runtime.resolve_provider("browser.session")
        browser_provider = provider_runtime.services["browser_provider"]
        diagnostics["browser_provider_id"] = provider_runtime.manifest.id
        profile_id = channel_id
        profile_status = browser_provider.profile_status(profile_id)
        diagnostics["profile_busy"] = profile_status.busy
        diagnostics["profile_lock_owner"] = profile_status.owner
        browser_session = browser_provider.create_session(
            BrowserSessionOptions(
                profile_id=profile_id,
                headless=False,
                exclusive=True,
                start_url="",
                metadata={"owner": f"{resolved_worker_id}:connect", "channel_id": channel_id},
            )
        )
        diagnostics["browser_launch_count"] = 1
        diagnostics["browser_session_id"] = browser_session.session_id
        diagnostics["browser_session_status"] = "active"
        page = getattr(browser_session, "page", None)
        if page is None:
            raise BrowserUnavailableError(
                "browser_session.page_unavailable",
                "Browser session did not expose a page for LinkedIn authentication checks.",
            )
        attach_navigation_observer(page, diagnostics)
        try:
            diagnostics["requested_navigation_count"] = int(diagnostics.get("requested_navigation_count", 0)) + 1
            browser_session.navigate(config.linkedin_feed_url)
            result = inspect_linkedin_auth_state(page, diagnostics=diagnostics)
            if not result["authenticated"]:
                takeover = browser_provider.request_human_takeover(
                    HumanTakeoverRequest(
                        session_id=browser_session.session_id,
                        reason="LinkedIn authentication is required.",
                        timeout_seconds=600,
                        metadata={"channel_id": channel_id, "action_id": resolved_action_id},
                    )
                )
                diagnostics["human_takeover_status"] = takeover.get("status", "requested")
                diagnostics["human_takeover_reference"] = takeover.get("takeover_reference", "")
                logged_in, reason = wait_for_manual_linkedin_login(page, diagnostics=diagnostics)
                if not logged_in:
                    diagnostics["human_takeover_status"] = "expired"
                    connection = _finalize_connect_state(
                        config,
                        channel_id=channel_id,
                        status="needs_login",
                        diagnostics=diagnostics,
                        last_error=reason,
                    )
                    save_channel_worker_heartbeat(
                        channel_id,
                        status="error",
                        current_job_id=resolved_action_id,
                        current_job_type="connect",
                        last_error=reason,
                        worker_id=resolved_worker_id,
                        started_at=started_at,
                    )
                    _write_connect_log(
                        channel_id=channel_id,
                        action_id=resolved_action_id,
                        worker_id=resolved_worker_id,
                        status="needs_login",
                        last_step="human_takeover_expired",
                        diagnostics=diagnostics,
                        started_at=started_at,
                        error_code="authentication_required",
                        error_message=reason,
                    )
                    return connection
                diagnostics["human_takeover_status"] = "completed"
            connection = _finalize_connect_state(
                config,
                channel_id=channel_id,
                status="connected",
                diagnostics=diagnostics,
            )
            save_channel_worker_heartbeat(
                channel_id,
                status="idle",
                worker_id=resolved_worker_id,
                started_at=started_at,
            )
            _write_connect_log(
                channel_id=channel_id,
                action_id=resolved_action_id,
                worker_id=resolved_worker_id,
                status="success",
                last_step="authenticated",
                diagnostics=diagnostics,
                started_at=started_at,
            )
            return connection
        finally:
            browser_session.close()
    except BrowserProfileBusyError as exc:
        connection = _preserve_connected_or_error(
            config,
            channel_id=channel_id,
            diagnostics=diagnostics,
            last_error=f"profile_busy: {exc}",
        )
        save_channel_worker_heartbeat(
            channel_id,
            status="error",
            current_job_id=resolved_action_id,
            current_job_type="connect",
            last_error=safe_error_message(exc),
            worker_id=resolved_worker_id,
            started_at=started_at,
        )
        _write_connect_log(
            channel_id=channel_id,
            action_id=resolved_action_id,
            worker_id=resolved_worker_id,
            status="failed",
            last_step="profile_lock",
            diagnostics=diagnostics,
            started_at=started_at,
            error_code="profile_busy",
            error_message=safe_error_message(exc),
        )
        return connection
    except (BrowserUnavailableError, PluginCapabilityError, PluginDependencyError) as exc:
        status = browser_error_to_connection_status(exc)
        connection = _finalize_connect_state(
            config,
            channel_id=channel_id,
            status="needs_login" if status == "authentication_required" else status,
            diagnostics=diagnostics,
            last_error=safe_error_message(exc),
        )
        save_channel_worker_heartbeat(
            channel_id,
            status="error",
            current_job_id=resolved_action_id,
            current_job_type="connect",
            last_error=safe_error_message(exc),
            worker_id=resolved_worker_id,
            started_at=started_at,
        )
        _write_connect_log(
            channel_id=channel_id,
            action_id=resolved_action_id,
            worker_id=resolved_worker_id,
            status="needs_login" if status == "authentication_required" else "failed",
            last_step="browser_provider",
            diagnostics=diagnostics,
            started_at=started_at,
            error_code=getattr(exc, "code", "provider_unavailable"),
            error_message=safe_error_message(exc),
        )
        return connection
    except Exception as exc:
        _preserve_connected_or_error(
            config,
            channel_id=channel_id,
            diagnostics=diagnostics,
            last_error=str(exc),
        )
        save_channel_worker_heartbeat(
            channel_id,
            status="error",
            current_job_id=resolved_action_id,
            current_job_type="connect",
            last_error=str(exc),
            worker_id=resolved_worker_id,
            started_at=started_at,
        )
        _write_connect_log(
            channel_id=channel_id,
            action_id=resolved_action_id,
            worker_id=resolved_worker_id,
            status="failed",
            last_step="connect_exception",
            diagnostics=diagnostics,
            started_at=started_at,
            error_code="connect_error",
            error_message=str(exc),
        )
        raise
