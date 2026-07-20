from __future__ import annotations

from channel_models import ChannelConnection
from channel_store import now_iso


def record_provider_connection_state(
    connection: ChannelConnection,
    *,
    provider_id: str,
    status: str,
    auth_profile_reference: str = "",
    error_code: str = "",
) -> ChannelConnection:
    states = dict(connection.provider_connection_state_json or {})
    states[provider_id] = {
        "provider_id": provider_id,
        "status": status,
        "auth_profile_reference": auth_profile_reference,
        "last_verified_at": now_iso(),
        "last_error_code": error_code,
    }
    connection.provider_connection_state_json = states
    return connection


def provider_connection_status(connection: ChannelConnection, provider_id: str) -> str:
    state = dict(connection.provider_connection_state_json or {}).get(provider_id)
    if not isinstance(state, dict):
        return ""
    return str(state.get("status") or "")


def set_provider_connection_status(
    connection: ChannelConnection,
    *,
    provider_id: str,
    status: str,
    error_code: str = "",
    source: str = "session_check",
    job_id: str = "",
    pilot_run_id: str = "",
) -> ChannelConnection:
    states = dict(connection.provider_connection_state_json or {})
    current = dict(states.get(provider_id) or {})
    previous_status = str(current.get("status") or "")
    current.update(
        {
            "provider_id": provider_id,
            "status": status,
            "last_verified_at": now_iso(),
            "last_error_code": error_code,
        }
    )
    states[provider_id] = current
    connection.provider_connection_state_json = states
    if previous_status != status:
        try:
            from browser_pilots import ProviderStateEvent, append_provider_state_event

            append_provider_state_event(
                ProviderStateEvent(
                    channel_account_id=connection.channel_id,
                    provider_id=provider_id,
                    timestamp=now_iso(),
                    previous_status=previous_status,
                    new_status=status,
                    reason_code=error_code or status,
                    source=source,
                    job_id=job_id,
                    pilot_run_id=pilot_run_id,
                    safe_error_code=error_code,
                )
            )
        except Exception:
            pass
    return connection
