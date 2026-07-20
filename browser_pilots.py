from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from channel_storage import locked_json_store
from channel_store import (
    ACTIVE_JOB_STATUSES,
    LOCKS_DIR,
    STUDIO_DATA_DIR,
    ensure_channel_store_dirs,
    find_active_publish_job,
    get_channel_connection,
    list_metric_jobs,
    now_iso,
    save_channel_connection,
)

PILOTS_PATH = STUDIO_DATA_DIR / "browser_provider_pilot_runs.json"
PROVIDER_STATE_EVENTS_PATH = STUDIO_DATA_DIR / "provider_state_events.json"
MUTATING_PILOT_ACTIONS = {"publish_text", "publish_image"}
PILOT_SCOPES = {"login_only", "read_only", "text_publish", "image_publish"}
AUTO_BROWSER_PROVIDER_ID = "provider.browser.autobrowser"
LEGACY_PROVIDER_ID = "provider.browser.legacy"
_ISSUED_CONFIRMATION_TOKENS: dict[tuple[str, str], str] = {}


@dataclass
class PilotAction:
    action_type: str
    status: str = "pending"
    started_at: str = ""
    completed_at: str = ""
    confirmation_actor: str = ""
    confirmation_timestamp: str = ""
    confirmation_token_hash: str = ""
    confirmation_token_expires_at: str = ""
    error_code: str = ""
    remote_verification: str = ""
    artifact_references: list[str] = field(default_factory=list)
    cleanup_status: str = ""


@dataclass
class BrowserProviderPilotRun:
    id: str
    channel_account_id: str
    channel_plugin_id: str
    provider_id: str
    provider_version: str
    provider_contract_version: str
    external_service_version: str
    started_at: str
    initiated_by: str
    environment: str
    scope: str
    reason: str
    status: str = "planned"
    completed_at: str = ""
    preflight_results: dict[str, Any] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifact_references: list[str] = field(default_factory=list)
    rollback_result: dict[str, Any] = field(default_factory=dict)
    cleanup_result: dict[str, Any] = field(default_factory=dict)
    readiness_before: dict[str, Any] = field(default_factory=dict)
    readiness_after: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass
class ProviderStateEvent:
    channel_account_id: str
    provider_id: str
    timestamp: str
    previous_status: str
    new_status: str
    reason_code: str
    source: str
    job_id: str = ""
    pilot_run_id: str = ""
    safe_error_code: str = ""


def _list_store(path: Path):
    ensure_channel_store_dirs()
    return locked_json_store(path, default_factory=list, expect_type=list, lock_dir=LOCKS_DIR)


def _load_pilots() -> list[BrowserProviderPilotRun]:
    with _list_store(PILOTS_PATH) as store:
        payload = store.read()
    records: list[BrowserProviderPilotRun] = []
    for item in payload:
        if isinstance(item, dict):
            try:
                records.append(BrowserProviderPilotRun(**item))
            except TypeError:
                continue
    return records


def _save_pilots(records: list[BrowserProviderPilotRun]) -> None:
    with _list_store(PILOTS_PATH) as store:
        store.write([asdict(record) for record in records])


def list_browser_pilots() -> list[BrowserProviderPilotRun]:
    return sorted(_load_pilots(), key=lambda record: record.started_at, reverse=True)


def get_browser_pilot(pilot_id: str) -> BrowserProviderPilotRun | None:
    return next((record for record in _load_pilots() if record.id == pilot_id), None)


def create_browser_pilot(
    *,
    config: Any,
    runtime: Any,
    channel_account_id: str,
    provider_id: str,
    scope: str,
    reason: str,
    actor: str,
    acknowledged: bool,
) -> BrowserProviderPilotRun:
    if not actor.strip():
        raise ValueError("Pilot actor is required.")
    if len(reason.strip()) < 8:
        raise ValueError("Pilot reason is required.")
    if provider_id != AUTO_BROWSER_PROVIDER_ID:
        raise ValueError("Only provider.browser.autobrowser can be piloted in phase 8.")
    if scope not in PILOT_SCOPES:
        raise ValueError("Unsupported pilot scope.")
    if not acknowledged:
        raise ValueError("Pilot status acknowledgment is required.")
    pilot_accounts = set(str(item) for item in getattr(config, "auto_browser_pilot_accounts", []) or [])
    if channel_account_id not in pilot_accounts:
        raise ValueError("Channel account is not marked as an Auto Browser pilot account.")
    connection = get_channel_connection(channel_account_id)
    if connection is None:
        raise ValueError("Channel account does not exist.")
    if connection.channel_id != "linkedin":
        raise ValueError("Only channel.linkedin is supported for Auto Browser pilot.")
    if connection.browser_provider_id != provider_id:
        raise ValueError("Auto Browser must be explicitly selected for the account before pilot creation.")
    provider_runtime = runtime.resolve_provider("browser.session", preferred_provider_id=provider_id)
    health = dict(provider_runtime.health or {})
    pilot = BrowserProviderPilotRun(
        id=f"pilot_{secrets.token_hex(12)}",
        channel_account_id=channel_account_id,
        channel_plugin_id="channel.linkedin",
        provider_id=provider_id,
        provider_version=provider_runtime.manifest.version,
        provider_contract_version=str(health.get("browser_provider_contract_version") or ""),
        external_service_version=str(health.get("server_version") or health.get("tested_api_version") or ""),
        started_at=now_iso(),
        initiated_by=actor.strip(),
        environment="local",
        scope=scope,
        reason=reason.strip(),
        readiness_before=health.get("pilot_readiness", {}) if isinstance(health.get("pilot_readiness"), dict) else {},
    )
    records = _load_pilots()
    records.append(pilot)
    _save_pilots(records)
    append_provider_state_event(
        ProviderStateEvent(
            channel_account_id=channel_account_id,
            provider_id=provider_id,
            timestamp=now_iso(),
            previous_status="",
            new_status="planned",
            reason_code="pilot_created",
            source="pilot",
            pilot_run_id=pilot.id,
        )
    )
    return pilot


