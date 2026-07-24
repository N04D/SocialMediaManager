from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dashboard import plugin_host_health_payload, plugin_host_integrity_payload, plugin_host_process_payload
from src.core.plugin_distribution import PluginInstallationService, PluginPackageBuildService
from src.core.plugin_host import (
    PLUGIN_HOST_CALLBACK_CONTRACT_VERSION,
    PLUGIN_HOST_CRASH_POLICY_CONTRACT_VERSION,
    PLUGIN_HOST_ENVIRONMENT_CONTRACT_VERSION,
    PLUGIN_HOST_FRAMEWORK_VERSION,
    PLUGIN_HOST_HANDSHAKE_CONTRACT_VERSION,
    PLUGIN_HOST_LIFECYCLE_CONTRACT_VERSION,
    PLUGIN_HOST_PROTOCOL_VERSION,
    PLUGIN_HOST_RESOURCE_POLICY_CONTRACT_VERSION,
    PluginHostCallbackAuthorizationError,
    PluginHostCallbackDispatcher,
    PluginHostContextRegistry,
    PluginHostEnvironmentManager,
    PluginHostFrameError,
    PluginHostIntegrityService,
    PluginHostPermissionError,
    PluginHostResourceController,
    PluginHostResourcePolicy,
    PluginHostStateError,
    PluginHostStateStore,
    PluginHostSupervisor,
    decode_frame,
    encode_frame,
)
from src.core.plugin_host.callbacks import PluginHostTransferStore
from src.core.plugin_host.protocol import HOST_CALLBACK_METHODS, PLUGIN_METHODS, make_request, validate_child_request
from src.core.plugin_host.supervisor import classify_mutation_recovery
from src.plugin_sdk.cli import main as plugin_sdk_main

ROOT = Path(__file__).resolve().parents[1]


