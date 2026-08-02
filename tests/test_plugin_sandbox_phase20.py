from __future__ import annotations

import json
import platform
import sys
import tempfile
import unittest
from pathlib import Path

from dashboard import (
    plugin_sandbox_health_payload,
    plugin_sandbox_plan_payload,
    plugin_sandbox_platform_payload,
)
from src.core.plugin_sandbox import (
    PLUGIN_SANDBOX_ATTESTATION_CONTRACT_VERSION,
    PLUGIN_SANDBOX_FILESYSTEM_CONTRACT_VERSION,
    PLUGIN_SANDBOX_FRAMEWORK_VERSION,
    PLUGIN_SANDBOX_NETWORK_CONTRACT_VERSION,
    PLUGIN_SANDBOX_PLAN_CONTRACT_VERSION,
    PLUGIN_SANDBOX_PLATFORM_CONTRACT_VERSION,
    PLUGIN_SANDBOX_POLICY_CONTRACT_VERSION,
    PLUGIN_SANDBOX_SYSCALL_CONTRACT_VERSION,
    PLUGIN_SANDBOX_VIOLATION_CONTRACT_VERSION,
    PluginHostProcessSpec,
    PluginSandboxActivationBlockedError,
    PluginSandboxIntegrityService,
    PluginSandboxPolicyError,
    PluginSandboxViolationStore,
    SandboxCompilationContext,
    SandboxPolicyCompiler,
    UnsupportedPluginSandboxController,
    classify_violation,
    select_sandbox_controller,
)
from src.core.plugin_sandbox.policies import (
    BROKER_PERMISSION_MAP,
    LINUX_REQUIRED_CONTROLS,
    MACOS_REQUIRED_CONTROLS,
    SENSITIVE_DENY_PATH_SUMMARIES,
    WINDOWS_REQUIRED_CONTROLS,
)
from src.plugin_sdk.cli import main as plugin_sdk_main

ROOT = Path(__file__).resolve().parents[1]


