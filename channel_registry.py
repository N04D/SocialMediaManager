from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from channel_store import ensure_channel_connection, get_channel_connection, worker_status_from_heartbeat


ROOT_DIR = Path(__file__).resolve().parent
CHANNELS_DIR = ROOT_DIR / "channels"
ALLOWED_PLUGIN_MODES = {"playwright_local", "placeholder"}
ALLOWED_PLUGIN_STATUSES = {"experimental", "alpha", "beta", "stable", "planned"}
ALLOWED_METRICS_MODES = {"playwright_local_snapshot", "none"}
ALLOWED_HEALTH_STATES = {
    "ready",
    "not_configured",
    "invalid_manifest",
    "missing_files",
    "worker_missing",
    "error",
    "disabled",
}


@dataclass
class ChannelRegistryEntry:
    id: str
    manifest: dict[str, Any]
    plugin_dir: Path
    health: str
    errors: list[str] = field(default_factory=list)
    connection_status: str = "not_configured"
    last_checked_at: str = ""
    last_error: str = ""
    connected_at: str = ""
    mode: str = ""
    local_profile_path: str = ""
    worker_status: str = "offline"
    worker_last_seen_at: str = ""
    worker_last_error: str = ""
    worker_current_job_id: str = ""
    worker_current_job_type: str = ""
    worker_process_id: int = 0
    worker_started_at: str = ""
    worker_is_stale: bool = False
    profile_busy: bool = False
    profile_lock_owner: str = ""
    profile_lock_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "manifest": self.manifest,
            "plugin_dir": str(self.plugin_dir),
            "health": self.health,
            "errors": self.errors,
            "connection_status": self.connection_status,
            "last_checked_at": self.last_checked_at,
            "last_error": self.last_error,
            "connected_at": self.connected_at,
            "mode": self.mode,
            "local_profile_path": self.local_profile_path,
            "worker_status": self.worker_status,
            "worker_last_seen_at": self.worker_last_seen_at,
            "worker_last_error": self.worker_last_error,
            "worker_current_job_id": self.worker_current_job_id,
            "worker_current_job_type": self.worker_current_job_type,
            "worker_process_id": self.worker_process_id,
            "worker_started_at": self.worker_started_at,
            "worker_is_stale": self.worker_is_stale,
            "profile_busy": self.profile_busy,
            "profile_lock_owner": self.profile_lock_owner,
            "profile_lock_path": self.profile_lock_path,
        }