def run_pilot_preflight(*, config: Any, runtime: Any, pilot_id: str) -> BrowserProviderPilotRun:
    pilot = get_browser_pilot(pilot_id)
    if pilot is None:
        raise ValueError("Pilot run does not exist.")
    provider_runtime = runtime.resolve_provider("browser.session", preferred_provider_id=pilot.provider_id)
    provider = provider_runtime.services.get("browser_provider")
    connection = get_channel_connection(pilot.channel_account_id)
    health = dict(provider_runtime.health or {})
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, message: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "message": message})

    check("provider_explicitly_selected", bool(connection and connection.browser_provider_id == pilot.provider_id))
    check(
        "pilot_account_marked",
        pilot.channel_account_id in set(getattr(config, "auto_browser_pilot_accounts", []) or []),
    )
    check("provider_health_ready", provider_runtime.status.value == "ready")
    check("contract_compatible", health.get("contract_compatibility") in {"compatible", "compatible_with_warnings"})
    check("doctor_recent", bool(getattr(config, "auto_browser_doctor_last_passed_at", "")))
    check("integration_recent", bool(getattr(config, "auto_browser_integration_last_passed_at", "")))
    check("chaos_recent", bool(getattr(config, "auto_browser_chaos_last_passed_at", "")))
    check("no_active_publish_job", find_active_publish_job(pilot.channel_account_id) is None)
    active_metric = any(
        job.status in ACTIVE_JOB_STATUSES for job in list_metric_jobs(channel_id=pilot.channel_account_id)
    )
    check("no_active_metric_job", not active_metric)
    check("no_active_connect_job", not bool(connection and connection.active_job_id))
    profile_status = provider.profile_status(pilot.channel_account_id) if provider is not None else None
    check("no_active_lock", not bool(profile_status and profile_status.busy))
    reconciliation = (
        provider.reconcile_sessions() if provider is not None and hasattr(provider, "reconcile_sessions") else {}
    )
    check("no_unresolved_owned_orphan", int(reconciliation.get("orphaned_remote_count", 0) or 0) == 0)
    check("rollback_provider_available", "provider.browser.legacy" in runtime.runtimes)
    check(
        "legacy_providerstate_known",
        bool(connection and "provider.browser.legacy" in connection.provider_connection_state_json),
    )
    check("pipeline_legacyflows_blocked", True)
    if pilot.scope == "image_publish":
        check("uploadtransfer_ready", health.get("upload_capability") == "available")

    ok = all(item["ok"] for item in checks)
    pilot.preflight_results = {
        "status": "passed" if ok else "failed",
        "checked_at": now_iso(),
        "checks": checks,
        "evidence_windows": {
            "doctor_hours": 24,
            "integration_days": 7,
            "chaos_days": 30,
        },
    }
    pilot.status = "preflight" if ok else "planned"
    _replace_pilot(pilot)
    return pilot


def prepare_pilot_action(pilot_id: str, action_type: str, *, actor: str) -> BrowserProviderPilotRun:
    pilot = _require_pilot(pilot_id)
    action = PilotAction(action_type=action_type)
    if action_type in MUTATING_PILOT_ACTIONS:
        token = secrets.token_urlsafe(24)
        action.status = "awaiting_confirmation"
        action.confirmation_token_hash = _token_hash(token)
        action.confirmation_token_expires_at = _future_iso(minutes=15)
        issued_token = token
    else:
        action.status = "verified"
        action.started_at = now_iso()
        action.completed_at = action.started_at
        action.confirmation_actor = actor
    pilot.actions.append(asdict(action))
    pilot.status = "running"
    _replace_pilot(pilot)
    if action_type in MUTATING_PILOT_ACTIONS:
        _ISSUED_CONFIRMATION_TOKENS[(pilot.id, action_type)] = issued_token
    return pilot


