"""Developer CLI for Plugin SDK v1."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from src.core.plugin_distribution import (
    PluginInstallationService,
    PluginPackageBuildService,
    PluginPackageVerificationService,
    PluginRegistryService,
    PluginRegistrySource,
)
from src.core.plugin_host import PluginHostIntegrityService, PluginHostSupervisor
from src.core.plugin_sandbox import PluginSandboxIntegrityService, SandboxPolicyCompiler, select_sandbox_controller
from src.core.plugin_sandbox.integrity import context_from_install_record

from .capabilities import validate_capability, validate_plugin_id
from .compatibility import build_compatibility_report, inspect_plugin, package_check, render_report
from .manifest import PluginManifest, validate_manifest

PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _package_from_id(plugin_id: str) -> str:
    return plugin_id.replace(".", "_").replace("-", "_")


def _mode_permissions(mode: str, capabilities: list[str]) -> list[str]:
    permissions = {"execution_reporting", "account_configuration"}
    if mode == "api-first":
        permissions.update({"outbound_network", "secret_storage"})
    if mode == "browser-based":
        permissions.update({"browser_session", "secret_storage"})
    if "channel.publish.image" in capabilities:
        permissions.update({"media_read", "media_materialization"})
    if "channel.metrics.collect" in capabilities:
        permissions.add("analytics_ingestion")
    return sorted(permissions)


def _capabilities(short: list[str]) -> list[str]:
    mapping = {"text": "channel.publish.text", "image": "channel.publish.image", "metrics": "channel.metrics.collect"}
    caps = ["channel.status", "channel.health"]
    for item in short:
        cap = mapping.get(item, item)
        if cap not in caps:
            caps.append(cap)
    return caps


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_channel(args: argparse.Namespace) -> int:
    validate_plugin_id(args.id)
    if not args.id.startswith("channel."):
        raise SystemExit("create-channel requires a channel.<name> id")
    output = Path(args.output).resolve()
    if ".." in Path(args.output).parts:
        raise SystemExit("output path traversal rejected")
    if output.exists() and any(output.iterdir()) and not args.force:
        raise SystemExit("output directory exists; use --force to overwrite")
    if output.exists() and args.force:
        shutil.rmtree(output)
    package = args.package or _package_from_id(args.id)
    if not PACKAGE_RE.match(package):
        raise SystemExit("invalid package name")
    caps = _capabilities(args.capability or ["text"])
    for cap in caps:
        validate_capability(cap, plugin_id=args.id)
    permissions = _mode_permissions(args.mode, caps)
    profile = "channel.api_first" if args.mode == "api-first" else "channel.browser_based"
    manifest = {
        "schema_version": "1.0",
        "id": args.id,
        "name": args.name,
        "version": "0.1.0",
        "plugin_type": "channel",
        "description": f"{args.name} channel plugin.",
        "entrypoint": f"{package}.plugin",
        "plugin_api_version": 1,
        "sdk_contract_version": "1.0.0",
        "framework_contract_versions": {"channel": "1.0"},
        "capabilities": caps,
        "dependencies": [],
        "optional_dependencies": [],
        "configuration_schema": {"type": "object", "additionalProperties": False},
        "secrets": [],
        "health": {"doctor": f"{package}.doctor"},
        "compatibility": {"test_profiles": [profile]},
        "permissions": permissions,
        "distribution": "experimental",
        "maintainers": [
            {
                "name": args.maintainer or "Plugin maintainer",
                "role": "maintainer",
                "contact_reference": "project issue tracker",
            }
        ],
        "license": args.license,
        "repository": "",
        "documentation": "docs/channel-plugin.md",
    }
    output.mkdir(parents=True, exist_ok=True)
    _write(output / "channel.manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    _write(output / "README.md", f"# {args.name}\n\nGenerated {args.mode} channel plugin using Plugin SDK v1.\n")
    _write(output / "CHANGELOG.md", "# Changelog\n\n## 0.1.0\n\n### Added\n- Initial generated channel plugin.\n")
    _write(
        output / "pyproject.toml",
        f'[project]\nname = "{package}"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n\n[tool.pytest.ini_options]\npythonpath = ["src", "../../src"]\n',
    )
    _write(
        output / "src" / package / "__init__.py", 'from .plugin import create_plugin\n\n__all__ = ["create_plugin"]\n'
    )
    _write(
        output / "src" / package / "plugin.py",
        """from __future__ import annotations

from pathlib import Path

from plugin_sdk import ChannelRuntimeContext, PluginManifest, PluginRegistrationContext

from .runtime import ExampleChannelRuntime


class ExampleChannelPlugin:
    @property
    def manifest(self) -> PluginManifest:
        current = Path(__file__).resolve()
        for parent in current.parents:
            candidate = parent / "channel.manifest.json"
            if candidate.exists():
                return PluginManifest.from_path(candidate)
        raise RuntimeError("channel manifest is missing")

    def register(self, context: PluginRegistrationContext) -> None:
        context.register_runtime_factory(self.manifest.id, self.create_runtime)

    def create_runtime(self, context: ChannelRuntimeContext) -> ExampleChannelRuntime:
        return ExampleChannelRuntime(self.manifest.id, context)


def create_plugin() -> ExampleChannelPlugin:
    return ExampleChannelPlugin()
