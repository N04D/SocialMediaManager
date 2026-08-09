from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.core.runtime import (
    CapabilityDescriptor,
    CapabilityHandlerRegistry,
    CapabilityMode,
    ComponentBinding,
    ComponentManifest,
    DeploymentPolicy,
    EventEnvelope,
    EventSource,
    ExecutionState,
    Install,
    InstallGrants,
    PlaybookDefinition,
    PlaybookDeployment,
    PlaybookEdge,
    PlaybookExecutor,
    PlaybookNode,
    RequirementBinding,
    RuntimePolicyEngine,
    RuntimeRegistry,
    compile_execution_plan,
    trace_execution,
)
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.results import NodeResult


@dataclass
class CountingWriteHandler:
    calls: int = 0
    component_id: str = "test-write-component"
    capability_id: str = "test.resource.write"

    def execute(self, **kwargs) -> NodeResult:  # type: ignore[no-untyped-def]
        self.calls += 1
        return NodeResult.success({"writes": self.calls})


def write_playbook() -> PlaybookDefinition:
    return PlaybookDefinition(
        playbook_id="phase47.synthetic-write",
        version="1.0.0",
        schema_version="1.0",
        name="Synthetic Write",
        requirements={"writer": {"capabilities": ["test.resource.write"]}},
        nodes=(
            PlaybookNode("trigger", "trigger", {"event_type": "test.write.requested"}),
            PlaybookNode("write", "capability", {"requirement": "writer", "capability": "test.resource.write"}),
        ),
        edges=(PlaybookEdge("trigger", "write"),),
    )


def write_registry(grants: InstallGrants) -> RuntimeRegistry:
    registry = RuntimeRegistry()
    registry.register_component(
        ComponentManifest(
            component_id="test-write-component",
            provider="test",
            version="0.1.0",
            sdk_version="runtime-contracts-0.1",
            capabilities=(CapabilityDescriptor("test.resource.write", "0.1.0", CapabilityMode.WRITE.value),),
            permissions={
                "network": {"required": False},
                "filesystem": {"mode": "none"},
                "subprocess": {"allowed": False},
            },
        )
    )
    registry.register_install(
        Install(
            install_id="test-write-install",
            workspace_id="workspace",
            provider="test",
            account_ref="memory",
            component_bindings={"test.resource.write": ComponentBinding("test-write-component")},
            grants=grants,
        )
    )
    return registry


def write_deployment(policy: DeploymentPolicy) -> PlaybookDeployment:
    return PlaybookDeployment(
        deployment_id="phase47-write",
        playbook_id="phase47.synthetic-write",
        playbook_version="1.0.0",
        workspace_id="workspace",
        requirement_bindings={"writer": RequirementBinding("test-write-install")},
        policy=policy,
    )


def write_event() -> EventEnvelope:
    return EventEnvelope(
        event_type="test.write.requested",
        source=EventSource(component="phase47-test", provider="test"),
        workspace_id="workspace",
        idempotency_key="phase47-write",
    )


def write_executor(grants: InstallGrants, policy: DeploymentPolicy):
    registry = write_registry(grants)
    deployment = write_deployment(policy)
    plan = compile_execution_plan(write_playbook(), deployment, registry)
    handler = CountingWriteHandler()
    handlers = CapabilityHandlerRegistry()
    handlers.register(handler)
    executor = PlaybookExecutor(
        handlers,
        policy_engine=RuntimePolicyEngine(registry=registry, deployments={deployment.deployment_id: deployment}),
    )
    return executor, handler, plan


def write_records(executor: PlaybookExecutor, execution_id: str):
    return [node for node in executor.ledger.list_node_executions(execution_id) if node.node_id == "write"]


def test_mutation_without_permission_denies_before_handler() -> None:
    executor, handler, plan = write_executor(
        InstallGrants(allowed_capabilities=("test.resource.write",)),
        DeploymentPolicy(allow_mutations=False, require_approval_for_writes=False),
    )

    outcome = executor.execute(plan=plan, trigger_event=write_event())

    assert outcome.execution.state == ExecutionState.FAILED.value
    assert write_records(executor, outcome.execution.execution_id)[-1].error_code == "MUTATION_NOT_ALLOWED"
    assert handler.calls == 0


def test_write_requires_approval_then_approved_executes_once() -> None:
    executor, handler, plan = write_executor(
        InstallGrants(allowed_capabilities=("test.resource.write",), allow_mutations=True),
        DeploymentPolicy(allow_mutations=True, require_approval_for_writes=True),
    )

    waiting = executor.execute(plan=plan, trigger_event=write_event())

    assert waiting.execution.state == ExecutionState.WAITING.value
    assert handler.calls == 0
    waiting_node = write_records(executor, waiting.execution.execution_id)[-1]
    assert waiting_node.state == ExecutionState.WAITING.value
    assert waiting_node.metadata["waiting_reason"] == "approval_required"

    approved = executor.approve_execution_node(waiting.execution.execution_id, "write", actor="tester")

    assert approved.execution.state == ExecutionState.SUCCEEDED.value
    assert handler.calls == 1
    assert approved.context.node_outputs["write"] == {"writes": 1}

    second = executor.approve_execution_node(waiting.execution.execution_id, "write", actor="tester")
    assert second.execution.state == ExecutionState.SUCCEEDED.value
    assert handler.calls == 1


def test_rejection_never_executes_handler() -> None:
    executor, handler, plan = write_executor(
        InstallGrants(allowed_capabilities=("test.resource.write",), allow_mutations=True),
        DeploymentPolicy(allow_mutations=True, require_approval_for_writes=True),
    )
    waiting = executor.execute(plan=plan, trigger_event=write_event())

    rejected = executor.reject_execution_node(waiting.execution.execution_id, "write", actor="tester")

    assert rejected.execution.state == ExecutionState.FAILED.value
    assert handler.calls == 0
    assert write_records(executor, waiting.execution.execution_id)[-1].error_code == "APPROVAL_REJECTED"
    with pytest.raises(PlaybookExecutionError):
        executor.approve_execution_node(waiting.execution.execution_id, "write", actor="tester")


def test_approval_cannot_override_hard_deny() -> None:
    executor, handler, plan = write_executor(
        InstallGrants(allowed_capabilities=("test.resource.write",)),
        DeploymentPolicy(allow_mutations=False, require_approval_for_writes=True),
    )

    denied = executor.execute(plan=plan, trigger_event=write_event())

    assert denied.execution.state == ExecutionState.FAILED.value
    assert executor.approval_store.get(denied.execution.execution_id, "write") is None
    assert handler.calls == 0
    with pytest.raises(PlaybookExecutionError):
        executor.approve_execution_node(denied.execution.execution_id, "write", actor="tester")


def test_policy_trace_contains_no_secret_values() -> None:
    executor, _handler, plan = write_executor(
        InstallGrants(allowed_capabilities=("test.resource.write",), allow_mutations=True),
        DeploymentPolicy(allow_mutations=True, require_approval_for_writes=True),
    )
    waiting = executor.execute(plan=plan, trigger_event=write_event())
    trace = trace_execution(executor.ledger, waiting.execution.execution_id).to_dict()

    assert "approval_required" in str(trace)
    assert "secret" not in str(trace).lower()
    assert "token" not in str(trace).lower()
