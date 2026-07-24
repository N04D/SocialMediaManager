"""Supervisor for one external plugin process per plugin id/version."""

from __future__ import annotations

import selectors
import subprocess
import threading
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.core.plugin_sandbox import (
    PluginHostProcessSpec,
    SandboxCompilationContext,
    SandboxPolicyCompiler,
    select_sandbox_controller,
)
from src.plugin_sdk.contracts import PLUGIN_SDK_VERSION

from .contracts import PLUGIN_HOST_FRAMEWORK_VERSION, PLUGIN_HOST_PROTOCOL_VERSION
from .environment import PluginHostEnvironmentManager
from .errors import PluginHostHandshakeError, PluginHostProcessError, PluginHostTimeoutError
from .framing import decode_frame, encode_frame
from .models import (
    PluginHostCrashRecord,
    PluginHostHandshake,
    PluginHostProcessRecord,
    PluginHostResourcePolicy,
    PluginReady,
    utc_now,
)
from .policies import sanitized_environment
from .protocol import make_request, validate_response
from .resources import PluginHostResourceController


def classify_mutation_recovery(mutation_state: str) -> str:
    mapping = {
        "not_started": "pre_mutation_failure",
        "prepared": "cleanup_and_revalidation",
        "mutation_started": "uncertain",
        "mutation_acknowledged": "remote_verification_required",
        "mutation_verified": "evidence_reconciliation",
        "mutation_uncertain": "manual_review",
    }
    return mapping.get(mutation_state, "manual_review")


