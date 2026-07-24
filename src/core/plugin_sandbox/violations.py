"""Sandbox violation recording."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .models import PluginSandboxViolation, utc_now


class PluginSandboxViolationStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def record(
        self,
        *,
        plugin_id: str,
        plugin_version: str,
        host_id: str,
        process_instance_id: str,
        sandbox_plan_id: str,
        platform: str,
        control: str,
        operation: str,
        action: str,
        blocked: bool,
        severity: str,
        safe_resource_summary: str,
        mutation_state: str = "not_started",
        safe_error_code: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> PluginSandboxViolation:
        violation = PluginSandboxViolation(
            id=f"vio_{uuid.uuid4().hex}",
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            host_id=host_id,
            process_instance_id=process_instance_id,
            sandbox_plan_id=sandbox_plan_id,
            occurred_at=utc_now(),
            platform=platform,
            control=control,
            operation=operation,
            action=action,
            blocked=blocked,
            severity=severity,
            safe_resource_summary=safe_resource_summary,
            mutation_state=mutation_state,
            safe_error_code=safe_error_code,
            metadata=metadata or {},
        )
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "violations.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(violation.__dict__, sort_keys=True) + "\n")
        return violation

    def list(self) -> list[PluginSandboxViolation]:
        path = self.root / "violations.jsonl"
        if not path.exists():
            return []
        return [PluginSandboxViolation(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def classify_violation(control: str, operation: str) -> str:
    if operation in {"read_host_home", "read_content", "read_drafts"}:
        return "expected_denial"
    if control == "network":
        return "policy_violation"
    if operation in {"docker_socket", "ptrace", "mount", "bpf", "keyring"}:
        return "escape_attempt"
    if control == "platform":
        return "platform_failure"
    return "unknown"


__all__ = ["PluginSandboxViolationStore", "classify_violation"]
