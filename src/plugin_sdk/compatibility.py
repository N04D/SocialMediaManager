"""Plugin SDK compatibility reports and security scanners."""

from __future__ import annotations

import importlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .capabilities import RESERVED_FUTURE_CHANNEL_CAPABILITIES
from .contracts import (
    CHANNEL_PLUGIN_SDK_CONTRACT_VERSION,
    PLUGIN_MANIFEST_SCHEMA_VERSION,
    PLUGIN_SDK_VERSION,
)
from .errors import PluginCompatibilityError, PluginManifestValidationError
from .manifest import PluginManifest, validate_manifest

FORBIDDEN_IMPORT_PATTERNS = {
    "dashboard": r"\b(import|from)\s+dashboard\b",
    "worker": r"\b(import|from)\s+worker\b",
    "other_channel": r"\bfrom\s+channels\.(linkedin|mastodon|instagram|x|substack|blog)\b",
    "concrete_browser_provider": r"AutoBrowserProvider|LegacyBrowserProvider|\b(import|from)\s+playwright\b",
    "concrete_media_provider": r"LocalMediaStorageProvider|src\.core\.media\.fake_provider",
    "content_repository": r"content_store|ContentRepository",
    "media_repository": r"\b(import|from)\s+media_store\b|src\.core\.media\..*repository",
    "analytics_repository": r"AnalyticsRepository|analytics_store",
    "execution_repository": r"ExecutionRepository|execution_store",
    "scheduling_repository": r"SchedulingRepository|scheduler\b",
}
SECRET_PATTERNS = {
    "access_token": r"access[_-]?token\s*[:=]\s*['\"][A-Za-z0-9._~+/=-]{20,}",
    "client_secret": r"client[_-]?secret\s*[:=]\s*['\"][A-Za-z0-9._~+/=-]{16,}",
    "password": r"password\s*[:=]\s*['\"][^'\"]{8,}",
    "bearer": r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}",
    "private_key": r"BEGIN [A-Z ]*PRIVATE KEY",
    "cookie": r"cookie\s*[:=]\s*['\"][^'\"]{12,}",
}