class PluginHostProcess:
    def __init__(
        self,
        *,
        plugin_id: str,
        plugin_version: str,
        environment_manager: PluginHostEnvironmentManager,
        host_workdir: str | Path,
        repo_root: str | Path,
        policy: PluginHostResourcePolicy | None = None,
        sandbox_development_override: bool = False,
    ) -> None:
        self.plugin_id = plugin_id
        self.plugin_version = plugin_version
        self.environment_manager = environment_manager
        self.host_workdir = Path(host_workdir)
        self.repo_root = Path(repo_root)
        self.policy = policy or PluginHostResourcePolicy()
        self.sandbox_development_override = sandbox_development_override
        self.sandbox_controller = select_sandbox_controller(development_override=sandbox_development_override)
        self.sandbox_attestation = None
        self.resources = PluginHostResourceController(self.policy)
        self.host_id = f"{plugin_id}:{plugin_version}:{uuid.uuid4().hex[:12]}"
        self.process: subprocess.Popen[bytes] | None = None
        self.lock = threading.RLock()
        self.last_heartbeat_at = ""
        self.active_calls = 0
        self.crashes: list[PluginHostCrashRecord] = []
        self.ready: PluginReady | None = None
        self.record = PluginHostProcessRecord(
            host_id=self.host_id,
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            resource_containment=self.resources.containment_status(),
        )

    def start(self, *, capabilities: list[str], permissions: list[str]) -> PluginHostProcessRecord:
        with self.lock:
            spec = self.environment_manager.verify(self.plugin_id, self.plugin_version)
            self.host_workdir.mkdir(parents=True, exist_ok=True)
            env = sanitized_environment(
                {
                    "SMM_PLUGIN_HOST_REPO": str(self.repo_root),
                    "SMM_PLUGIN_INSTALL_ROOT": str(self.environment_manager.install_root),
                    "SMM_PLUGIN_ID": self.plugin_id,
                    "SMM_PLUGIN_VERSION": self.plugin_version,
                }
            )
            self.record.environment_status = spec.status
            sandbox_policy = SandboxPolicyCompiler().build_policy(
                plugin_id=self.plugin_id,
                plugin_version=self.plugin_version,
                distribution_status="community",
                permissions=permissions,
                capabilities=capabilities,
                development_override=self.sandbox_development_override,
            )
            sandbox_plan = self.sandbox_controller.compile_plan(
                sandbox_policy,
                SandboxCompilationContext(
                    install_record_id=f"{self.plugin_id}:{self.plugin_version}",
                    environment_id=spec.environment_checksum,
                    artifact_checksum=spec.artifact_sha256,
                    environment_checksum=spec.environment_checksum,
                    distribution_status="community",
                    development_override=self.sandbox_development_override,
                ),
            )
            self.sandbox_controller.prepare(sandbox_plan)
            sandboxed = self.sandbox_controller.launch(
                sandbox_plan,
                PluginHostProcessSpec(
                    argv=self.environment_manager.start_command(spec),
                    cwd=str(self.host_workdir),
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ),
            )
            self.sandbox_attestation = self.sandbox_controller.attest(sandboxed, sandbox_plan)
            self.process = sandboxed.process
            self.record.environment_status = spec.status
            self.record.process_status = "starting"
            self.record.warnings.extend(list(self.sandbox_attestation.warnings))
            request = PluginHostHandshake(
                protocol_version=PLUGIN_HOST_PROTOCOL_VERSION,
                host_runtime_version=PLUGIN_HOST_FRAMEWORK_VERSION,
                plugin_sdk_version=PLUGIN_SDK_VERSION,
                expected_plugin_id=self.plugin_id,
                expected_plugin_version=self.plugin_version,
                manifest_checksum=spec.manifest_checksum,
                artifact_checksum=spec.artifact_sha256,
                entrypoint=spec.entrypoint,
                allowed_capabilities=capabilities,
                allowed_permissions=permissions,
                maximum_frame_size=self.policy.max_frame_bytes,
                session_nonce=uuid.uuid4().hex,
                environment_checksum=spec.environment_checksum,
            )
            result = self.call_raw("host.initialize", request.to_dict(), timeout=self.policy.request_timeout_seconds)
            self.ready = PluginReady(**result)
            self._verify_ready(request, self.ready)
            self.call_raw("plugin.activate", {"host_id": self.host_id}, timeout=self.policy.request_timeout_seconds)
            self.record.process_status = "ready"
            self.record.last_heartbeat_at = utc_now()
            self.last_heartbeat_at = self.record.last_heartbeat_at
            return self.record

    def call_raw(self, method: str, params: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise PluginHostProcessError("plugin_host.process.not_started", "Plugin host process is not running.")
        request_id = f"req_{uuid.uuid4().hex}"
        frame = encode_frame(
            make_request(request_id, method, params).to_dict(), max_frame_bytes=self.policy.max_frame_bytes
        )
        with self.lock:
            self.active_calls += 1
            self.record.active_calls = self.active_calls
            self.process.stdin.write(frame)
            self.process.stdin.flush()
            try:
                response = self._read_response(timeout or self.policy.request_timeout_seconds)
                return validate_response(response, request_id)
            finally:
                self.active_calls -= 1
                self.record.active_calls = self.active_calls

    def ping(self) -> dict[str, Any]:
        result = self.call_raw("plugin.ping", {})
        self.record.last_heartbeat_at = utc_now()
        self.last_heartbeat_at = self.record.last_heartbeat_at
        return result

    def shutdown(self) -> PluginHostProcessRecord:
        if self.process is None:
            self.record.process_status = "stopped"
            return self.record
        try:
            self.call_raw("plugin.shutdown", {}, timeout=self.policy.shutdown_grace_seconds)
            self.process.wait(timeout=self.policy.shutdown_grace_seconds)
            self.record.process_status = "stopped"
        except Exception:
            self.terminate("operator stop")
        finally:
            self._close_pipes()
        return self.record

    def terminate(self, reason: str) -> None:
        if self.process is None:
            return
        try:
            self.resources.terminate_group(self.process.pid)
            self.process.wait(timeout=self.policy.terminate_grace_seconds)
        except Exception:
            self.resources.kill_group(self.process.pid)
        finally:
            self._close_pipes()
        self._crash("operator stop", "not_started", "plugin_host.process.terminated", reason, restartable=False)

    def cancel(self, mutation_state: str) -> dict[str, str]:
        recovery = classify_mutation_recovery(mutation_state)
        if recovery in {"uncertain", "remote_verification_required", "manual_review"}:
            return {"status": "mutation may have occurred", "recovery": recovery}
        return {"status": "cancelled pre-mutation", "recovery": recovery}

    def watchdog_tick(self) -> PluginHostProcessRecord:
        if (
            self.process
            and self.process.poll() is not None
            and self.record.process_status not in {"stopped", "quarantined"}
        ):
            self._crash(
                "process exit", "not_started", "plugin_host.process.exited", "Plugin host exited.", restartable=True
            )
        if self.last_heartbeat_at:
            last = datetime.fromisoformat(self.last_heartbeat_at)
            if datetime.now(UTC) - last > timedelta(seconds=self.policy.request_timeout_seconds * 2):
                self._crash(
                    "watchdog termination",
                    "not_started",
                    "plugin_host.watchdog.timeout",
                    "Plugin host heartbeat timed out.",
                    restartable=True,
                )
                self.terminate("watchdog timeout")
        return self.record

    def _read_response(self, timeout: float) -> dict[str, Any]:
        assert self.process is not None and self.process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(self.process.stdout, selectors.EVENT_READ)
        if not selector.select(timeout):
            raise PluginHostTimeoutError("plugin_host.rpc.timeout", "Plugin host RPC call timed out.")
        return decode_frame(self.process.stdout, max_frame_bytes=self.policy.max_frame_bytes)

    def _verify_ready(self, expected: PluginHostHandshake, ready: PluginReady) -> None:
        if ready.protocol_version.split(".", maxsplit=1)[0] != expected.protocol_version.split(".", maxsplit=1)[0]:
            raise PluginHostHandshakeError("plugin_host.handshake.protocol_mismatch", "Plugin host protocol mismatch.")
        checks = {
            "plugin_id": ready.plugin_id == expected.expected_plugin_id,
            "plugin_version": ready.plugin_version == expected.expected_plugin_version,
            "manifest_checksum": ready.manifest_checksum == expected.manifest_checksum,
            "entrypoint": ready.entrypoint_identity == expected.entrypoint,
            "sdk": ready.plugin_sdk_version == expected.plugin_sdk_version,
            "capabilities": set(ready.capabilities).issubset(set(expected.allowed_capabilities)),
            "permissions": set(ready.requested_permissions).issubset(set(expected.allowed_permissions)),
        }
        if not all(checks.values()):
            raise PluginHostHandshakeError("plugin_host.handshake.identity_mismatch", "Plugin host identity mismatch.")

    def _crash(
        self, classification: str, mutation_state: str, code: str, message: str, *, restartable: bool
    ) -> PluginHostCrashRecord:
        record = PluginHostCrashRecord(
            host_id=self.host_id,
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            classification=classification,
            mutation_state=mutation_state,
            safe_error_code=code,
            safe_message=message,
            restartable=restartable,
        )
        self.crashes.append(record)
        self.record.crash_count = len(self.crashes)
        self.record.crash_classification = classification
        if len(self.crashes) >= self.policy.maximum_crashes:
            self.record.process_status = "quarantined"
            self.record.restart_backoff_seconds = self.policy.restart_backoff_seconds * len(self.crashes)
        else:
            self.record.process_status = "crashed"
        return record

    def _close_pipes(self) -> None:
        if self.process is None:
            return
        for pipe in [self.process.stdin, self.process.stdout, self.process.stderr]:
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:
                pass


class PluginHostSupervisor:
    def __init__(
        self,
        install_root: str | Path,
        environment_root: str | Path,
        host_workdir: str | Path,
        repo_root: str | Path,
        *,
        sandbox_development_override: bool = False,
    ):
        self.environment_manager = PluginHostEnvironmentManager(install_root, environment_root)
        self.host_workdir = Path(host_workdir)
        self.repo_root = Path(repo_root)
        self.sandbox_development_override = sandbox_development_override
        self.hosts: dict[str, PluginHostProcess] = {}

    def host_key(self, plugin_id: str, plugin_version: str) -> str:
        return f"{plugin_id}=={plugin_version}"

    def prepare(self, plugin_id: str, plugin_version: str) -> dict[str, Any]:
        return asdict(self.environment_manager.prepare(plugin_id, plugin_version))

    def verify(self, plugin_id: str, plugin_version: str) -> dict[str, Any]:
        return asdict(self.environment_manager.verify(plugin_id, plugin_version))

    def ensure_host(
        self,
        plugin_id: str,
        plugin_version: str,
        *,
        capabilities: list[str] | None = None,
        permissions: list[str] | None = None,
    ) -> PluginHostProcess:
        key = self.host_key(plugin_id, plugin_version)
        if key not in self.hosts:
            self.hosts[key] = PluginHostProcess(
                plugin_id=plugin_id,
                plugin_version=plugin_version,
                environment_manager=self.environment_manager,
                host_workdir=self.host_workdir / plugin_id / plugin_version,
                repo_root=self.repo_root,
                sandbox_development_override=self.sandbox_development_override,
            )
        host = self.hosts[key]
        if host.record.process_status in {"stopped", "not_started"}:
            host.start(capabilities=capabilities or [], permissions=permissions or [])
        return host

    def list_processes(self) -> list[dict[str, Any]]:
        return [host.record.to_public() for host in self.hosts.values()]

    def health(self) -> dict[str, Any]:
        degraded = sum(1 for host in self.hosts.values() if host.record.process_status not in {"ready", "stopped"})
        containment = {host.record.resource_containment for host in self.hosts.values()} or {"not_started"}
        return {
            "status": "degraded" if degraded else "ready",
            "framework_version": PLUGIN_HOST_FRAMEWORK_VERSION,
            "protocol_version": PLUGIN_HOST_PROTOCOL_VERSION,
            "active_hosts": len(self.hosts),
            "degraded_hosts": degraded,
            "resource_containment": ",".join(sorted(containment)),
        }


__all__ = ["PluginHostProcess", "PluginHostSupervisor", "classify_mutation_recovery"]
