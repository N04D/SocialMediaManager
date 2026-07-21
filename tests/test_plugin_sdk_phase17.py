from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import plugin_sdk
from dashboard import plugin_compatibility_payload, plugin_sdk_version_payload
from plugin_sdk import (
    CHANNEL_PLUGIN_SDK_CONTRACT_VERSION,
    MEDIA_PLUGIN_SDK_CONTRACT_VERSION,
    PLUGIN_DOCTOR_CONTRACT_VERSION,
    PLUGIN_FIXTURE_CONTRACT_VERSION,
    PLUGIN_MANIFEST_SCHEMA_VERSION,
    PLUGIN_SDK_VERSION,
    PLUGIN_TESTKIT_CONTRACT_VERSION,
    PROVIDER_PLUGIN_SDK_CONTRACT_VERSION,
    ChannelHealthRequest,
    ChannelPublishRequest,
    ChannelPublishResult,
    ChannelRuntimeContext,
    PluginCapabilityUnsupportedError,
    PluginManifest,
    PluginManifestValidationError,
    ResolvedContent,
    ResolvedMediaItem,
)
from plugin_sdk.cli import main as cli_main
from plugin_sdk.compatibility import build_compatibility_report, scan_forbidden_imports, scan_secrets
from plugin_sdk.testing import (
    FakeAnalyticsIngestion,
    FakeChannelRuntime,
    FakeClock,
    FakeExecutionReporter,
    FakeMediaLibrary,
    FakeSecretService,
    assert_no_secrets,
    assert_no_storage_references,
)