def _load_manifest(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None



def _validate_bool_map(name: str, payload: Any, required_keys: list[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [f"{name} must be an object."]
    for key in required_keys:
        if key not in payload:
            errors.append(f"{name}.{key} is required.")
        elif not isinstance(payload[key], bool):
            errors.append(f"{name}.{key} must be a boolean.")
    return errors



def validate_channel_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_string_fields = ["id", "name", "version", "description", "status", "mode"]
    for field_name in required_string_fields:
        value = manifest.get(field_name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field_name} is required.")

    if not errors:
        if manifest["mode"] not in ALLOWED_PLUGIN_MODES:
            errors.append(f"mode must be one of {sorted(ALLOWED_PLUGIN_MODES)}.")
        if manifest["status"] not in ALLOWED_PLUGIN_STATUSES:
            errors.append(f"status must be one of {sorted(ALLOWED_PLUGIN_STATUSES)}.")

    errors.extend(
        _validate_bool_map(
            "capabilities",
            manifest.get("capabilities"),
            [
                "canGenerate",
                "canPreview",
                "canPublish",
                "canFetchMetrics",
                "canReadComments",
                "requiresApproval",
            ],
        )
    )
    errors.extend(
        _validate_bool_map(
            "connection",
            manifest.get("connection"),
            ["canConnect", "canDisconnect", "canCheckStatus"],
        )
    )

    output_types = manifest.get("outputTypes")
    if not isinstance(output_types, list) or not output_types:
        errors.append("outputTypes must be a non-empty list.")
    else:
        for item in output_types:
            if not isinstance(item, str) or not item.strip():
                errors.append("outputTypes entries must be non-empty strings.")

    metrics = manifest.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("metrics must be an object.")
    else:
        metrics_mode = metrics.get("mode")
        if not isinstance(metrics_mode, str) or metrics_mode not in ALLOWED_METRICS_MODES:
            errors.append(f"metrics.mode must be one of {sorted(ALLOWED_METRICS_MODES)}.")
        for key in ["supportsManualRefresh", "supportsScheduledRefresh"]:
            if not isinstance(metrics.get(key), bool):
                errors.append(f"metrics.{key} must be a boolean.")
        refresh_windows = metrics.get("defaultRefreshWindows", [])
        if not isinstance(refresh_windows, list):
            errors.append("metrics.defaultRefreshWindows must be a list.")
        else:
            for window in refresh_windows:
                if not isinstance(window, str):
                    errors.append("metrics.defaultRefreshWindows entries must be strings.")

    return errors



def _plugin_health(manifest: dict[str, Any], plugin_dir: Path, errors: list[str]) -> tuple[str, list[str]]:
    if errors:
        return "invalid_manifest", errors

    required_paths: list[Path] = [plugin_dir / "README.md"]
    capabilities = manifest.get("capabilities", {})
    if capabilities.get("canGenerate"):
        required_paths.extend([plugin_dir / "rules.yaml", plugin_dir / "prompts"])
    if any(capabilities.get(key) for key in ["canPublish", "canFetchMetrics"]) or manifest.get("connection", {}).get("canConnect"):
        worker_index = plugin_dir / "worker" / "index.py"
        if not worker_index.exists():
            return "worker_missing", ["worker/index.py is required for this plugin."]
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        return "missing_files", [f"Missing required plugin file or directory: {path.name}" for path in missing]
    return "ready", []



def _default_connection_status(manifest: dict[str, Any]) -> str:
    if not manifest.get("connection", {}).get("canConnect"):
        return "disabled"
    return "not_configured"



def _profile_state(entry_id: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(f"channels.{entry_id}.worker.browser")
    except Exception:
        return {"busy": False, "owner": "", "lock_path": ""}
    state_fn = getattr(module, "profile_lock_state", None)
    if not callable(state_fn):
        return {"busy": False, "owner": "", "lock_path": ""}
    try:
        return dict(state_fn(entry_id))
    except Exception:
        return {"busy": False, "owner": "", "lock_path": ""}



def scan_channel_registry(*, rescan: bool = False) -> list[ChannelRegistryEntry]:
    entries: list[ChannelRegistryEntry] = []
    if not CHANNELS_DIR.exists():
        return entries

    seen_ids: dict[str, ChannelRegistryEntry] = {}
    for plugin_dir in sorted(path for path in CHANNELS_DIR.iterdir() if path.is_dir()):
        manifest_path = plugin_dir / "channel.manifest.json"
        if not manifest_path.exists():
            continue
        manifest = _load_manifest(manifest_path)
        if manifest is None:
            entry = ChannelRegistryEntry(
                id=plugin_dir.name,
                manifest={},
                plugin_dir=plugin_dir,
                health="invalid_manifest",
                errors=["channel.manifest.json could not be parsed."],
            )
            entries.append(entry)
            continue

        manifest_errors = validate_channel_manifest(manifest)
        health, health_errors = _plugin_health(manifest, plugin_dir, manifest_errors)
        entry = ChannelRegistryEntry(
            id=str(manifest.get("id") or plugin_dir.name),
            manifest=manifest,
            plugin_dir=plugin_dir,
            health=health,
            errors=health_errors,
            mode=str(manifest.get("mode") or ""),
        )
        if entry.id in seen_ids:
            duplicate_error = f"Duplicate plugin id '{entry.id}' detected."
            entry.health = "invalid_manifest"
            entry.errors.append(duplicate_error)
            seen_ids[entry.id].health = "invalid_manifest"
            seen_ids[entry.id].errors.append(duplicate_error)
        else:
            seen_ids[entry.id] = entry

        if entry.health in ALLOWED_HEALTH_STATES and entry.health != "invalid_manifest":
            connection = get_channel_connection(entry.id)
            if connection is None:
                ensure_channel_connection(
                    entry.id,
                    mode=entry.mode or str(manifest.get("mode") or ""),
                    status=_default_connection_status(manifest),
                    local_profile_path="",
                    capabilities_snapshot_json=dict(manifest.get("capabilities") or {}),
                )
                connection = get_channel_connection(entry.id)
            if connection is not None:
                entry.connection_status = connection.status
                entry.last_checked_at = connection.last_checked_at
                entry.last_error = connection.last_error
                entry.connected_at = connection.connected_at
                entry.local_profile_path = connection.local_profile_path
                entry.mode = connection.mode or entry.mode

            worker_status, heartbeat = worker_status_from_heartbeat(entry.id)
            entry.worker_status = worker_status
            if heartbeat is not None:
                entry.worker_last_seen_at = heartbeat.last_seen_at
                entry.worker_last_error = heartbeat.last_error
                entry.worker_current_job_id = heartbeat.current_job_id
                entry.worker_current_job_type = heartbeat.current_job_type
                entry.worker_process_id = heartbeat.process_id
                entry.worker_started_at = heartbeat.started_at
                entry.worker_is_stale = worker_status == "offline" and bool(heartbeat.last_seen_at)

            profile_state = _profile_state(entry.id)
            entry.profile_busy = bool(profile_state.get("busy"))
            entry.profile_lock_owner = str(profile_state.get("owner") or "")
            entry.profile_lock_path = str(profile_state.get("lock_path") or "")
        entries.append(entry)

    return sorted(entries, key=lambda item: item.manifest.get("name", item.id).lower())



def get_channel_registry_entry(channel_id: str) -> ChannelRegistryEntry | None:
    for entry in scan_channel_registry():
        if entry.id == channel_id:
            return entry
    return None
