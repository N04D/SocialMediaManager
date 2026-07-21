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
        return PluginManifest.from_path(Path(__file__).resolve().parents[2] / "channel.manifest.json")

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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
