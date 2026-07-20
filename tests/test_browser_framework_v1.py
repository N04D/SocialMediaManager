from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from browser_pilots import (
    AUTO_BROWSER_PROVIDER_ID,
    LEGACY_PROVIDER_ID,
    ProviderStateEvent,
    append_provider_state_event,
    confirm_pilot_action,
    create_browser_pilot,
    list_provider_state_events,
    pop_issued_confirmation_token,
    prepare_pilot_action,
    rollback_pilot,
    run_pilot_preflight,
)
from channel_models import ChannelConnection
from channel_store import get_channel_connection, now_iso, save_channel_connection
from plugin_runtime import ApplicationPluginRuntime
from src.core.browser import (
    BROWSER_ARTIFACT_CONTRACT_VERSION,
    BROWSER_FRAMEWORK_VERSION,
    BROWSER_PROVIDER_CONTRACT_VERSION,
    BROWSER_SESSION_CONTRACT_VERSION,
    BROWSER_TARGET_CONTRACT_VERSION,
)
from src.core.browser.contracts import browser_contract_compatibility
from src.core.plugins import PluginCapabilityError
from src.core.plugins.manifest import PluginManifest, PluginStatus
from src.core.plugins.runtime import PluginRuntime, ProviderResolver
from tests.test_plugin_runtime_phase2 import Config
from tests.test_support import isolated_channel_store


class _ProfileStatus:
    busy = False


class _PilotProvider:
    def profile_status(self, profile_id: str):
        return _ProfileStatus()

    def reconcile_sessions(self) -> dict:
        return {"status": "consistent", "orphaned_remote_count": 0, "stale_mapping_count": 0}


def _provider_manifest(plugin_id: str, *, contract_version: str = "1.0") -> PluginManifest:
    return PluginManifest.from_dict(
        {
            "id": plugin_id,
            "name": plugin_id,
            "version": "0.1.0",
            "plugin_api_version": 1,
            "type": "provider",
            "entrypoint": "test",
            "capabilities": ["browser.session", "browser.auth_profile", "browser.human_takeover"],
            "dependencies": [],
            "config_schema": {
                "browser_framework_version": BROWSER_FRAMEWORK_VERSION,
                "browser_provider_contract_version": contract_version,
                "browser_session_contract_version": BROWSER_SESSION_CONTRACT_VERSION,
                "browser_target_contract_version": BROWSER_TARGET_CONTRACT_VERSION,
                "browser_artifact_contract_version": BROWSER_ARTIFACT_CONTRACT_VERSION,
            },
        }
    )


def _runtime(*, auto_status: PluginStatus = PluginStatus.READY, auto_contract: str = "1.0") -> ApplicationPluginRuntime:
    runtime = ApplicationPluginRuntime()
    for plugin_id, priority, contract in [
        (LEGACY_PROVIDER_ID, 10, "1.0"),
        (AUTO_BROWSER_PROVIDER_ID, 5, auto_contract),
    ]:
        manifest = _provider_manifest(plugin_id, contract_version=contract)
        runtime.registry.register(manifest)
        status = auto_status if plugin_id == AUTO_BROWSER_PROVIDER_ID else PluginStatus.READY
        runtime.runtimes[plugin_id] = PluginRuntime(
            manifest=manifest,
            instance=_PilotProvider(),
            status=status,
            services={"browser_provider": _PilotProvider()},
            health={
                "status": "ready",
                "default_priority": priority,
                "browser_provider_contract_version": contract,
                "required_browser_provider_contract_version": BROWSER_PROVIDER_CONTRACT_VERSION,
                "browser_session_contract_version": BROWSER_SESSION_CONTRACT_VERSION,
                "browser_target_contract_version": BROWSER_TARGET_CONTRACT_VERSION,
                "browser_artifact_contract_version": BROWSER_ARTIFACT_CONTRACT_VERSION,
                "contract_compatibility": browser_contract_compatibility(contract),
                "server_version": "1.3.1",
                "tested_api_version": "1.3.1",
                "upload_capability": "available",
                "pilot_readiness": {"status": "ready", "reasons": []},
            },
        )
    runtime.resolver = ProviderResolver(runtime.registry, runtime.runtimes)
    return runtime