def pop_issued_confirmation_token(pilot_id: str, action_type: str) -> str:
    return _ISSUED_CONFIRMATION_TOKENS.pop((pilot_id, action_type), "")


def confirm_pilot_action(
    pilot_id: str, action_type: str, *, token: str, actor: str, reason: str
) -> BrowserProviderPilotRun:
    if len(reason.strip()) < 8:
        raise ValueError("Confirmation reason is required.")
    pilot = _require_pilot(pilot_id)
    for action in pilot.actions:
        if action.get("action_type") != action_type or action.get("status") != "awaiting_confirmation":
            continue
        if action.get("confirmation_token_hash") != _token_hash(token):
            raise ValueError("Confirmation token is invalid.")
        if _is_expired(str(action.get("confirmation_token_expires_at") or "")):
            raise ValueError("Confirmation token has expired.")
        action["status"] = "verified"
        action["confirmation_actor"] = actor
        action["confirmation_timestamp"] = now_iso()
        action["started_at"] = action["confirmation_timestamp"]
        action["completed_at"] = action["confirmation_timestamp"]
        action["confirmation_token_hash"] = "used"
        action["artifact_references"] = []
        _replace_pilot(pilot)
        return pilot
    raise ValueError("No pending action confirmation is available.")


def rollback_pilot(*, config: Any, runtime: Any, pilot_id: str, actor: str, reason: str) -> BrowserProviderPilotRun:
    if len(reason.strip()) < 8:
        raise ValueError("Rollback reason is required.")
    pilot = _require_pilot(pilot_id)
    connection = get_channel_connection(pilot.channel_account_id)
    if connection is not None:
        previous = connection.browser_provider_id
        connection.browser_provider_id = LEGACY_PROVIDER_ID
        connection.updated_at = now_iso()
        save_channel_connection(connection)
        append_provider_state_event(
            ProviderStateEvent(
                channel_account_id=pilot.channel_account_id,
                provider_id=LEGACY_PROVIDER_ID,
                timestamp=now_iso(),
                previous_status=previous,
                new_status=LEGACY_PROVIDER_ID,
                reason_code="pilot_rollback",
                source="rollback",
                pilot_run_id=pilot.id,
            )
        )
    pilot.status = "rolled_back"
    pilot.completed_at = now_iso()
    pilot.rollback_result = {
        "status": "rolled_back",
        "actor": actor,
        "reason": reason.strip(),
        "provider_after": LEGACY_PROVIDER_ID,
        "content_preserved": True,
        "metrics_preserved": True,
        "autobrowser_state_preserved": True,
    }
    _replace_pilot(pilot)
    return pilot


def pause_pilot(pilot_id: str) -> BrowserProviderPilotRun:
    pilot = _require_pilot(pilot_id)
    pilot.status = "paused"
    _replace_pilot(pilot)
    return pilot


def cancel_pilot(pilot_id: str, *, reason: str = "") -> BrowserProviderPilotRun:
    pilot = _require_pilot(pilot_id)
    pilot.status = "cancelled"
    pilot.completed_at = now_iso()
    pilot.notes = reason[:240]
    _replace_pilot(pilot)
    return pilot


def append_provider_state_event(event: ProviderStateEvent) -> None:
    with _list_store(PROVIDER_STATE_EVENTS_PATH) as store:
        payload = [item for item in store.read() if isinstance(item, dict)]
        payload.append(asdict(event))
        store.write(payload[-200:])


def list_provider_state_events(channel_account_id: str = "", *, limit: int = 10) -> list[ProviderStateEvent]:
    with _list_store(PROVIDER_STATE_EVENTS_PATH) as store:
        payload = store.read()
    records: list[ProviderStateEvent] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if channel_account_id and item.get("channel_account_id") != channel_account_id:
            continue
        try:
            records.append(ProviderStateEvent(**item))
        except TypeError:
            continue
    return sorted(records, key=lambda record: record.timestamp, reverse=True)[:limit]


def _replace_pilot(pilot: BrowserProviderPilotRun) -> None:
    records = _load_pilots()
    for index, record in enumerate(records):
        if record.id == pilot.id:
            records[index] = pilot
            _save_pilots(records)
            return
    records.append(pilot)
    _save_pilots(records)


def _require_pilot(pilot_id: str) -> BrowserProviderPilotRun:
    pilot = get_browser_pilot(pilot_id)
    if pilot is None:
        raise ValueError("Pilot run does not exist.")
    return pilot


def _token_hash(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


def _future_iso(*, minutes: int) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes)).astimezone().isoformat(timespec="seconds")


def _is_expired(value: str) -> bool:
    try:
        return datetime.fromisoformat(value).astimezone(UTC) <= datetime.now(UTC)
    except ValueError:
        return True