class PluginSandboxPhase20Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.compiler = SandboxPolicyCompiler()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def build_policy(self, *, platform_name: str = "linux", permissions: list[str] | None = None):
        return self.compiler.build_policy(
            plugin_id="channel.example",
            plugin_version="0.1.0",
            distribution_status="community",
            permissions=permissions
            or [
                "account_configuration",
                "execution_reporting",
                "outbound_network",
                "secret_storage",
                "media_materialization",
                "browser_session",
            ],
            capabilities=["channel.health", "channel.publish.text", "channel.metrics.collect"],
            platform_name=platform_name,
        )

    def context(self) -> SandboxCompilationContext:
        return SandboxCompilationContext(
            install_record_id="install_1",
            environment_id="env_1",
            artifact_checksum="sha256:artifact",
            environment_checksum="sha256:environment",
        )

    def test_contract_versions(self) -> None:
        self.assertEqual(PLUGIN_SANDBOX_FRAMEWORK_VERSION, "0.1.0")
        self.assertEqual(PLUGIN_SANDBOX_POLICY_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_SANDBOX_PLAN_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_SANDBOX_ATTESTATION_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_SANDBOX_FILESYSTEM_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_SANDBOX_NETWORK_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_SANDBOX_SYSCALL_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_SANDBOX_VIOLATION_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_SANDBOX_PLATFORM_CONTRACT_VERSION, "1.0")

    def test_policy_maps_permissions_to_broker_only_capabilities(self) -> None:
        policy = self.build_policy()
        self.assertEqual(policy.network_policy["direct"], "deny")
        self.assertEqual(policy.network_policy["brokered_http"], "allowed")
        self.assertEqual(policy.metadata["outbound_network"], "brokered_http_only")
        self.assertEqual(BROKER_PERMISSION_MAP["outbound_network"], ["host.http.request"])
        self.assertEqual(
            BROKER_PERMISSION_MAP["browser_session"],
            ["host.browser.open_session", "host.browser.invoke", "host.browser.close_session"],
        )
        self.assertIn("content", policy.filesystem_policy["denied"])
        self.assertIn("drafts", policy.filesystem_policy["denied"])
        self.assertIn(".ssh", policy.filesystem_policy["denied"])
        self.assertTrue(policy.identity_policy["no_new_privs"])
        self.assertTrue(policy.identity_policy["drop_capabilities"])

    def test_unsupported_direct_permissions_and_subprocess_are_blocked(self) -> None:
        for permission in ["direct_network", "filesystem_all", "home_access", "arbitrary_subprocess"]:
            with self.subTest(permission=permission):
                with self.assertRaises(PluginSandboxPolicyError):
                    self.build_policy(permissions=[permission])
        with self.assertRaises(PluginSandboxPolicyError):
            self.build_policy(permissions=["subprocess"])

    def test_plan_is_bound_to_policy_environment_and_artifact(self) -> None:
        controller = select_sandbox_controller(development_override=False)
        policy = self.build_policy(platform_name=platform.system().lower())
        plan = controller.compile_plan(policy, self.context())
        self.assertEqual(plan.plugin_id, "channel.example")
        self.assertEqual(plan.plugin_version, "0.1.0")
        self.assertEqual(plan.policy_checksum, policy.checksum)
        self.assertEqual(plan.environment_checksum, "sha256:environment")
        self.assertEqual(plan.artifact_checksum, "sha256:artifact")
        self.assertEqual(plan.network_rules[0]["direct"], "deny")
        self.assertIn({"name": "plugin_temp", "mode": "rw,noexec,nosuid,nodev"}, plan.filesystem_mounts)
        self.assertIn(plan.expected_attestation["status"], {"enforced", "incomplete"})

    def test_linux_policy_declares_required_baseline(self) -> None:
        policy = self.build_policy(platform_name="linux")
        self.assertTrue(set(LINUX_REQUIRED_CONTROLS).issubset(policy.required_controls))
        for control in [
            "user_namespace",
            "mount_namespace",
            "pid_namespace",
            "ipc_namespace",
            "uts_namespace",
            "network_namespace",
            "seccomp",
            "landlock",
            "no_new_privs",
        ]:
            self.assertIn(control, policy.required_controls)

    def test_windows_and_macos_fail_closed_requirements(self) -> None:
        windows = self.build_policy(platform_name="windows")
        macos = self.build_policy(platform_name="darwin")
        self.assertTrue(set(WINDOWS_REQUIRED_CONTROLS).issubset(windows.required_controls))
        self.assertTrue(set(MACOS_REQUIRED_CONTROLS).issubset(macos.required_controls))
        self.assertIn("appcontainer", windows.required_controls)
        self.assertIn("job_object", windows.required_controls)
        self.assertIn("app_sandbox_entitlement", macos.required_controls)
        self.assertIn("signed_helper", macos.required_controls)

    def test_unsupported_controller_blocks_without_development_override(self) -> None:
        controller = UnsupportedPluginSandboxController(development_override=False)
        policy = self.build_policy(platform_name="unknown")
        plan = controller.compile_plan(policy, self.context())
        spec = PluginHostProcessSpec(argv=["python", "-c", "print('x')"], cwd=str(self.root), env={})
        with self.assertRaises(PluginSandboxActivationBlockedError):
            controller.launch(plan, spec)

    def test_development_override_is_explicit_and_attested(self) -> None:
        controller = UnsupportedPluginSandboxController(development_override=True)
        policy = self.build_policy(platform_name="unknown")
        plan = controller.compile_plan(policy, self.context())
        spec = PluginHostProcessSpec(
            argv=[sys.executable, "-c", "import time; time.sleep(0.05)"],
            cwd=str(self.root),
            env={},
        )
        process = controller.launch(plan, spec)
        try:
            attestation = controller.attest(process, plan)
            self.assertEqual(attestation.status, "development_override")
            self.assertIn("Development override", " ".join(attestation.warnings))
        finally:
            controller.terminate(process)

    def test_violation_classification_and_redaction(self) -> None:
        store = PluginSandboxViolationStore(self.root / "violations")
        self.assertEqual(classify_violation("filesystem", "read_content"), "expected_denial")
        self.assertEqual(classify_violation("network", "direct_tcp"), "policy_violation")
        self.assertEqual(classify_violation("filesystem", "docker_socket"), "escape_attempt")
        record = store.record(
            plugin_id="channel.example",
            plugin_version="0.1.0",
            host_id="host_1",
            process_instance_id="proc_1",
            sandbox_plan_id="plan_1",
            platform="linux",
            control="filesystem",
            operation="open",
            action="deny",
            blocked=True,
            severity="escape_attempt",
            safe_resource_summary=".ssh",
            mutation_state="mutation_started",
        )
        self.assertEqual(record.safe_resource_summary, ".ssh")
        self.assertEqual(record.mutation_state, "mutation_started")
        self.assertNotIn("/home/", json.dumps(record.__dict__))

    def test_integrity_detects_missing_attestation_and_mismatches(self) -> None:
        plan = self.compiler.compile_plan(
            self.build_policy(),
            self.context(),
            select_sandbox_controller(development_override=False).inspect_platform(),
        )
        integrity = PluginSandboxIntegrityService(self.root / "sandbox")
        findings = integrity.scan(plans=[plan])
        self.assertTrue(any(item["code"] == "plugin_sandbox.integrity.plan_incomplete" for item in findings))

    def test_dashboard_sandbox_payloads_are_safe(self) -> None:
        health = plugin_sandbox_health_payload()
        platform_payload = plugin_sandbox_platform_payload()
        plans = plugin_sandbox_plan_payload()
        self.assertIn("framework_version", health)
        self.assertIn("platform", platform_payload)
        self.assertIn("plans", plans)
        rendered = json.dumps({"health": health, "platform": platform_payload, "plans": plans})
        self.assertNotIn("/home/", rendered)
        self.assertNotIn("malware-free", rendered.lower())
        self.assertNotIn("fully trusted", rendered.lower())

    def test_cli_sandbox_commands(self) -> None:
        self.assertEqual(plugin_sdk_main(["sandbox", "status"]), 0)
        self.assertEqual(plugin_sdk_main(["sandbox", "platform"]), 0)
        with self.assertRaises(SystemExit):
            plugin_sdk_main(["sandbox", "plan", "channel.example==0.1.0"])
        self.assertEqual(plugin_sdk_main(["sandbox", "integrity"]), 0)
        self.assertIn(plugin_sdk_main(["sandbox", "doctor"]), {0, 1})

    def test_fixture_scenarios_cover_security_boundaries(self) -> None:
        scenarios = {path.stem for path in (ROOT / "integrations/plugin_sandbox/scenarios").glob("*.json")}
        expected = {
            "healthy_minimal_plugin",
            "read_host_home",
            "read_repository",
            "read_content",
            "read_drafts",
            "direct_tcp",
            "direct_udp",
            "localhost_connect",
            "listening_socket",
            "unix_socket",
            "docker_socket",
            "ssh_agent_socket",
            "subprocess",
            "ptrace",
            "namespace_escape",
            "mount_attempt",
            "capability_escalation",
            "bpf_attempt",
            "keyring_attempt",
            "valid_http_callback",
            "valid_browser_callback",
            "valid_media_transfer",
            "valid_state_callback",
        }
        self.assertTrue(expected.issubset(scenarios))

    def test_boundary_searches(self) -> None:
        phase20_files = [ROOT / "src/core/plugin_sandbox", ROOT / "integrations/plugin_sandbox"]
        text = "\n".join(path.read_text() for root in phase20_files for path in root.rglob("*.py"))
        self.assertNotIn("shell=True", text)
        self.assertNotIn("pickle", text)
        self.assertNotIn("marshal", text)
        self.assertNotIn("yaml.load", text)
        self.assertNotIn("sandbox-exec", text)
        self.assertNotIn("os.system", text)
        self.assertIn("shell=False", text)

    def test_sensitive_denied_summaries_include_user_owned_areas(self) -> None:
        self.assertIn("content", SENSITIVE_DENY_PATH_SUMMARIES)
        self.assertIn("drafts", SENSITIVE_DENY_PATH_SUMMARIES)
        self.assertIn(".ssh", SENSITIVE_DENY_PATH_SUMMARIES)

    def test_no_framework_contract_changes(self) -> None:
        import subprocess

        result = subprocess.run(
            [
                "git",
                "diff",
                "--",
                "src/core/browser",
                "src/core/media",
                "src/core/execution",
                "src/core/scheduling",
                "src/core/analytics",
                "src/plugin_sdk/contracts.py",
                "src/core/plugin_distribution/contracts.py",
                "src/core/plugin_host/contracts.py",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