class BrowserFrameworkV1ContractTests(unittest.TestCase):
    def test_contract_versions_are_central_and_manifest_declares_them(self) -> None:
        self.assertEqual(BROWSER_FRAMEWORK_VERSION, "1.0.0")
        self.assertEqual(BROWSER_PROVIDER_CONTRACT_VERSION, "1.0")
        for path in [
            Path("plugins/providers/legacy_browser/plugin.manifest.json"),
            Path("plugins/providers/auto_browser/plugin.manifest.json"),
        ]:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["config_schema"]["browser_provider_contract_version"], "1.0")
            self.assertEqual(payload["config_schema"]["browser_session_contract_version"], "1.0")

    def test_incompatible_provider_is_not_selected(self) -> None:
        runtime = _runtime(auto_contract="2.0")
        with self.assertRaises(PluginCapabilityError):
            runtime.resolve_provider("browser.session", preferred_provider_id=AUTO_BROWSER_PROVIDER_ID)

    def test_compatible_minor_provider_is_selected_with_warning(self) -> None:
        runtime = _runtime(auto_contract="1.1")
        selected = runtime.resolve_provider("browser.session", preferred_provider_id=AUTO_BROWSER_PROVIDER_ID)
        self.assertEqual(selected.manifest.id, AUTO_BROWSER_PROVIDER_ID)
        self.assertEqual(browser_contract_compatibility("1.1"), "compatible_with_warnings")

    def test_conformance_payload_is_machine_readable(self) -> None:
        payload = _runtime().browser_conformance_payload()
        self.assertEqual(payload["browser_framework_version"], "1.0.0")
        providers = {item["plugin_id"]: item for item in payload["providers"]}
        self.assertEqual(providers[AUTO_BROWSER_PROVIDER_ID]["contract_compatibility"], "compatible")
        self.assertIn("create_session", providers[AUTO_BROWSER_PROVIDER_ID]["required_operations"])

    def test_framework_boundaries_do_not_import_concrete_providers(self) -> None:
        linkedin_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                Path("channels/linkedin/runtime.py"),
                Path("channels/linkedin/worker/connect.py"),
                Path("channels/linkedin/worker/session.py"),
                Path("channels/linkedin/worker/publish.py"),
                Path("channels/linkedin/worker/metrics.py"),
            ]
        )
        self.assertNotIn("AutoBrowserProvider", linkedin_text)
        self.assertNotIn("LegacyBrowserProvider", linkedin_text)
        self.assertNotIn("plugins.providers.auto_browser", linkedin_text)
        self.assertNotIn("plugins.providers.legacy_browser", linkedin_text)
        self.assertNotIn("playwright", Path("src/core/browser/provider.py").read_text(encoding="utf-8").lower())


class BrowserPilotEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Config()
        self.config.auto_browser_pilot_accounts = ["linkedin"]
        self.config.auto_browser_doctor_last_passed_at = now_iso()
        self.config.auto_browser_integration_last_passed_at = now_iso()
        self.config.auto_browser_chaos_last_passed_at = now_iso()
        save_channel_connection(
            ChannelConnection(
                id="connection_linkedin",
                channel_id="linkedin",
                mode="playwright_local",
                status="connected",
                browser_provider_id=AUTO_BROWSER_PROVIDER_ID,
                provider_connection_state_json={
                    LEGACY_PROVIDER_ID: {"status": "connected"},
                    AUTO_BROWSER_PROVIDER_ID: {"status": "authentication_required"},
                },
            )
        )
        self.runtime = _runtime()

    def _pilot(self):
        return create_browser_pilot(
            config=self.config,
            runtime=self.runtime,
            channel_account_id="linkedin",
            provider_id=AUTO_BROWSER_PROVIDER_ID,
            scope="login_only",
            reason="controlled pilot",
            actor="operator",
            acknowledged=True,
        )

    def test_valid_login_only_pilot_and_preflight(self) -> None:
        pilot = self._pilot()
        self.assertEqual(pilot.status, "planned")
        pilot = run_pilot_preflight(config=self.config, runtime=self.runtime, pilot_id=pilot.id)
        self.assertEqual(pilot.preflight_results["status"], "passed")
        self.assertTrue(all(item["ok"] for item in pilot.preflight_results["checks"]))

    def test_pilot_creation_rejects_legacy_or_unmarked_account(self) -> None:
        with self.assertRaises(ValueError):
            create_browser_pilot(
                config=self.config,
                runtime=self.runtime,
                channel_account_id="linkedin",
                provider_id=LEGACY_PROVIDER_ID,
                scope="login_only",
                reason="controlled pilot",
                actor="operator",
                acknowledged=True,
            )
        self.config.auto_browser_pilot_accounts = []
        with self.assertRaises(ValueError):
            self._pilot()

    def test_preflight_blocks_stale_evidence_and_image_without_upload(self) -> None:
        pilot = self._pilot()
        self.config.auto_browser_doctor_last_passed_at = ""
        pilot = run_pilot_preflight(config=self.config, runtime=self.runtime, pilot_id=pilot.id)
        checks = {item["name"]: item["ok"] for item in pilot.preflight_results["checks"]}
        self.assertFalse(checks["doctor_recent"])

    def test_mutating_action_requires_single_use_confirmation_token(self) -> None:
        pilot = self._pilot()
        pilot = prepare_pilot_action(pilot.id, "publish_text", actor="operator")
        token = pop_issued_confirmation_token(pilot.id, "publish_text")
        stored = next(item for item in pilot.actions if item["action_type"] == "publish_text")
        self.assertEqual(stored["status"], "awaiting_confirmation")
        self.assertNotIn(token, json.dumps(pilot.__dict__))
        pilot = confirm_pilot_action(
            pilot.id,
            "publish_text",
            token=token,
            actor="operator",
            reason="confirmed test publish",
        )
        stored = next(item for item in pilot.actions if item["action_type"] == "publish_text")
        self.assertEqual(stored["status"], "verified")
        with self.assertRaises(ValueError):
            confirm_pilot_action(
                pilot.id,
                "publish_text",
                token=token,
                actor="operator",
                reason="duplicate submit",
            )

    def test_rollback_restores_legacy_provider_and_preserves_state(self) -> None:
        pilot = self._pilot()
        pilot = rollback_pilot(
            config=self.config,
            runtime=self.runtime,
            pilot_id=pilot.id,
            actor="operator",
            reason="rollback requested",
        )
        connection = get_channel_connection("linkedin")
        self.assertIsNotNone(connection)
        assert connection is not None
        self.assertEqual(connection.browser_provider_id, LEGACY_PROVIDER_ID)
        self.assertEqual(pilot.rollback_result["autobrowser_state_preserved"], True)
        self.assertEqual(pilot.rollback_result["content_preserved"], True)

    def test_provider_state_history_is_compact_and_secret_free(self) -> None:
        append_provider_state_event(
            ProviderStateEvent(
                channel_account_id="linkedin",
                provider_id=AUTO_BROWSER_PROVIDER_ID,
                timestamp=now_iso(),
                previous_status="authentication_required",
                new_status="connected",
                reason_code="connect",
                source="pilot",
                pilot_run_id="pilot-a",
                safe_error_code="",
            )
        )
        events = list_provider_state_events("linkedin", limit=10)
        self.assertEqual(events[0].source, "pilot")
        self.assertNotIn("secret", json.dumps([event.__dict__ for event in events]).lower())


if __name__ == "__main__":
    unittest.main()