@dataclass(frozen=True)
class PluginCompatibilityReport:
    """Machine-readable compatibility report."""

    plugin_id: str
    plugin_version: str
    sdk_version: str = PLUGIN_SDK_VERSION
    manifest_schema_version: str = PLUGIN_MANIFEST_SCHEMA_VERSION
    declared_contract_versions: dict[str, str] = field(default_factory=dict)
    required_contract_versions: dict[str, str] = field(
        default_factory=lambda: {"channel": CHANNEL_PLUGIN_SDK_CONTRACT_VERSION}
    )
    compatible: bool = False
    compatibility_status: str = "unverified"
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    permissions: tuple[str, ...] = field(default_factory=tuple)
    distribution: str = "community"
    passed_contract_suites: tuple[str, ...] = field(default_factory=tuple)
    failed_contract_suites: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    forbidden_imports: tuple[str, ...] = field(default_factory=tuple)
    secret_findings: tuple[str, ...] = field(default_factory=tuple)
    fixture_status: str = "unverified"
    doctor_status: str = "unverified"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def find_manifest_path(plugin_path: str | Path) -> Path:
    path = Path(plugin_path)
    if path.is_file():
        return path
    candidates = [path / "plugin.manifest.json", path / "channel.manifest.json"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise PluginCompatibilityError("plugin_sdk.manifest_missing", "No plugin manifest found.")


def scan_forbidden_imports(root: str | Path, *, allow: set[str] | None = None) -> list[str]:
    """Read-only scanner for imports outside the public SDK boundary."""

    allow = allow or set()
    path = Path(root)
    files = [path] if path.is_file() else list(path.rglob("*.py"))
    findings: list[str] = []
    own_channel_module = ""
    try:
        manifest = PluginManifest.from_path(find_manifest_path(path))
        if manifest.id.startswith("channel."):
            own_channel_module = "channels." + manifest.id.removeprefix("channel.")
    except Exception:
        own_channel_module = ""
    for file_path in files:
        if any(part.startswith(".") or part == "__pycache__" for part in file_path.parts):
            continue
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        for code, pattern in FORBIDDEN_IMPORT_PATTERNS.items():
            if code in allow:
                continue
            if code == "other_channel" and own_channel_module and own_channel_module in text:
                text_for_pattern = text.replace(own_channel_module, "channels.__self__")
            else:
                text_for_pattern = text
            if re.search(pattern, text_for_pattern):
                findings.append(f"{code}:{file_path.name}")
    return sorted(set(findings))


def scan_secrets(root: str | Path) -> list[str]:
    """Read-only scanner for committed credentials in plugin source."""

    path = Path(root)
    if path.is_file():
        files = [path]
    else:
        files = [
            p for p in path.rglob("*") if p.is_file() and p.suffix in {".py", ".json", ".md", ".yaml", ".yml", ".env"}
        ]
    findings: list[str] = []
    for file_path in files:
        if file_path.name == ".env":
            findings.append(f"env_file:{file_path.name}")
            continue
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        sanitized = text.replace("fixture-access-token", "fixture-token").replace(
            "example-client-secret", "fixture-secret"
        )
        for code, pattern in SECRET_PATTERNS.items():
            if re.search(pattern, sanitized, flags=re.IGNORECASE):
                findings.append(f"{code}:{file_path.name}")
    return sorted(set(findings))


def inspect_plugin(plugin_path: str | Path) -> dict[str, Any]:
    manifest = PluginManifest.from_path(find_manifest_path(plugin_path))
    warnings = validate_manifest(manifest)
    profiles = ["channel.minimal"]
    if "channel.publish.text" in manifest.capabilities:
        profiles.append("channel.text_publish")
    if "channel.publish.image" in manifest.capabilities:
        profiles.append("channel.image_publish")
    if "channel.metrics.collect" in manifest.capabilities:
        profiles.append("channel.metrics")
    if "browser_session" in manifest.permissions:
        profiles.append("channel.browser_based")
    elif "outbound_network" in manifest.permissions:
        profiles.append("channel.api_first")
    return {
        "plugin_id": manifest.id,
        "version": manifest.version,
        "type": manifest.plugin_type,
        "sdk_version": manifest.sdk_contract_version or "legacy",
        "framework_contracts": manifest.framework_contract_versions,
        "capabilities": list(manifest.capabilities),
        "permissions": list(manifest.permissions),
        "entrypoint": manifest.entrypoint,
        "test_profile": profiles,
        "warnings": warnings,
    }


def package_check(plugin_path: str | Path) -> list[str]:
    """Check package readiness without installing or downloading dependencies."""

    root = Path(plugin_path)
    warnings: list[str] = []
    manifest = PluginManifest.from_path(find_manifest_path(root))
    if root.is_dir():
        for required in ("README.md", "CHANGELOG.md"):
            if not (root / required).exists():
                warnings.append(f"{required.lower()}_missing")
    if not manifest.license:
        warnings.append("license_missing")
    if not manifest.documentation:
        warnings.append("documentation_missing")
    return warnings


def build_compatibility_report(plugin_path: str | Path) -> PluginCompatibilityReport:
    root = Path(plugin_path)
    warnings: list[str] = []
    failed: list[str] = []
    passed: list[str] = []
    try:
        manifest_path = find_manifest_path(root)
        manifest = PluginManifest.from_path(manifest_path)
        warnings.extend(validate_manifest(manifest))
    except (PluginManifestValidationError, PluginCompatibilityError) as exc:
        return PluginCompatibilityReport(
            plugin_id="unknown",
            plugin_version="0.0.0",
            compatible=False,
            compatibility_status="invalid",
            warnings=(exc.code,),
            failed_contract_suites=("manifest",),
        )
    forbidden = scan_forbidden_imports(root)
    secret_findings = scan_secrets(root)
    if any(cap in RESERVED_FUTURE_CHANNEL_CAPABILITIES for cap in manifest.capabilities):
        failed.append("reserved_capability")
    if forbidden:
        failed.append("boundary")
    else:
        passed.append("boundary")
    if secret_findings:
        failed.append("secrets")
    else:
        passed.append("secrets")
    passed.append("manifest")
    if manifest.plugin_type == "channel":
        passed.append("channel.minimal")
        if "channel.publish.text" in manifest.capabilities:
            passed.append("channel.text_publish")
        if "channel.publish.image" in manifest.capabilities:
            passed.append("channel.image_publish")
        if "channel.metrics.collect" in manifest.capabilities:
            passed.append("channel.metrics")
    inserted: list[str] = []
    try:
        if root.is_dir():
            for candidate in (root / "src", root):
                if candidate.exists():
                    value = str(candidate.resolve())
                    if value not in sys.path:
                        sys.path.insert(0, value)
                        inserted.append(value)
        if manifest.entrypoint:
            importlib.import_module(manifest.entrypoint)
            passed.append("entrypoint")
    except Exception:
        warnings.append("entrypoint_import_unverified")
    finally:
        for value in inserted:
            try:
                sys.path.remove(value)
            except ValueError:
                pass
    fixture_status = "present" if (root / "fixture.py").exists() or list(root.rglob("fixture*.py")) else "unverified"
    doctor_status = "present" if (root / "doctor.py").exists() or list(root.rglob("doctor.py")) else "unverified"
    status = (
        "compatible" if not failed and not warnings else "compatible_with_warnings" if not failed else "incompatible"
    )
    return PluginCompatibilityReport(
        plugin_id=manifest.id,
        plugin_version=manifest.version,
        declared_contract_versions=manifest.framework_contract_versions,
        compatible=not failed,
        compatibility_status=status,
        capabilities=manifest.capabilities,
        permissions=manifest.permissions,
        distribution=manifest.distribution,
        passed_contract_suites=tuple(passed),
        failed_contract_suites=tuple(failed),
        warnings=tuple(sorted(set(warnings))),
        forbidden_imports=tuple(forbidden),
        secret_findings=tuple(secret_findings),
        fixture_status=fixture_status,
        doctor_status=doctor_status,
    )


def render_report(report: PluginCompatibilityReport) -> str:
    status = "PASS" if report.compatible else "FAIL"
    lines = [f"{status} {report.plugin_id} {report.plugin_version} ({report.compatibility_status})"]
    lines.append("capabilities: " + ", ".join(report.capabilities))
    lines.append("permissions: " + ", ".join(report.permissions))
    if report.warnings:
        lines.append("warnings: " + ", ".join(report.warnings))
    if report.forbidden_imports:
        lines.append("forbidden_imports: " + ", ".join(report.forbidden_imports))
    if report.secret_findings:
        lines.append("secret_findings: " + ", ".join(report.secret_findings))
    return "\n".join(lines)


__all__ = [
    "PluginCompatibilityReport",
    "build_compatibility_report",
    "find_manifest_path",
    "inspect_plugin",
    "package_check",
    "render_report",
    "scan_forbidden_imports",
    "scan_secrets",
]
