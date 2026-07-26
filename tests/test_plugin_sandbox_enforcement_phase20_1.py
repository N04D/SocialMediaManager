from __future__ import annotations

import json
import platform
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.core.plugin_distribution import PluginInstallationService, PluginPackageBuildService
from src.core.plugin_host import PluginHostSupervisor
from src.core.plugin_sandbox import (
    PluginHostProcessSpec,
    SandboxCompilationContext,
    SandboxPolicyCompiler,
    select_sandbox_controller,
)
from src.core.plugin_sandbox.errors import PluginSandboxActivationBlockedError
from src.core.plugin_sandbox.linux import namespaces
from src.core.plugin_sandbox.linux.landlock import landlock_abi_version
from src.core.plugin_sandbox.linux.native import (
    DENIED_SYSCALLS,
    LINUX_LAUNCHER_CONTRACT_VERSION,
    LINUX_LAUNCHER_VERSION,
    landlock_abi,
    launcher_record,
    seccomp_available,
)
from src.core.plugin_sandbox.linux.seccomp import SECCOMP_PROFILES, profile_checksum, seccomp_backend_status

ROOT = Path(__file__).resolve().parents[1]


class PluginSandboxEnforcementPhase201Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.compiler = SandboxPolicyCompiler()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def policy_and_plan(self, *, development_override: bool = False):
        controller = select_sandbox_controller(development_override=development_override)
        policy = self.compiler.build_policy(
            plugin_id="channel.example",
            plugin_version="0.1.0",
            distribution_status="community",
            permissions=["account_configuration", "outbound_network", "secret_storage"],
            capabilities=["channel.health"],
            development_override=development_override,
        )
        plan = controller.compile_plan(
            policy,
            SandboxCompilationContext(
                install_record_id="install_1",
                environment_id="env_1",
                artifact_checksum="artifact_1",
                environment_checksum="environment_1",
                development_override=development_override,
            ),
        )
        return controller, policy, plan

    def test_launcher_integrity_record(self) -> None:
        record = launcher_record()
        self.assertEqual(record["launcher_version"], LINUX_LAUNCHER_VERSION)
        self.assertEqual(record["launcher_contract_version"], LINUX_LAUNCHER_CONTRACT_VERSION)
        self.assertEqual(len(record["launcher_checksum"]), 64)
        self.assertIn(platform.machine(), record["supported_architectures"])
        self.assertTrue(record["permissions_safe"])

    def test_launcher_command_validation_terms(self) -> None:
        source = (ROOT / "src/core/plugin_sandbox/linux/launcher.py").read_text()
        for forbidden in ["shell=True", "bash -c", "sh -c", "eval("]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn("invalid_command", source)
        self.assertIn("os.execve", source)

    def test_namespace_enforcement_probe_reports_actual_capability(self) -> None:
        probe = namespaces.namespace_enforcement_probe()
        self.assertIn("supported", probe)
        self.assertIn("error", probe)
        controller = select_sandbox_controller()
        capability = controller.inspect_platform()
        if not probe["supported"]:
            for control in [
                "uid_gid_mapping",
                "mount_namespace",
                "pid_namespace",
                "ipc_namespace",
                "uts_namespace",
                "network_namespace",
            ]:
                self.assertIn(control, capability.missing_controls)

    def test_required_namespace_policy_controls(self) -> None:
        _, policy, plan = self.policy_and_plan()
        required = set(policy.required_controls)
        for control in [
            "user_namespace",
            "uid_gid_mapping",
            "mount_namespace",
            "pid_namespace",
            "ipc_namespace",
            "uts_namespace",
            "network_namespace",
        ]:
            self.assertIn(control, required)
        self.assertIn("uid_gid_mapping", plan.required_controls)

    def test_filesystem_policy_denies_sensitive_roots(self) -> None:
        _, policy, plan = self.policy_and_plan()
        denied = set(policy.filesystem_policy["denied"])
        for item in ["home", "repository", "content", "drafts", ".ssh", ".gnupg", "docker.sock", "ssh-agent"]:
            with self.subTest(item=item):
                self.assertIn(item, denied)
        mounts = {item["name"]: item["mode"] for item in plan.filesystem_mounts}
        self.assertEqual(mounts["plugin_environment"], "ro")
        self.assertIn("noexec", mounts["plugin_temp"])

    def test_proc_dev_policy_and_docs(self) -> None:
        linux_fs = (ROOT / "docs/plugin-sandbox-linux-filesystem.md").read_text()
        for marker in ["/dev/null", "/dev/zero", "/dev/random", "/dev/urandom"]:
            self.assertTrue(marker in linux_fs or "minimal `/dev`" in linux_fs)
        self.assertIn("isolated `/proc`", (ROOT / "docs/plugin-sandbox-linux.md").read_text())

    def test_landlock_abi_detection_is_kernel_based(self) -> None:
        abi = landlock_abi()
        self.assertEqual(landlock_abi_version(), abi)
        self.assertIsInstance(abi, int)
        self.assertGreaterEqual(abi, 0)

    def test_seccomp_backend_and_profiles(self) -> None:
        self.assertIn(seccomp_backend_status(), {"available", "unavailable"})
        self.assertEqual(seccomp_backend_status(), "available" if seccomp_available() else "unavailable")
        for profile in [
            "python_plugin_base.v1",
            "channel_api_first.v1",
            "channel_browser_proxy.v1",
            "channel_metrics_read.v1",
        ]:
            with self.subTest(profile=profile):
                self.assertIn(profile, SECCOMP_PROFILES)
                self.assertEqual(len(profile_checksum(profile)), 64)

    def test_seccomp_denied_syscall_categories_declared(self) -> None:
        for syscall in [
            "ptrace",
            "process_vm_readv",
            "process_vm_writev",
            "mount",
            "umount2",
            "setns",
            "unshare",
            "bpf",
            "perf_event_open",
            "keyctl",
            "reboot",
            "kexec_load",
            "swapon",
            "swapoff",
            "open_by_handle_at",
            "execve",
        ]:
            with self.subTest(syscall=syscall):
                self.assertIn(syscall, DENIED_SYSCALLS)

    def test_seccomp_load_probe_in_disposable_child(self) -> None:
        if not seccomp_available():
            self.skipTest("libseccomp unavailable")
        code = """
from src.core.plugin_sandbox.linux.native import apply_seccomp_denylist
from src.core.plugin_sandbox.linux.seccomp import seccomp_status
apply_seccomp_denylist(['ptrace','mount','setns','unshare','bpf','keyctl','execve'])
print(seccomp_status())
"""
        result = subprocess.run([".venv/bin/python", "-c", code], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2")

    def test_network_policy_is_broker_only(self) -> None:
        _, policy, _ = self.policy_and_plan()
        self.assertEqual(policy.network_policy["direct"], "deny")
        self.assertEqual(policy.metadata["outbound_network"], "brokered_http_only")
        self.assertEqual(policy.metadata["direct_network"], "unsupported")

    def test_child_runtime_has_attestation_acceptance_gate(self) -> None:
        source = (ROOT / "src/plugin_host_runtime/host.py").read_text()
        self.assertLess(source.index("enforce_and_attest"), source.index("def _load_plugin"))
        self.assertIn("sandbox.attestation_accepted", source)
        self.assertIn("sandbox_attestation_accepted", source)

    def test_parent_validates_child_attestation_before_activation(self) -> None:
        source = (ROOT / "src/core/plugin_host/supervisor.py").read_text()
        self.assertLess(source.index("_verify_sandbox_attestation"), source.index('"plugin.activate"'))
        self.assertIn("child_attestation_failed", source)
        self.assertIn("kernel_evidence_mismatch", source)

    def test_production_launch_fails_closed_when_probe_missing(self) -> None:
        controller, _, plan = self.policy_and_plan()
        missing = [control for control in plan.required_controls if control not in plan.resolved_controls]
        if not missing:
            self.skipTest("host reports all required controls available")
        spec = PluginHostProcessSpec(argv=["/bin/false"], cwd=str(self.root), env={})
        with self.assertRaises(PluginSandboxActivationBlockedError):
            controller.launch(plan, spec)

    def test_development_override_does_not_claim_enforced(self) -> None:
        controller, _, plan = self.policy_and_plan(development_override=True)
        spec = PluginHostProcessSpec(
            argv=[".venv/bin/python", "-c", "import time; time.sleep(0.01)"],
            cwd=str(ROOT),
            env={},
        )
        process = controller.launch(plan, spec)
        try:
            attestation = controller.attest(process, plan)
            if process.metadata.get("development_override"):
                self.assertEqual(attestation.status, "development_override")
        finally:
            controller.terminate(process)

    def test_native_integration_real_host_or_platform_skip(self) -> None:
        controller = select_sandbox_controller(development_override=False)
        capability = controller.inspect_platform()
        if not capability.production_ready:
            self.skipTest(f"kernel not production-ready: {capability.missing_controls}")
        release = PluginPackageBuildService().create_release_directory(
            "templates/channel-plugin", self.root / "release"
        )
        PluginInstallationService(self.root / "installs").install_verified_release(
            release,
            actor="test",
            reason="phase20.1",
            permission_confirmed=True,
        )
        service = PluginInstallationService(self.root / "installs")
        service.request_activation(
            "channel.example",
            "0.1.0",
            actor="test",
            reason="phase20.1",
            permission_confirmed=True,
        )
        active = self.root / "installs/channel.example/active.json"
        payload = json.loads(active.read_text())
        payload["activation_status"] = "enabled"
        active.write_text(json.dumps(payload))
        supervisor = PluginHostSupervisor(self.root / "installs", self.root / "envs", self.root / "work", ROOT)
        host = supervisor.ensure_host(
            "channel.example",
            "0.1.0",
            capabilities=["channel.health"],
            permissions=["account_configuration", "outbound_network", "secret_storage"],
        )
        try:
            self.assertEqual(host.record.process_status, "ready")
            self.assertEqual(host.sandbox_attestation.status, "enforced")
            self.assertEqual(host.ready.sandbox_attestation["status"], "enforced")
            self.assertEqual(host.call_raw("channel.health", {"workspace_id": "w1"})["status"], "ok")
        finally:
            host.shutdown()

    def test_mutation_recovery_semantics_unchanged(self) -> None:
        from src.core.plugin_host.supervisor import classify_mutation_recovery

        cases = {
            "not_started": "pre_mutation_failure",
            "prepared": "cleanup_and_revalidation",
            "mutation_started": "uncertain",
            "mutation_acknowledged": "remote_verification_required",
            "mutation_verified": "evidence_reconciliation",
            "mutation_uncertain": "manual_review",
        }
        for state, expected in cases.items():
            with self.subTest(state=state):
                self.assertEqual(classify_mutation_recovery(state), expected)

    def test_no_framework_contract_changes(self) -> None:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--",
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


def _make_declared_control_test(control: str):
    def test(self: PluginSandboxEnforcementPhase201Tests) -> None:
        _, policy, _ = self.policy_and_plan()
        self.assertIn(control, policy.required_controls)

    return test


for _control in [
    "no_new_privs",
    "user_namespace",
    "uid_gid_mapping",
    "mount_namespace",
    "pid_namespace",
    "ipc_namespace",
    "uts_namespace",
    "network_namespace",
    "private_mount_propagation",
    "readonly_code_environment",
    "minimal_writable_dirs",
    "proc_isolated",
    "dev_minimal",
    "seccomp",
    "landlock",
    "network_default_deny",
    "rlimits",
    "process_group",
    "sandbox_attestation",
]:
    setattr(
        PluginSandboxEnforcementPhase201Tests,
        f"test_declared_required_control_{_control}",
        _make_declared_control_test(_control),
    )


def _make_denied_path_test(path_summary: str):
    def test(self: PluginSandboxEnforcementPhase201Tests) -> None:
        _, policy, _ = self.policy_and_plan()
        self.assertIn(path_summary, policy.filesystem_policy["denied"])

    return test


for _path_summary in [
    "home",
    "repository",
    "content",
    "drafts",
    ".ssh",
    ".gnupg",
    "browserprofiles",
    "databasefiles",
    "docker.sock",
    "ssh-agent",
]:
    safe_name = _path_summary.replace(".", "dot_").replace("-", "_")
    setattr(
        PluginSandboxEnforcementPhase201Tests,
        f"test_filesystem_denies_{safe_name}",
        _make_denied_path_test(_path_summary),
    )


def _make_seccomp_syscall_test(syscall: str):
    def test(self: PluginSandboxEnforcementPhase201Tests) -> None:
        self.assertIn(syscall, DENIED_SYSCALLS)

    return test


for _syscall in [
    "ptrace",
    "process_vm_readv",
    "process_vm_writev",
    "mount",
    "umount2",
    "pivot_root",
    "chroot",
    "setns",
    "unshare",
    "bpf",
    "perf_event_open",
    "keyctl",
    "add_key",
    "request_key",
    "reboot",
    "kexec_load",
    "kexec_file_load",
    "swapon",
    "swapoff",
    "sethostname",
    "setdomainname",
    "iopl",
    "ioperm",
    "open_by_handle_at",
    "init_module",
    "finit_module",
    "delete_module",
    "fork",
    "vfork",
    "execve",
    "execveat",
]:
    setattr(
        PluginSandboxEnforcementPhase201Tests,
        f"test_seccomp_denies_{_syscall}",
        _make_seccomp_syscall_test(_syscall),
    )


def _make_scenario_test(scenario: str):
    def test(self: PluginSandboxEnforcementPhase201Tests) -> None:
        path = ROOT / "integrations/plugin_sandbox/scenarios" / f"{scenario}.json"
        self.assertTrue(path.exists())
        payload = json.loads(path.read_text())
        self.assertTrue(payload.get("expected") or payload.get("classification"))

    return test


for _scenario in [
    "read_host_home",
    "read_repository",
    "read_content",
    "read_drafts",
    "read_another_plugin",
    "write_code_environment",
    "create_symlink_escape",
    "hardlink_escape",
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
    "oversized_temp",
    "process_fork_bomb",
    "memory_pressure",
    "cpu_pressure",
    "valid_http_callback",
    "valid_browser_callback",
    "valid_media_transfer",
    "valid_state_callback",
]:
    setattr(
        PluginSandboxEnforcementPhase201Tests,
        f"test_fixture_scenario_{_scenario}",
        _make_scenario_test(_scenario),
    )


if __name__ == "__main__":
    unittest.main()