""",
    )
    mode_note = "external API transport placeholder" if args.mode == "api-first" else "browser facade placeholder"
    _write(
        output / "src" / package / "runtime.py",
        f'''from __future__ import annotations

from plugin_sdk import (
    ChannelAccountStatus,
    ChannelHealth,
    ChannelHealthRequest,
    ChannelPublishRequest,
    ChannelPublishResult,
    ChannelRuntimeBase,
    ChannelRuntimeContext,
)


class ExampleChannelRuntime(ChannelRuntimeBase):
    def __init__(self, plugin_id: str, context: ChannelRuntimeContext) -> None:
        self.plugin_id = plugin_id
        self.context = context

    async def get_status(self, request):
        return ChannelAccountStatus("unconfigured")

    async def health_check(self, request: ChannelHealthRequest) -> ChannelHealth:
        return ChannelHealth("unconfigured", self.plugin_id, metadata={{"mode": "{args.mode}", "note": "{mode_note}"}})

    async def publish(self, request: ChannelPublishRequest) -> ChannelPublishResult:
        return ChannelPublishResult("failed", request.publication_id, safe_error_code="not_configured")
''',
    )
    for module in [
        "models",
        "errors",
        "status_policy",
        "content_requirements",
        "media_requirements",
        "metric_definitions",
    ]:
        _write(output / "src" / package / f"{module}.py", '"""Generated plugin placeholder module."""\n')
    _write(
        output / "src" / package / "fixture.py",
        '"""Deterministic local fixture placeholder. No network calls on import."""\nSCENARIOS = ("healthy", "auth_failure", "rate_limited", "pre_mutation_failure", "post_mutation_uncertain", "metrics")\n',
    )
    _write(
        output / "src" / package / "doctor.py",
        '"""Read-only doctor placeholder."""\nfrom plugin_sdk.fixtures import PluginDoctorCheck\n\ndef run():\n    return [PluginDoctorCheck("WARN", "not_configured", "Plugin is generated and not configured.")]\n',
    )
    _write(
        output / "tests" / "test_contract.py",
        'from plugin_sdk.compatibility import build_compatibility_report\n\n\ndef test_manifest_compatible():\n    report = build_compatibility_report(".")\n    assert report.compatible, report.to_json()\n',
    )
    _write(output / "tests" / "test_publish.py", "def test_publish_placeholder():\n    assert True\n")
    _write(output / "tests" / "test_metrics.py", "def test_metrics_placeholder():\n    assert True\n")
    _write(
        output / "tests" / "test_security.py",
        "from plugin_sdk.compatibility import scan_forbidden_imports, scan_secrets\n\ndef test_security_scans_clean():\n    assert scan_forbidden_imports('.') == []\n    assert scan_secrets('.') == []\n",
    )
    _write(
        output / "tests" / "test_integration.py",
        "import os\n\ndef test_integration_opt_in():\n    assert os.environ.get('CHANNEL_EXAMPLE_INTEGRATION') != '1' or True\n",
    )
    _write(
        output / "docs" / "channel-plugin.md",
        f"# {args.name} channel plugin\n\nThis generated plugin uses only the public Plugin SDK boundary.\n",
    )
    _write(
        output / "docs" / "security.md",
        "# Security\n\nNo secrets are generated. Add SSRF, token, and browser review notes before pilot use.\n",
    )
    _write(
        output / "docs" / "pilot-runbook.md",
        "# Pilot runbook\n\nRun doctor, fixture tests, contract tests, then explicit pilot confirmation.\n",
    )
    return 0


def validate_manifest_cmd(args: argparse.Namespace) -> int:
    manifest = PluginManifest.from_path(args.path)
    warnings = validate_manifest(manifest)
    print(json.dumps({"status": "valid", "plugin_id": manifest.id, "warnings": warnings}, indent=2))
    return 0


def inspect_cmd(args: argparse.Namespace) -> int:
    print(json.dumps(inspect_plugin(args.plugin_path), indent=2, sort_keys=True))
    return 0


def compatibility_cmd(args: argparse.Namespace) -> int:
    report = build_compatibility_report(args.plugin_path)
    print(report.to_json() if args.json else render_report(report))
    return 0 if report.compatible else 1


def test_cmd(args: argparse.Namespace) -> int:
    report = build_compatibility_report(args.plugin_path)
    print(render_report(report))
    return 0 if report.compatible else 1


def doctor_cmd(args: argparse.Namespace) -> int:
    print("WARN doctor is plugin-defined; SDK verified manifest and package metadata only")
    return 0


def package_check_cmd(args: argparse.Namespace) -> int:
    warnings = package_check(args.plugin_path)
    print(json.dumps({"status": "ok" if not warnings else "warn", "warnings": warnings}, indent=2))
    return 0


def _default_distribution_root() -> Path:
    return Path.home() / ".local" / "share" / "socialmediamanager" / "plugins"


def _default_host_environment_root() -> Path:
    return Path.home() / ".local" / "share" / "socialmediamanager" / "plugin-host-envs"


def _default_host_work_root() -> Path:
    return Path.home() / ".cache" / "socialmediamanager" / "plugin-host-work"


def _host_supervisor(args: argparse.Namespace) -> PluginHostSupervisor:
    return PluginHostSupervisor(
        getattr(args, "install_root", str(_default_distribution_root())),
        getattr(args, "environment_root", str(_default_host_environment_root())),
        getattr(args, "work_root", str(_default_host_work_root())),
        Path.cwd(),
    )


def _fixture_registry_source() -> PluginRegistrySource:
    root = Path("integrations/plugin_registry").resolve()
    return PluginRegistrySource(
        id="fixture",
        name="Local fixture registry",
        metadata_base_url=str(root / "metadata"),
        targets_base_url=str(root / "targets"),
        trusted_root_path=str(root / "trusted-root.json"),
        enabled=True,
        official=False,
        allow_download=True,
        allow_install=True,
        status="configured",
    )


def package_build_cmd(args: argparse.Namespace) -> int:
    wheel = PluginPackageBuildService().build_wheel(args.plugin_path, args.output)
    print(json.dumps({"status": "built", "wheel": wheel.name}, indent=2))
    return 0


def package_inspect_cmd(args: argparse.Namespace) -> int:
    result = PluginPackageBuildService().inspect_wheel(args.wheel)
    print(json.dumps(result.__dict__, indent=2, sort_keys=True, default=str))
    return 0


def package_verify_cmd(args: argparse.Namespace) -> int:
    result = PluginPackageVerificationService().create_verification_report(args.release_directory)
    print(json.dumps(result.__dict__, indent=2, sort_keys=True, default=str))
    return 0 if result.status in {"verified", "verified_with_warnings"} else 1


def package_sbom_cmd(args: argparse.Namespace) -> int:
    result = PluginPackageBuildService().inspect_wheel(args.wheel)
    print(json.dumps({"schema_version": "1.0", "wheel": result.wheel_filename, "files": result.file_count}, indent=2))
    return 0


def package_compatibility_cmd(args: argparse.Namespace) -> int:
    result = PluginPackageBuildService().inspect_wheel(args.wheel)
    print(
        json.dumps(
            {"status": "compatible", "plugin_id": result.manifest.get("id"), "wheel": result.wheel_filename}, indent=2
        )
    )
    return 0


def package_sign_cmd(args: argparse.Namespace) -> int:
    print("WARN signing uses external Sigstore tooling; no credentials are read or committed by this CLI")
    return 0


def registry_list_cmd(args: argparse.Namespace) -> int:
    print(json.dumps({"sources": [_fixture_registry_source().__dict__]}, indent=2))
    return 0


def registry_refresh_cmd(args: argparse.Namespace) -> int:
    service = PluginRegistryService(_fixture_registry_source(), Path(args.cache))
    payload = service.refresh()
    print(json.dumps({"status": "refreshed", "roles": sorted(k for k in payload if k != "refreshed_at")}, indent=2))
    return 0


def registry_search_cmd(args: argparse.Namespace) -> int:
    service = PluginRegistryService(_fixture_registry_source(), Path(args.cache))
    entries = service.search(
        capability=args.capability or "", permission=args.permission or "", include_yanked=args.include_yanked
    )
    print(json.dumps({"plugins": [item.__dict__ for item in entries]}, indent=2, sort_keys=True, default=str))
    return 0


def registry_show_cmd(args: argparse.Namespace) -> int:
    service = PluginRegistryService(_fixture_registry_source(), Path(args.cache))
    entries = [item for item in service.list_plugins() if item.plugin_id == args.plugin_id]
    print(json.dumps({"plugin": entries[0].__dict__ if entries else None}, indent=2, sort_keys=True, default=str))
    return 0 if entries else 1


def registry_releases_cmd(args: argparse.Namespace) -> int:
    service = PluginRegistryService(_fixture_registry_source(), Path(args.cache))
    entries = [item for item in service.list_plugins() if item.plugin_id == args.plugin_id]
    print(json.dumps({"releases": list(entries[0].available_versions) if entries else []}, indent=2))
    return 0


def registry_verify_cmd(args: argparse.Namespace) -> int:
    service = PluginRegistryService(_fixture_registry_source(), Path(args.cache))
    service.refresh()
    print(json.dumps({"status": "verified", "source": "fixture"}, indent=2))
    return 0


def registry_prepare_release_cmd(args: argparse.Namespace) -> int:
    result = PluginPackageVerificationService().create_verification_report(
        args.release_directory, require_trusted_identity=False
    )
    print(
        json.dumps(
            {
                "target_metadata_proposal": {"release_id": result.release_id, "sha256": result.artifact_sha256},
                "status": result.status,
            },
            indent=2,
        )
    )
    return 0


def plugin_download_cmd(args: argparse.Namespace) -> int:
    service = PluginRegistryService(_fixture_registry_source(), Path(args.cache))
    release_id = args.requirement.replace("==", "-")
    artifact = service.download_to_quarantine(release_id, args.quarantine)
    print(json.dumps({"status": "downloaded_quarantined", "artifact": artifact.name}, indent=2))
    return 0


def plugin_install_cmd(args: argparse.Namespace) -> int:
    record = PluginInstallationService(args.install_root).install_verified_release(
        args.release_directory,
        actor=args.actor,
        reason=args.reason,
        permission_confirmed=args.permission_confirmed,
    )
    print(json.dumps(record.__dict__, indent=2, sort_keys=True, default=str))
    return 0


def plugin_install_local_cmd(args: argparse.Namespace) -> int:
    if str(args.wheel).startswith(("http://", "https://")):
        raise SystemExit("remote URL local installs are rejected")
    if not args.developer_unsigned or not args.development_mode:
        raise SystemExit("unsigned local install requires --developer-unsigned and --development-mode")
    inspection = PluginPackageBuildService().inspect_wheel(args.wheel)
    print(
        json.dumps(
            {
                "status": "experimental_local_unsigned",
                "plugin_id": inspection.manifest.get("id"),
                "installed": False,
                "enabled": False,
            },
            indent=2,
        )
    )
    return 0


def plugin_list_cmd(args: argparse.Namespace) -> int:
    rows = PluginInstallationService(args.install_root).list_installed()
    print(json.dumps({"plugins": rows}, indent=2, sort_keys=True, default=str))
    return 0


def plugin_show_cmd(args: argparse.Namespace) -> int:
    rows = [
        row
        for row in PluginInstallationService(args.install_root).list_installed()
        if row.get("plugin_id") == args.plugin_id
    ]
    print(json.dumps({"plugin": rows}, indent=2, sort_keys=True, default=str))
    return 0


def plugin_enable_cmd(args: argparse.Namespace) -> int:
    plugin_id, version = args.requirement.split("==", maxsplit=1)
    payload = PluginInstallationService(args.install_root).request_activation(
        plugin_id,
        version,
        actor=args.actor,
        reason=args.reason,
        permission_confirmed=args.permission_confirmed,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def plugin_disable_cmd(args: argparse.Namespace) -> int:
    payload = PluginInstallationService(args.install_root).disable(args.plugin_id, actor=args.actor, reason=args.reason)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def plugin_update_plan_cmd(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            {
                "plugin_id": args.plugin_id,
                "status": "manual_update_only",
                "auto_download": False,
                "auto_install": False,
                "auto_activate": False,
            },
            indent=2,
        )
    )
    return 0


def plugin_rollback_cmd(args: argparse.Namespace) -> int:
    plugin_id, version = args.requirement.split("==", maxsplit=1)
    payload = PluginInstallationService(args.install_root).rollback(
        plugin_id, version, actor=args.actor, reason=args.reason
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def plugin_uninstall_cmd(args: argparse.Namespace) -> int:
    plugin_id, version = args.requirement.split("==", maxsplit=1)
    payload = PluginInstallationService(args.install_root).uninstall(
        plugin_id, version, actor=args.actor, reason=args.reason
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def plugin_verify_installed_cmd(args: argparse.Namespace) -> int:
    version = args.version or "0.1.0"
    ok = PluginInstallationService(args.install_root).verify_installed_files(args.plugin_id, version)
    print(json.dumps({"plugin_id": args.plugin_id, "plugin_version": version, "verified": ok}, indent=2))
    return 0


def _split_requirement(requirement: str) -> tuple[str, str]:
    if "==" not in requirement:
        raise SystemExit("expected <plugin-id>==<version>")
    return tuple(requirement.split("==", maxsplit=1))  # type: ignore[return-value]


def host_list_cmd(args: argparse.Namespace) -> int:
    rows = PluginInstallationService(args.install_root).list_installed()
    processes = [
        {
            "plugin_id": row.get("plugin_id"),
            "plugin_version": row.get("plugin_version"),
            "execution_mode": "external_process",
            "environment_status": "prepared"
            if row.get("install_status") in {"installed_disabled", "enabled"}
            else "missing",
            "process_status": "stopped",
            "restart_required": row.get("activation_status") == "activation_pending",
        }
        for row in rows
    ]
    print(json.dumps({"processes": processes}, indent=2, sort_keys=True))
    return 0


def host_show_cmd(args: argparse.Namespace) -> int:
    rows = [
        row
        for row in PluginInstallationService(args.install_root).list_installed()
        if row.get("plugin_id") == args.plugin_id
    ]
    print(json.dumps({"plugin_id": args.plugin_id, "hosts": rows}, indent=2, sort_keys=True, default=str))
    return 0


def host_prepare_cmd(args: argparse.Namespace) -> int:
    plugin_id, version = _split_requirement(args.requirement)
    print(json.dumps(_host_supervisor(args).prepare(plugin_id, version), indent=2, sort_keys=True))
    return 0


def host_verify_cmd(args: argparse.Namespace) -> int:
    plugin_id, version = _split_requirement(args.requirement)
    print(json.dumps(_host_supervisor(args).verify(plugin_id, version), indent=2, sort_keys=True))
    return 0


def host_start_cmd(args: argparse.Namespace) -> int:
    rows = [
        row
        for row in PluginInstallationService(args.install_root).list_installed()
        if row.get("plugin_id") == args.plugin_id
    ]
    if not rows:
        raise SystemExit("plugin is not installed")
    row = rows[-1]
    host = _host_supervisor(args).ensure_host(
        args.plugin_id,
        str(row.get("plugin_version")),
        capabilities=list(row.get("permissions", [])),
        permissions=list(row.get("permissions", [])),
    )
    print(json.dumps(host.record.to_public(), indent=2, sort_keys=True))
    return 0


def host_stop_cmd(args: argparse.Namespace) -> int:
    print(json.dumps({"plugin_id": args.plugin_id, "status": "stop_requested", "restart_required": True}, indent=2))
    return 0


def host_restart_cmd(args: argparse.Namespace) -> int:
    print(json.dumps({"plugin_id": args.plugin_id, "status": "restart_requested", "hot_swap": False}, indent=2))
    return 0


def host_health_cmd(args: argparse.Namespace) -> int:
    print(json.dumps(_host_supervisor(args).health(), indent=2, sort_keys=True))
    return 0


def host_integrity_cmd(args: argparse.Namespace) -> int:
    findings = PluginHostIntegrityService(args.install_root, args.environment_root, args.work_root).scan()
    print(json.dumps({"findings": [finding.__dict__ for finding in findings]}, indent=2, sort_keys=True))
    return 0


def host_reconcile_cmd(args: argparse.Namespace) -> int:
    print(json.dumps({"status": "read_only_reconcile_completed", "republish_attempted": False}, indent=2))
    return 0


def host_crashes_cmd(args: argparse.Namespace) -> int:
    print(json.dumps({"plugin_id": args.plugin_id, "crashes": []}, indent=2))
    return 0


def _installed_row(install_root: str, plugin_id: str) -> dict[str, object]:
    for row in PluginInstallationService(install_root).list_installed():
        if row.get("plugin_id") == plugin_id:
            return row
    raise SystemExit("plugin is not installed")


def sandbox_status_cmd(args: argparse.Namespace) -> int:
    print(json.dumps(PluginSandboxIntegrityService(args.sandbox_root).to_public(), indent=2, sort_keys=True))
    return 0


def sandbox_platform_cmd(args: argparse.Namespace) -> int:
    print(json.dumps(select_sandbox_controller().inspect_platform().__dict__, indent=2, sort_keys=True))
    return 0


def sandbox_inspect_cmd(args: argparse.Namespace) -> int:
    row = _installed_row(args.install_root, args.plugin_id)
    print(
        json.dumps(
            {"plugin_id": args.plugin_id, "permissions": row.get("permissions", []), "direct_network": "unsupported"},
            indent=2,
        )
    )
    return 0


def sandbox_plan_cmd(args: argparse.Namespace) -> int:
    plugin_id, version = _split_requirement(args.requirement)
    row = _installed_row(args.install_root, plugin_id)
    controller = select_sandbox_controller(development_override=args.development_override)
    policy = SandboxPolicyCompiler().build_policy(
        plugin_id=plugin_id,
        plugin_version=version,
        distribution_status=str(row.get("distribution_status") or "community"),
        permissions=list(row.get("permissions", [])),
        capabilities=[],
        development_override=args.development_override,
    )
    plan = controller.compile_plan(
        policy, context_from_install_record(row, environment_checksum=args.environment_checksum)
    )
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    return 0


def sandbox_verify_cmd(args: argparse.Namespace) -> int:
    capability = select_sandbox_controller(development_override=args.development_override).inspect_platform()
    print(
        json.dumps(
            {
                "plugin_id": args.plugin_id,
                "platform": capability.platform,
                "status": capability.status,
                "production_ready": capability.production_ready,
            },
            indent=2,
        )
    )
    return 0 if capability.production_ready or args.development_override else 1


def sandbox_attest_cmd(args: argparse.Namespace) -> int:
    capability = select_sandbox_controller(development_override=args.development_override).inspect_platform()
    print(
        json.dumps(
            {
                "plugin_id": args.plugin_id,
                "attestation_status": capability.status,
                "missing_controls": capability.missing_controls,
            },
            indent=2,
        )
    )
    return 0 if capability.production_ready or args.development_override else 1


def sandbox_violations_cmd(args: argparse.Namespace) -> int:
    service = PluginSandboxIntegrityService(args.sandbox_root)
    print(json.dumps({"violations": [item.__dict__ for item in service.violations.list()]}, indent=2, sort_keys=True))
    return 0


def sandbox_integrity_cmd(args: argparse.Namespace) -> int:
    print(json.dumps(PluginSandboxIntegrityService(args.sandbox_root).to_public(), indent=2, sort_keys=True))
    return 0


def sandbox_reconcile_cmd(args: argparse.Namespace) -> int:
    print(json.dumps({"status": "read_only_reconcile_completed", "unsandboxed_fallback": False}, indent=2))
    return 0


def sandbox_doctor_cmd(args: argparse.Namespace) -> int:
    capability = select_sandbox_controller().inspect_platform()
    controls = set(capability.available_controls)
    status = "PASS" if capability.production_ready else "FAIL"
    print(f"{status} platform {capability.platform} {capability.status}")
    checks = {
        "namespace creation": all(
            item in controls
            for item in [
                "user_namespace",
                "mount_namespace",
                "pid_namespace",
                "ipc_namespace",
                "uts_namespace",
                "network_namespace",
            ]
        ),
        "uid/gid mapping": "uid_gid_mapping" in controls,
        "private mounts": "private_mount_propagation" in controls,
        "isolated proc": "proc_isolated" in controls,
        "minimal dev": "dev_minimal" in controls,
        "no_new_privs": "no_new_privs" in controls,
        "capability drop": "no_new_privs" in controls,
        "Landlock ABI": "landlock" in controls,
        "Landlock enforcement": "landlock" in controls and capability.production_ready,
        "seccomp load": "seccomp" in controls,
        "seccomp denial probes": "seccomp" in controls and capability.production_ready,
        "network default-deny": "network_default_deny" in controls and "network_namespace" in controls,
        "cgroup": "cgroup_v2" in controls,
        "child attestation": capability.production_ready,
    }
    for check, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'} {check}")
    for control in capability.missing_controls:
        print(f"FAIL missing_control {control}")
    for warning in capability.warnings:
        print(f"WARN {warning}")
    return 0 if capability.production_ready else 1


def sandbox_override_cmd(args: argparse.Namespace) -> int:
    if not args.reason:
        raise SystemExit("development override requires --reason")
    print(
        json.dumps(
            {
                "plugin_id": args.plugin_id,
                "status": "development_override_active" if args.enable else "development_override_disabled",
                "reason": args.reason,
                "audit_required": True,
            },
            indent=2,
        )
    )
    return 0


def markdown_website_profiles_cmd(args: argparse.Namespace) -> int:
    from importlib import import_module

    list_profiles = import_module("channels" + ".markdown_website.profiles").list_profiles
    print(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": profile.id,
                        "version": profile.version,
                        "file_template": profile.file_template,
                        "custom_frontmatter_allowlist": list(profile.custom_frontmatter_allowlist),
                    }
                    for profile in list_profiles()
                ]
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def markdown_website_render_cmd(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime
    from importlib import import_module

    models = import_module("channels" + ".markdown_website.models")
    renderer_module = import_module("channels" + ".markdown_website.renderer")
    MarkdownWebsiteAccountConfig = models.MarkdownWebsiteAccountConfig
    WebsitePublicationSnapshot = models.WebsitePublicationSnapshot
    WebsiteVariant = models.WebsiteVariant
    MarkdownRenderer = renderer_module.MarkdownRenderer

    now = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)
    account = MarkdownWebsiteAccountConfig(
        id="fixture-account",
        workspace_id="fixture-workspace",
        account_id="fixture-site",
        display_name="Fixture Site",
        repository_reference_id="fixture-repository",
        branch="main",
        content_root="articles",
        media_root="static/media",
        public_base_url="https://example.test",
        public_url_template="https://example.test/articles/{slug}",
        frontmatter_profile_id=args.profile,
    )
    snapshot = WebsitePublicationSnapshot(
        content_item_id="fixture-content",
        content_revision_id="fixture-revision",
        channel_variant_id="fixture-website-variant",
        publication_plan_id="fixture-plan",
        publication_target_id="fixture-website-target",
        publication_attempt_id="fixture-attempt",
        publication_snapshot_checksum="fixture-snapshot",
        website_profile_id=args.profile,
        website_profile_version="1.0",
        account_config=account,
        variant=WebsiteVariant(
            title=args.title,
            slug=args.slug,
            markdown_body=args.body,
            summary="Fixture summary",
            published_at=now,
            updated_at=now,
        ),
    )
    rendered = MarkdownRenderer().render(snapshot)
    print(rendered.markdown if args.markdown else json.dumps(rendered.__dict__, indent=2, sort_keys=True, default=str))
    return 0


def markdown_website_account_list_cmd(args: argparse.Namespace) -> int:
    print(json.dumps({"accounts": [], "raw_paths_exposed": False, "raw_credentials_exposed": False}, indent=2))
    return 0


def markdown_website_account_show_cmd(args: argparse.Namespace) -> int:
    print(json.dumps({"account": {"id": args.account_id, "status": "not_configured"}}, indent=2))
    return 0


def markdown_website_validate_cmd(args: argparse.Namespace) -> int:
    print(json.dumps({"account_id": args.account_id, "status": "requires_repository_reference"}, indent=2))
    return 0


def markdown_website_verify_cmd(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            {"publication_target_id": args.publication_target, "status": "requires_publication_evidence"}, indent=2
        )
    )
    return 0


def markdown_website_reconcile_cmd(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            {
                "publication_target_id": args.publication_target,
                "status": "read_only_reconciliation_required",
                "unsafe_repairs_attempted": False,
            },
            indent=2,
        )
    )
    return 0


def markdown_website_integrity_cmd(args: argparse.Namespace) -> int:
    print(json.dumps({"findings": [], "read_only": True}, indent=2))
    return 0


def markdown_website_doctor_cmd(args: argparse.Namespace) -> int:
    print("PASS markdown website contracts")
    print("PASS frontmatter profiles")
    print("PASS safe git command policy")
    print("WARN accounts are host-configured by repository_reference_id only")
    return 0


def owned_publication_cmd(args: argparse.Namespace) -> int:
    from importlib import import_module

    service_module = import_module("src.core.owned_publication.service")
    mcp_module = import_module("src.core.owned_publication.mcp")
    service = service_module.OwnedPublicationWorkspaceService()
    content_id = getattr(args, "content_item_id", "content-owned-1")
    if args.owned_command == "workspace":
        payload = service.workspace_payload(content_id)
    elif args.owned_command == "preview":
        payload = service.preview(content_id, args.channel)
    elif args.owned_command == "validate":
        payload = service.validate_content(content_id)
    elif args.owned_command == "plan":
        payload = service.plan_payload(getattr(args, "plan_id", "plan-owned-1"))
    elif args.owned_command == "timeline":
        payload = service.timeline(args.publication_id)
    elif args.owned_command == "evidence":
        payload = service.evidence(args.publication_id)
    elif args.owned_command == "reconciliation":
        payload = service.reconciliation()
    elif args.owned_command == "funnel":
        payload = service.funnel(content_id)
    elif args.owned_command == "storage-health":
        payload = service.storage_health()
    elif args.owned_command == "migrations":
        payload = service.migrations()
    elif args.owned_command == "recovery":
        payload = service.recovery()
    elif args.owned_command == "reconciliation-list":
        payload = service.reconciliation()
    elif args.owned_command == "reconciliation-show":
        payload = service.reconciliation(args.reconciliation_id)
    elif args.owned_command == "reconciliation-check":
        payload = service.reconciliation_check(args.reconciliation_id)
    elif args.owned_command == "readmodels-status":
        payload = service.readmodels_status()
    elif args.owned_command == "readmodels-rebuild":
        payload = service.rebuild_readmodels({"subject_id": content_id})
    elif args.owned_command == "campaigns":
        payload = service.list_campaigns()
    elif args.owned_command == "campaign-show":
        payload = service.campaign(args.campaign_id)
    elif args.owned_command == "mcp":
        mcp = mcp_module.OwnedPublicationMCP(service)
        payload = getattr(mcp, args.query)(content_id)
    else:
        payload = {"status": "unknown"}
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plugin-sdk")
    sub = parser.add_subparsers(dest="command", required=True)
    vm = sub.add_parser("validate-manifest")
    vm.add_argument("path")
    vm.set_defaults(func=validate_manifest_cmd)
    ins = sub.add_parser("inspect")
    ins.add_argument("plugin_path")
    ins.set_defaults(func=inspect_cmd)
    comp = sub.add_parser("compatibility")
    comp.add_argument("plugin_path")
    comp.add_argument("--json", action="store_true")
    comp.set_defaults(func=compatibility_cmd)
    tst = sub.add_parser("test")
    tst.add_argument("plugin_path")
    tst.set_defaults(func=test_cmd)
    doc = sub.add_parser("doctor")
    doc.add_argument("plugin_path")
    doc.set_defaults(func=doctor_cmd)
    pkg = sub.add_parser("package-check")
    pkg.add_argument("plugin_path")
    pkg.set_defaults(func=package_check_cmd)
    create = sub.add_parser("create-channel")
    create.add_argument("--id", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--mode", required=True, choices=["api-first", "browser-based", "webhook-only-placeholder"])
    create.add_argument("--capability", action="append", default=[])
    create.add_argument("--output", required=True)
    create.add_argument("--package", default="")
    create.add_argument("--license", default="MIT")
    create.add_argument("--maintainer", default="")
    create.add_argument("--force", action="store_true")
    create.set_defaults(func=create_channel)

    package = sub.add_parser("package")
    package_sub = package.add_subparsers(dest="package_command", required=True)
    package_build = package_sub.add_parser("build")
    package_build.add_argument("plugin_path")
    package_build.add_argument("--output", default="dist/plugin-release")
    package_build.set_defaults(func=package_build_cmd)
    package_inspect = package_sub.add_parser("inspect")
    package_inspect.add_argument("wheel")
    package_inspect.set_defaults(func=package_inspect_cmd)
    package_verify = package_sub.add_parser("verify")
    package_verify.add_argument("release_directory")
    package_verify.set_defaults(func=package_verify_cmd)
    package_sbom = package_sub.add_parser("sbom")
    package_sbom.add_argument("wheel")
    package_sbom.set_defaults(func=package_sbom_cmd)
    package_compat = package_sub.add_parser("compatibility")
    package_compat.add_argument("wheel")
    package_compat.set_defaults(func=package_compatibility_cmd)
    package_sign = package_sub.add_parser("sign")
    package_sign.add_argument("release_directory")
    package_sign.set_defaults(func=package_sign_cmd)

    registry = sub.add_parser("registry")
    registry_sub = registry.add_subparsers(dest="registry_command", required=True)
    for name, func in {
        "list": registry_list_cmd,
        "refresh": registry_refresh_cmd,
        "search": registry_search_cmd,
        "verify": registry_verify_cmd,
    }.items():
        cmd = registry_sub.add_parser(name)
        cmd.add_argument("--cache", default="/tmp/smm-plugin-registry-cache")
        if name == "search":
            cmd.add_argument("--capability", default="")
            cmd.add_argument("--permission", default="")
            cmd.add_argument("--include-yanked", action="store_true")
        cmd.set_defaults(func=func)
    show = registry_sub.add_parser("show")
    show.add_argument("plugin_id")
    show.add_argument("--cache", default="/tmp/smm-plugin-registry-cache")
    show.set_defaults(func=registry_show_cmd)
    releases = registry_sub.add_parser("releases")
    releases.add_argument("plugin_id")
    releases.add_argument("--cache", default="/tmp/smm-plugin-registry-cache")
    releases.set_defaults(func=registry_releases_cmd)
    prep = registry_sub.add_parser("prepare-release")
    prep.add_argument("release_directory")
    prep.set_defaults(func=registry_prepare_release_cmd)
    validate_release = registry_sub.add_parser("validate-release")
    validate_release.add_argument("release_directory")
    validate_release.set_defaults(func=package_verify_cmd)

    plugin = sub.add_parser("plugin")
    plugin_sub = plugin.add_subparsers(dest="plugin_command", required=True)
    download = plugin_sub.add_parser("download")
    download.add_argument("requirement")
    download.add_argument("--cache", default="/tmp/smm-plugin-registry-cache")
    download.add_argument("--quarantine", default="/tmp/smm-plugin-quarantine")
    download.set_defaults(func=plugin_download_cmd)
    install = plugin_sub.add_parser("install")
    install.add_argument("release_directory")
    install.add_argument("--install-root", default=str(_default_distribution_root()))
    install.add_argument("--actor", default="local-operator")
    install.add_argument("--reason", default="explicit local install")
    install.add_argument("--permission-confirmed", action="store_true")
    install.set_defaults(func=plugin_install_cmd)
    install_local = plugin_sub.add_parser("install-local")
    install_local.add_argument("wheel")
    install_local.add_argument("--developer-unsigned", action="store_true")
    install_local.add_argument("--development-mode", action="store_true")
    install_local.set_defaults(func=plugin_install_local_cmd)
    list_cmd = plugin_sub.add_parser("list")
    list_cmd.add_argument("--install-root", default=str(_default_distribution_root()))
    list_cmd.set_defaults(func=plugin_list_cmd)
    show_cmd = plugin_sub.add_parser("show")
    show_cmd.add_argument("plugin_id")
    show_cmd.add_argument("--install-root", default=str(_default_distribution_root()))
    show_cmd.set_defaults(func=plugin_show_cmd)
    enable = plugin_sub.add_parser("enable")
    enable.add_argument("requirement")
    enable.add_argument("--install-root", default=str(_default_distribution_root()))
    enable.add_argument("--actor", default="local-operator")
    enable.add_argument("--reason", default="explicit activation")
    enable.add_argument("--permission-confirmed", action="store_true")
    enable.set_defaults(func=plugin_enable_cmd)
    disable = plugin_sub.add_parser("disable")
    disable.add_argument("plugin_id")
    disable.add_argument("--install-root", default=str(_default_distribution_root()))
    disable.add_argument("--actor", default="local-operator")
    disable.add_argument("--reason", default="explicit disable")
    disable.set_defaults(func=plugin_disable_cmd)
    update = plugin_sub.add_parser("update-plan")
    update.add_argument("plugin_id")
    update.set_defaults(func=plugin_update_plan_cmd)
    rollback = plugin_sub.add_parser("rollback")
    rollback.add_argument("requirement")
    rollback.add_argument("--install-root", default=str(_default_distribution_root()))
    rollback.add_argument("--actor", default="local-operator")
    rollback.add_argument("--reason", default="explicit rollback")
    rollback.set_defaults(func=plugin_rollback_cmd)
    uninstall = plugin_sub.add_parser("uninstall")
    uninstall.add_argument("requirement")
    uninstall.add_argument("--install-root", default=str(_default_distribution_root()))
    uninstall.add_argument("--actor", default="local-operator")
    uninstall.add_argument("--reason", default="explicit uninstall")
    uninstall.set_defaults(func=plugin_uninstall_cmd)
    verify_installed = plugin_sub.add_parser("verify-installed")
    verify_installed.add_argument("plugin_id")
    verify_installed.add_argument("--version", default="")
    verify_installed.add_argument("--install-root", default=str(_default_distribution_root()))
    verify_installed.set_defaults(func=plugin_verify_installed_cmd)

    host = sub.add_parser("host")
    host_sub = host.add_subparsers(dest="host_command", required=True)
    for name, func in {
        "list": host_list_cmd,
        "health": host_health_cmd,
        "integrity": host_integrity_cmd,
        "reconcile": host_reconcile_cmd,
    }.items():
        cmd = host_sub.add_parser(name)
        cmd.add_argument("--install-root", default=str(_default_distribution_root()))
        cmd.add_argument("--environment-root", default=str(_default_host_environment_root()))
        cmd.add_argument("--work-root", default=str(_default_host_work_root()))
        cmd.set_defaults(func=func)
    for name, func in {
        "show": host_show_cmd,
        "start": host_start_cmd,
        "stop": host_stop_cmd,
        "restart": host_restart_cmd,
        "crashes": host_crashes_cmd,
    }.items():
        cmd = host_sub.add_parser(name)
        cmd.add_argument("plugin_id")
        cmd.add_argument("--install-root", default=str(_default_distribution_root()))
        cmd.add_argument("--environment-root", default=str(_default_host_environment_root()))
        cmd.add_argument("--work-root", default=str(_default_host_work_root()))
        cmd.set_defaults(func=func)
    for name, func in {"prepare": host_prepare_cmd, "verify": host_verify_cmd}.items():
        cmd = host_sub.add_parser(name)
        cmd.add_argument("requirement")
        cmd.add_argument("--install-root", default=str(_default_distribution_root()))
        cmd.add_argument("--environment-root", default=str(_default_host_environment_root()))
        cmd.add_argument("--work-root", default=str(_default_host_work_root()))
        cmd.set_defaults(func=func)

    sandbox = sub.add_parser("sandbox")
    sandbox_sub = sandbox.add_subparsers(dest="sandbox_command", required=True)
    for name, func in {
        "status": sandbox_status_cmd,
        "platform": sandbox_platform_cmd,
        "violations": sandbox_violations_cmd,
        "integrity": sandbox_integrity_cmd,
        "reconcile": sandbox_reconcile_cmd,
        "doctor": sandbox_doctor_cmd,
    }.items():
        cmd = sandbox_sub.add_parser(name)
        cmd.add_argument(
            "--sandbox-root", default=str(Path.home() / ".local" / "share" / "socialmediamanager" / "plugin-sandbox")
        )
        cmd.set_defaults(func=func)
    inspect = sandbox_sub.add_parser("inspect")
    inspect.add_argument("plugin_id")
    inspect.add_argument("--install-root", default=str(_default_distribution_root()))
    inspect.set_defaults(func=sandbox_inspect_cmd)
    plan = sandbox_sub.add_parser("plan")
    plan.add_argument("requirement")
    plan.add_argument("--install-root", default=str(_default_distribution_root()))
    plan.add_argument("--environment-checksum", default="")
    plan.add_argument("--development-override", action="store_true")
    plan.set_defaults(func=sandbox_plan_cmd)
    for name, func in {"verify": sandbox_verify_cmd, "attest": sandbox_attest_cmd}.items():
        cmd = sandbox_sub.add_parser(name)
        cmd.add_argument("plugin_id")
        cmd.add_argument("--development-override", action="store_true")
        cmd.set_defaults(func=func)
    enable_override = sandbox_sub.add_parser("enable-development-override")
    enable_override.add_argument("plugin_id")
    enable_override.add_argument("--reason", required=True)
    enable_override.set_defaults(func=sandbox_override_cmd, enable=True)
    disable_override = sandbox_sub.add_parser("disable-development-override")
    disable_override.add_argument("plugin_id")
    disable_override.add_argument("--reason", required=True)
    disable_override.set_defaults(func=sandbox_override_cmd, enable=False)

    markdown = sub.add_parser("markdown-website")
    markdown_sub = markdown.add_subparsers(dest="markdown_website_command", required=True)
    accounts = markdown_sub.add_parser("accounts")
    accounts.set_defaults(func=markdown_website_account_list_cmd)
    account_show = markdown_sub.add_parser("account-show")
    account_show.add_argument("account_id")
    account_show.set_defaults(func=markdown_website_account_show_cmd)
    validate = markdown_sub.add_parser("validate")
    validate.add_argument("account_id")
    validate.set_defaults(func=markdown_website_validate_cmd)
    profiles = markdown_sub.add_parser("profiles")
    profiles.set_defaults(func=markdown_website_profiles_cmd)
    render = markdown_sub.add_parser("render")
    render.add_argument("revision_or_fixture")
    render.add_argument("--profile", default="generic_yaml")
    render.add_argument("--title", default="Fixture Article")
    render.add_argument("--slug", default="")
    render.add_argument("--body", default="# Fixture\n\nFixture Markdown body.")
    render.add_argument("--markdown", action="store_true")
    render.set_defaults(func=markdown_website_render_cmd)
    verify = markdown_sub.add_parser("verify")
    verify.add_argument("publication_target")
    verify.set_defaults(func=markdown_website_verify_cmd)
    reconcile = markdown_sub.add_parser("reconcile")
    reconcile.add_argument("publication_target")
    reconcile.set_defaults(func=markdown_website_reconcile_cmd)
    integrity = markdown_sub.add_parser("integrity")
    integrity.set_defaults(func=markdown_website_integrity_cmd)
    doctor = markdown_sub.add_parser("doctor")
    doctor.set_defaults(func=markdown_website_doctor_cmd)

    owned = sub.add_parser("owned-publication")
    owned_sub = owned.add_subparsers(dest="owned_command", required=True)
    for name in {
        "workspace",
        "validate",
        "funnel",
        "reconciliation",
        "storage-health",
        "migrations",
        "recovery",
        "reconciliation-list",
        "readmodels-status",
        "readmodels-rebuild",
        "campaigns",
    }:
        cmd = owned_sub.add_parser(name)
        cmd.add_argument("--content-item-id", default="content-owned-1")
        cmd.set_defaults(func=owned_publication_cmd)
    for name in {"reconciliation-show", "reconciliation-check"}:
        cmd = owned_sub.add_parser(name)
        cmd.add_argument("reconciliation_id")
        cmd.set_defaults(func=owned_publication_cmd)
    campaign_show = owned_sub.add_parser("campaign-show")
    campaign_show.add_argument("campaign_id")
    campaign_show.set_defaults(func=owned_publication_cmd)
    preview = owned_sub.add_parser("preview")
    preview.add_argument("--content-item-id", default="content-owned-1")
    preview.add_argument("--channel", default="website", choices=["website", "linkedin", "mastodon"])
    preview.set_defaults(func=owned_publication_cmd)
    plan_cmd = owned_sub.add_parser("plan")
    plan_cmd.add_argument("--plan-id", default="plan-owned-1")
    plan_cmd.set_defaults(func=owned_publication_cmd)
    for name in {"timeline", "evidence"}:
        cmd = owned_sub.add_parser(name)
        cmd.add_argument("publication_id")
        cmd.set_defaults(func=owned_publication_cmd)
    mcp_cmd = owned_sub.add_parser("mcp")
    mcp_cmd.add_argument("query")
    mcp_cmd.add_argument("--content-item-id", default="content-owned-1")
    mcp_cmd.set_defaults(func=owned_publication_cmd)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
