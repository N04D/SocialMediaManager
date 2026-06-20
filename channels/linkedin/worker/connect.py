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

from .browser import ProfileBusyError, RemoteBrowserUnavailableError, linkedin_profile_lock, open_local_linkedin_session, persistent_profile_path
from .runtime import save_channel_worker_heartbeat, worker_id_for_channel
from .session import (
    attach_navigation_observer,
    inspect_linkedin_auth_state,
    navigate_linkedin_once,
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
        with linkedin_profile_lock(channel_id, owner=f"{resolved_worker_id}:connect"):
            playwright, browser, context, page, owns_session, session_label = open_local_linkedin_session(
                config,
                headed_default=True,
                allow_remote_debugging=True,
                require_remote_debugging=True,
            )
            diagnostics["browser_launch_count"] = 1
            attach_navigation_observer(page, diagnostics)
            try:
                navigate_linkedin_once(page, config.linkedin_feed_url, diagnostics=diagnostics)
                result = inspect_linkedin_auth_state(page, diagnostics=diagnostics)
                if not result["authenticated"]:
                    logged_in, reason = wait_for_manual_linkedin_login(page, diagnostics=diagnostics)
                    if not logged_in:
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
                            last_step="manual_login_timeout",
                            diagnostics=diagnostics,
                            started_at=started_at,
                            error_code="needs_login",
                            error_message=reason,
                        )
                        return connection
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
                if owns_session:
                    context.close()
                playwright.stop()
    except ProfileBusyError as exc:
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
            last_error=str(exc),
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
            error_message=str(exc),
        )
        return connection
    except RemoteBrowserUnavailableError as exc:
        connection = _finalize_connect_state(
            config,
            channel_id=channel_id,
            status="needs_login",
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
            status="needs_login",
            last_step="remote_browser_unavailable",
            diagnostics=diagnostics,
            started_at=started_at,
            error_code="remote_browser_unavailable",
            error_message=str(exc),
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