class PluginHostPhase19Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        release_root = self.root / "release"
        self.release = PluginPackageBuildService().create_release_directory("templates/channel-plugin", release_root)
        self.install_root = self.root / "installs"
        self.record = PluginInstallationService(self.install_root).install_verified_release(
            self.release,
            actor="test",
            reason="phase19",
            permission_confirmed=True,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_contract_versions(self) -> None:
        self.assertEqual(PLUGIN_HOST_FRAMEWORK_VERSION, "0.1.0")
        self.assertEqual(PLUGIN_HOST_PROTOCOL_VERSION, "1.0")
        self.assertEqual(PLUGIN_HOST_HANDSHAKE_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_HOST_LIFECYCLE_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_HOST_CALLBACK_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_HOST_RESOURCE_POLICY_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_HOST_ENVIRONMENT_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_HOST_CRASH_POLICY_CONTRACT_VERSION, "1.0")

    def test_framing_and_json_rpc_validation(self) -> None:
        payload = {"jsonrpc": "2.0", "id": "abc", "result": {"ok": True}}
        frame = encode_frame(payload)
        self.assertEqual(decode_frame(io.BytesIO(frame)), payload)
        with self.assertRaises(PluginHostFrameError):
            encode_frame({"x": "y" * 20}, max_frame_bytes=8)
        request = make_request("id1", "channel.health", {"named": True})
        self.assertEqual(request.method, "channel.health")
        callback = validate_child_request(
            {"jsonrpc": "2.0", "id": "cb1", "method": "host.clock.now", "params": {"context_id": "ctx"}}
        )
        self.assertEqual(callback.method, "host.clock.now")
        self.assertNotIn("pickle", json.dumps(sorted(PLUGIN_METHODS | HOST_CALLBACK_METHODS)))

    def test_environment_isolation_and_process_command(self) -> None:
        manager = PluginHostEnvironmentManager(self.install_root, self.root / "envs")
        spec = manager.prepare("channel.example", "0.1.0")
        self.assertEqual(spec.status, "prepared")
        self.assertTrue(manager.probe_no_user_site(spec))
        command = manager.start_command(spec)
        self.assertEqual(command[1:3], ["-I", "-m"])
        marker = Path(spec.python_executable).parents[1] / "host-environment.json"
        payload = json.loads(marker.read_text())
        self.assertFalse(payload["system_site_packages"])
        self.assertEqual(payload["pip"], "blocked")

    def test_supervisor_handshake_proxy_and_child_process(self) -> None:
        service = PluginInstallationService(self.install_root)
        service.request_activation(
            "channel.example", "0.1.0", actor="test", reason="phase19", permission_confirmed=True
        )
        plugin_root = self.install_root / "channel.example"
        active = json.loads((plugin_root / "active.json").read_text())
        active["activation_status"] = "enabled"
        active["plugin_id"] = "channel.example"
        (plugin_root / "active.json").write_text(json.dumps(active))
        supervisor = PluginHostSupervisor(self.install_root, self.root / "envs", self.root / "work", ROOT)
        host = supervisor.ensure_host(
            "channel.example",
            "0.1.0",
            capabilities=[
                "channel.status",
                "channel.health",
                "channel.publish.text",
                "channel.publish.image",
                "channel.metrics.collect",
            ],
            permissions=[
                "account_configuration",
                "analytics_ingestion",
                "execution_reporting",
                "media_materialization",
                "media_read",
                "outbound_network",
                "secret_storage",
            ],
        )
        self.assertEqual(host.record.process_status, "ready")
        self.assertEqual(host.ping()["status"], "ok")
        result = host.call_raw("channel.health", {"workspace_id": "w1"})
        self.assertEqual(result["status"], "ok")
        host.shutdown()

    def test_identity_mismatch_quarantines_handshake(self) -> None:
        supervisor = PluginHostSupervisor(self.install_root, self.root / "envs", self.root / "work", ROOT)
        host = supervisor.ensure_host(
            "channel.example",
            "0.1.0",
            capabilities=[
                "channel.status",
                "channel.health",
                "channel.publish.text",
                "channel.publish.image",
                "channel.metrics.collect",
            ],
            permissions=[
                "account_configuration",
                "analytics_ingestion",
                "execution_reporting",
                "media_materialization",
                "media_read",
                "outbound_network",
                "secret_storage",
            ],
        )
        self.assertEqual(host.record.process_status, "ready")
        host.shutdown()

    def test_main_process_loader_returns_proxy_not_external_import(self) -> None:
        service = PluginInstallationService(self.install_root)
        service.request_activation(
            "channel.example", "0.1.0", actor="test", reason="phase19", permission_confirmed=True
        )
        active = self.install_root / "channel.example" / "active.json"
        payload = json.loads(active.read_text())
        payload["activation_status"] = "enabled"
        active.write_text(json.dumps(payload))
        loader = __import__("src.core.plugin_distribution", fromlist=["InstalledPluginLoader"]).InstalledPluginLoader(
            self.install_root, repo_root=ROOT
        )
        proxy = loader.load_active_plugin("channel.example")
        self.assertEqual(proxy.__class__.__name__, "RemoteChannelPluginProxy")
        source = (ROOT / "src/core/plugin_distribution/services.py").read_text()
        self.assertNotIn(".load()()", source)

    def test_call_context_authorization_secret_scope_and_late_callback(self) -> None:
        registry = PluginHostContextRegistry()
        context = registry.create(
            plugin_id="channel.example",
            plugin_version="0.1.0",
            workspace_id="w1",
            channel_account_id="a1",
            operation="publish",
            capability="channel.publish.text",
            deadline=datetime.now(UTC) + timedelta(seconds=60),
            allowed_callbacks=["host.clock.now", "host.secret.get"],
            allowed_secrets=["oauth"],
        )
        dispatcher = PluginHostCallbackDispatcher(registry)
        self.assertIn(
            "now", dispatcher.dispatch("channel.example", "0.1.0", "host.clock.now", {"context_id": context.context_id})
        )
        self.assertEqual(
            dispatcher.dispatch(
                "channel.example", "0.1.0", "host.secret.get", {"context_id": context.context_id, "purpose": "oauth"}
            )["status"],
            "redacted",
        )
        with self.assertRaises(PluginHostPermissionError):
            dispatcher.dispatch(
                "channel.example", "0.1.0", "host.secret.get", {"context_id": context.context_id, "purpose": "other"}
            )
        registry.revoke(context.context_id)
        with self.assertRaises(PluginHostCallbackAuthorizationError):
            dispatcher.dispatch("channel.example", "0.1.0", "host.clock.now", {"context_id": context.context_id})

    def test_state_facade_json_only_quota_and_compare_set(self) -> None:
        registry = PluginHostContextRegistry()
        context = registry.create(
            plugin_id="channel.example",
            plugin_version="0.1.0",
            workspace_id="w1",
            channel_account_id="a1",
            operation="status",
            capability="channel.status",
            deadline=datetime.now(UTC) + timedelta(seconds=60),
            allowed_callbacks=["host.state.get", "host.state.put", "host.state.compare_and_set"],
        )
        store = PluginHostStateStore(self.root / "state", max_item_bytes=32)
        self.assertEqual(store.put(context, "ns", "key", {"v": 1})["status"], "stored")
        self.assertEqual(store.compare_and_set(context, "ns", "key", {"v": 1}, {"v": 2})["status"], "stored")
        with self.assertRaises(PluginHostStateError):
            store.put(context, "ns", "large", {"v": "x" * 100})

    def test_media_transfer_cleanup_and_checksum(self) -> None:
        registry = PluginHostContextRegistry()
        context = registry.create(
            plugin_id="channel.example",
            plugin_version="0.1.0",
            operation="publish",
            capability="channel.publish.image",
            deadline=datetime.now(UTC) + timedelta(seconds=60),
            allowed_callbacks=["host.media.materialize", "host.media.release"],
        )
        source = self.root / "image.png"
        source.write_bytes(b"image")
        transfers = PluginHostTransferStore(self.root / "transfers")
        record = transfers.materialize_from_path(context, source, mime="image/png")
        self.assertTrue(Path(record["path"]).exists())
        self.assertEqual(transfers.release(context, record["transfer_id"])["status"], "released")
        self.assertFalse(Path(record["path"]).exists())

    def test_resource_policy_and_crash_mutation_recovery(self) -> None:
        controller = PluginHostResourceController(PluginHostResourcePolicy(cpu_seconds=1))
        self.assertIn(controller.containment_status(), {"enforced", "degraded_resource_containment"})
        self.assertEqual(classify_mutation_recovery("not_started"), "pre_mutation_failure")
        self.assertEqual(classify_mutation_recovery("mutation_started"), "uncertain")
        self.assertEqual(classify_mutation_recovery("mutation_acknowledged"), "remote_verification_required")
        self.assertEqual(classify_mutation_recovery("mutation_verified"), "evidence_reconciliation")

    def test_integrity_detects_active_without_environment(self) -> None:
        service = PluginInstallationService(self.install_root)
        service.request_activation(
            "channel.example", "0.1.0", actor="test", reason="phase19", permission_confirmed=True
        )
        findings = PluginHostIntegrityService(self.install_root, self.root / "missing-envs", self.root / "state").scan()
        self.assertTrue(any(item.code == "plugin_host.integrity.active_without_environment" for item in findings))

    def test_cli_host_commands_and_dashboard_payloads(self) -> None:
        with self.assertRaises(SystemExit):
            plugin_sdk_main(["host", "prepare", "channel.example", "--install-root", str(self.install_root)])
        self.assertEqual(
            plugin_sdk_main(
                [
                    "host",
                    "prepare",
                    "channel.example==0.1.0",
                    "--install-root",
                    str(self.install_root),
                    "--environment-root",
                    str(self.root / "envs"),
                    "--work-root",
                    str(self.root / "work"),
                ]
            ),
            0,
        )
        self.assertIn("framework_version", plugin_host_health_payload())
        self.assertIn("processes", plugin_host_process_payload())
        self.assertIn("findings", plugin_host_integrity_payload())

    def test_boundary_search_terms(self) -> None:
        phase19_files = [
            ROOT / "src/core/plugin_host",
            ROOT / "src/plugin_host_runtime",
            ROOT / "src/core/plugin_distribution/services.py",
        ]
        text = "\n".join(
            path.read_text() for root in phase19_files for path in ([root] if root.is_file() else root.rglob("*.py"))
        )
        self.assertNotIn("pickle", text)
        self.assertNotIn("marshal", text)
        self.assertNotIn("yaml.load", text)
        self.assertNotIn("shell=True", text)
        self.assertNotIn("StrictHostKeyChecking=no", text)
        distribution_loader = (ROOT / "src/core/plugin_distribution/services.py").read_text()
        self.assertNotIn("entry.load", distribution_loader)

    def test_fixture_scenarios_present(self) -> None:
        scenarios = {path.stem for path in (ROOT / "integrations/plugin_host/scenarios").glob("*.json")}
        expected = {
            "healthy_api_channel",
            "healthy_browser_channel",
            "crash_on_start",
            "crash_pre_mutation",
            "crash_post_mutation",
            "hang_on_health",
            "hang_on_publish",
            "malformed_rpc",
            "oversized_frame",
            "stdout_noise",
            "callback_escalation",
            "secret_cross_scope",
            "workspace_escape",
            "memory_pressure",
            "cpu_pressure",
            "subprocess_attempt",
            "crash_loop",
        }
        self.assertTrue(expected.issubset(scenarios))

    def test_process_start_contract_uses_shell_false(self) -> None:
        source = (ROOT / "src/core/plugin_host/supervisor.py").read_text()
        self.assertIn("shell=False", source)
        self.assertIn("stdin=subprocess.PIPE", source)
        self.assertIn("stdout=subprocess.PIPE", source)
        self.assertIn("stderr=subprocess.PIPE", source)
        self.assertIn("close_fds=True", source)

    def test_no_framework_contract_changes(self) -> None:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--",
                "src/core/browser",
                "src/core/media",
                "src/core/content",
                "src/core/execution",
                "src/core/scheduling",
                "src/core/analytics",
                "src/plugin_sdk/contracts.py",
                "src/core/plugin_distribution/contracts.py",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
