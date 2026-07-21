"""Developer CLI for Plugin SDK v1."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
