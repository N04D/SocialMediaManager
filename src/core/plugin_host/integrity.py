"""Read-only integrity scans for plugin host state."""

from __future__ import annotations

import json
from pathlib import Path

from .models import PluginHostIntegrityFinding


class PluginHostIntegrityService:
    def __init__(self, install_root: str | Path, environment_root: str | Path, host_state_root: str | Path) -> None:
        self.install_root = Path(install_root)
        self.environment_root = Path(environment_root)
        self.host_state_root = Path(host_state_root)

    def scan(self) -> list[PluginHostIntegrityFinding]:
        findings: list[PluginHostIntegrityFinding] = []
        findings.extend(self.scan_environments())
        findings.extend(self.scan_active_pointers())
        return findings

    def scan_environments(self) -> list[PluginHostIntegrityFinding]:
        findings: list[PluginHostIntegrityFinding] = []
        if not self.environment_root.exists():
            return findings
        for env_file in self.environment_root.glob("*/*/host-environment.json"):
            payload = json.loads(env_file.read_text())
            plugin_id = str(payload.get("plugin_id") or "")
            version = str(payload.get("plugin_version") or "")
            if not (self.install_root / plugin_id / "installs" / version).exists():
                findings.append(
                    PluginHostIntegrityFinding(
                        "plugin_host.integrity.environment_without_install",
                        "high",
                        plugin_id=plugin_id,
                        plugin_version=version,
                        safe_message="Plugin host environment exists without installed code.",
                    )
                )
            if payload.get("system_site_packages") is not False:
                findings.append(
                    PluginHostIntegrityFinding(
                        "plugin_host.integrity.system_site_enabled",
                        "critical",
                        plugin_id=plugin_id,
                        plugin_version=version,
                        safe_message="Plugin host environment has system site packages enabled.",
                    )
                )
        return findings

    def scan_active_pointers(self) -> list[PluginHostIntegrityFinding]:
        findings: list[PluginHostIntegrityFinding] = []
        for active in self.install_root.glob("*/active.json"):
            payload = json.loads(active.read_text())
            plugin_id = str(payload.get("plugin_id") or active.parent.name)
            version = str(payload.get("plugin_version") or "")
            if not (self.environment_root / plugin_id / version / "host-environment.json").exists():
                findings.append(
                    PluginHostIntegrityFinding(
                        "plugin_host.integrity.active_without_environment",
                        "high",
                        plugin_id=plugin_id,
                        plugin_version=version,
                        safe_message="Active external plugin is missing a prepared host environment.",
                    )
                )
        return findings


__all__ = ["PluginHostIntegrityService"]