class PluginSDKPhase17Tests(unittest.TestCase):
    def test_contract_versions_are_centralized(self) -> None:
        self.assertEqual(PLUGIN_SDK_VERSION, "1.0.0")
        self.assertEqual(CHANNEL_PLUGIN_SDK_CONTRACT_VERSION, "1.0")
        self.assertEqual(PROVIDER_PLUGIN_SDK_CONTRACT_VERSION, "1.0")
        self.assertEqual(MEDIA_PLUGIN_SDK_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_MANIFEST_SCHEMA_VERSION, "1.0")
        self.assertEqual(PLUGIN_TESTKIT_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_FIXTURE_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_DOCTOR_CONTRACT_VERSION, "1.0")

    def test_public_import_boundary_exports_expected_symbols(self) -> None:
        expected = {
            "ChannelPlugin",
            "ChannelRuntime",
            "ChannelPublishRequest",
            "ChannelPublishResult",
            "ChannelMetricObservationInput",
            "ChannelHealth",
        }
        self.assertTrue(expected.issubset(set(plugin_sdk.__all__)))
        for name in expected:
            self.assertTrue(hasattr(plugin_sdk, name))

    def test_sdk_package_does_not_import_forbidden_application_layers(self) -> None:
        text = "\n".join(path.read_text() for path in Path("src/plugin_sdk").rglob("*.py"))
        for forbidden in ("from dashboard", "import dashboard", "from worker", "import worker", "from channels."):
            self.assertNotIn(forbidden, text)

    def test_valid_manifest_and_schema_file_exist(self) -> None:
        schema = json.loads(Path("schemas/plugin-manifest-v1.schema.json").read_text())
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0")
        manifest = PluginManifest.from_path("templates/channel-plugin/channel.manifest.json")
        self.assertEqual(manifest.id, "channel.example")
        self.assertEqual(manifest.distribution, "experimental")

    def test_manifest_rejects_invalid_values(self) -> None:
        base = json.loads(Path("templates/channel-plugin/channel.manifest.json").read_text())
        for key, value in [
            ("id", "Channel.Bad"),
            ("version", "one"),
            ("entrypoint", "/tmp/plugin.py"),
            ("sdk_contract_version", "2.0.0"),
        ]:
            payload = dict(base, **{key: value})
            with self.assertRaises(PluginManifestValidationError):
                plugin_sdk.validate_manifest(PluginManifest.from_dict(payload))
        with self.assertRaises(PluginManifestValidationError):
            plugin_sdk.validate_manifest(PluginManifest.from_dict(dict(base, capabilities=["channel.publish.video"])))
        with self.assertRaises(PluginManifestValidationError):
            plugin_sdk.validate_manifest(
                PluginManifest.from_dict(dict(base, secrets=[{"name": "token", "default": "real-token"}]))
            )
        custom = PluginManifest.from_dict(dict(base, capabilities=["channel.example.custom_operation"]))
        self.assertEqual(plugin_sdk.validate_manifest(custom), [])

    def test_publish_models_reject_false_success_and_redact_evidence(self) -> None:
        content = ResolvedContent("item", "rev", "checksum", body="exact body")
        request = ChannelPublishRequest(
            "ws", "acct", "pub", "plan", "target", "attempt", 1, "snap", "channel.publish.text", content
        )
        self.assertEqual(request.resolved_content.body, "exact body")
        with self.assertRaises(ValueError):
            ChannelPublishResult("published", "pub")
        result = ChannelPublishResult(
            "published",
            "pub",
            remote_uri="urn:test:1",
            verified_at=datetime.now(UTC),
            evidence={"revision_id": "rev", "snapshot_checksum": "snap"},
        )
        assert_no_secrets(result)
        assert_no_storage_references(result)

    def test_runtime_base_uses_standard_unsupported_error(self) -> None:
        runtime = plugin_sdk.ChannelRuntimeBase()
        req = ChannelPublishRequest(
            "ws",
            "acct",
            "pub",
            "plan",
            "target",
            "attempt",
            1,
            "snap",
            "channel.publish.text",
            ResolvedContent("i", "r", "c"),
        )
        with self.assertRaises(PluginCapabilityUnsupportedError):
            asyncio.run(runtime.publish(req))

    def test_least_privilege_context_enforces_permissions(self) -> None:
        context = ChannelRuntimeContext("channel.example", "ws", permissions=frozenset({"execution_reporting"}))
        context.require_permission("execution_reporting")
        with self.assertRaises(PluginCapabilityUnsupportedError):
            context.require_permission("browser_session")

    def test_fake_services_cover_secrets_media_analytics_execution(self) -> None:
        async def run() -> None:
            secrets = FakeSecretService()
            ref = await secrets.put_secret("channel.example", "ws", "acct", "token", "fixture-access-token")
            self.assertNotIn("fixture-access-token", repr(ref))
            self.assertTrue(await secrets.has_secret(ref))
            media = FakeMediaLibrary()
            selected = ResolvedMediaItem("rel", "asset", "variant", "image/png", "checksum", 0)
            async with media.materialize(selected, "publish") as materialized:
                self.assertEqual(materialized.checksum, "checksum")
            self.assertIn("cleanup", media.history)
            analytics = FakeAnalyticsIngestion()
            observation = plugin_sdk.ChannelMetricObservationInput(
                "channel.example", "likes", 1, FakeClock().now(), "pub"
            )
            result = await analytics.ingest([observation], plugin_sdk.ChannelMetricIngestionContext("ws", "acct"))
            self.assertEqual(result.accepted, 1)
            reporter = FakeExecutionReporter()
            await reporter.report_phase("preflight")
            await reporter.report_phase("payload_prepared")
            with self.assertRaises(plugin_sdk.PluginSDKError):
                await reporter.report_phase("preflight")

        asyncio.run(run())

    def test_fake_channel_runtime_supports_publish_uncertain_and_health(self) -> None:
        req = ChannelPublishRequest(
            "ws",
            "acct",
            "pub",
            "plan",
            "target",
            "attempt",
            1,
            "snap",
            "channel.publish.text",
            ResolvedContent("i", "r", "c"),
        )
        ready = asyncio.run(FakeChannelRuntime().publish(req))
        self.assertEqual(ready.status, "published")
        uncertain = asyncio.run(FakeChannelRuntime(mode="uncertain").publish(req))
        self.assertEqual(uncertain.status, "uncertain")
        health = asyncio.run(FakeChannelRuntime().health_check(ChannelHealthRequest("ws")))
        self.assertEqual(health.status, "ready")

    def test_cli_scaffolds_api_first_and_browser_based_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api_path = Path(tmp) / "api"
            browser_path = Path(tmp) / "browser"
            self.assertEqual(
                cli_main(
                    [
                        "create-channel",
                        "--id",
                        "channel.sample",
                        "--name",
                        "Sample",
                        "--mode",
                        "api-first",
                        "--capability",
                        "text",
                        "--output",
                        str(api_path),
                        "--package",
                        "channel_sample",
                    ]
                ),
                0,
            )
            self.assertEqual(
                cli_main(
                    [
                        "create-channel",
                        "--id",
                        "channel.samplebrowser",
                        "--name",
                        "Sample Browser",
                        "--mode",
                        "browser-based",
                        "--capability",
                        "text",
                        "--output",
                        str(browser_path),
                        "--package",
                        "channel_sample_browser",
                    ]
                ),
                0,
            )
            self.assertTrue(build_compatibility_report(api_path).compatible)
            browser_report = build_compatibility_report(browser_path)
            self.assertTrue(browser_report.compatible)
            self.assertIn("browser_session", browser_report.permissions)
            self.assertEqual(scan_secrets(api_path), [])
            self.assertEqual(scan_forbidden_imports(api_path), [])

    def test_cli_rejects_path_traversal_and_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "existing"
            existing.mkdir()
            (existing / "file.txt").write_text("x")
            with self.assertRaises(SystemExit):
                cli_main(
                    [
                        "create-channel",
                        "--id",
                        "channel.bad",
                        "--name",
                        "Bad",
                        "--mode",
                        "api-first",
                        "--output",
                        str(existing),
                    ]
                )
            with self.assertRaises(SystemExit):
                cli_main(
                    [
                        "create-channel",
                        "--id",
                        "channel.bad",
                        "--name",
                        "Bad",
                        "--mode",
                        "api-first",
                        "--output",
                        "../bad",
                    ]
                )

    def test_scanners_detect_forbidden_imports_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.py").write_text("from dashboard import app\naccess_token = 'abcdefghijklmnopqrstuvwxyz'\n")
            self.assertTrue(scan_forbidden_imports(root))
            self.assertTrue(scan_secrets(root))
            (root / "bad.py").write_text("from plugin_sdk import ChannelPlugin\n")
            self.assertEqual(scan_forbidden_imports(root), [])
            self.assertEqual(scan_secrets(root), [])

    def test_builtin_linkedin_and_mastodon_are_sdk_compatible(self) -> None:
        linkedin = build_compatibility_report("channels/linkedin")
        mastodon = build_compatibility_report("channels/mastodon")
        self.assertTrue(linkedin.compatible, linkedin.to_json())
        self.assertTrue(mastodon.compatible, mastodon.to_json())
        self.assertIn("browser_session", linkedin.permissions)
        self.assertIn("outbound_network", mastodon.permissions)

    def test_dashboard_plugin_api_helpers_are_safe(self) -> None:
        version = plugin_sdk_version_payload()
        self.assertEqual(version["plugin_sdk_version"], "1.0.0")
        payload = plugin_compatibility_payload()
        ids = {item["plugin_id"] for item in payload["plugins"]}
        self.assertIn("channel.linkedin", ids)
        self.assertIn("channel.mastodon", ids)
        for item in payload["plugins"]:
            public = json.dumps(item).lower()
            self.assertNotIn("access_token", public)
            self.assertNotIn("client_secret", public)
            self.assertNotIn("/home/", public)

    def test_template_contains_no_builtin_channel_or_provider_imports(self) -> None:
        text = "\n".join(path.read_text() for path in Path("templates/channel-plugin").rglob("*.py"))
        self.assertNotIn("channels.linkedin", text)
        self.assertNotIn("channels.mastodon", text)
        self.assertNotIn("AutoBrowserProvider", text)
        self.assertNotIn("Playwright", text)


if __name__ == "__main__":
    unittest.main()
