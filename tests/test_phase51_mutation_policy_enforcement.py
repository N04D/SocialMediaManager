from __future__ import annotations

from dataclasses import dataclass

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
    MutationPolicy,
    PlaybookDefinition,
    PlaybookDeployment,
    PlaybookEdge,
    PlaybookExecutor,
    PlaybookNode,
    ReadbackPolicy,
    RecoveryPolicy,
    RequirementBinding,
    RuntimePolicyEngine,
    RuntimeRegistry,
    compile_execution_plan,
    mutation_safety_report,
)
from src.core.runtime.mutation_policies import CompensationPolicy
from src.core.runtime.results import NodeResult
from tests.test_phase48_production_mutation import (
    calendar_create_event,
    calendar_stack,  # noqa: F401
    mutation_executor,
    pending_mutation_id,
)


@dataclass
class WriteHandlerWithoutPolicy:
    component_id: str = "prod-policy-component"
    capability_id: str = "test.mutation.write"
    calls: int = 0

    def execute(self, **kwargs) -> NodeResult:  # type: ignore[no-untyped-def]
        self.calls += 1
        return NodeResult.success({"calls": self.calls})


@dataclass
class PolicyWriteHandler:
    mutation_policy: MutationPolicy
    component_id: str = "prod-policy-component"
    capability_id: str = "test.mutation.write"
    calls: int = 0

    def execute(self, **kwargs) -> NodeResult:  # type: ignore[no-untyped-def]
        self.calls += 1
        return NodeResult.success({"calls": self.calls, "resource_ref": "test-resource:1"})


@dataclass
class ReadbackHandler(PolicyWriteHandler):
    def verify_readback(self, *args, **kwargs) -> bool:  # type: ignore[no-untyped-def]
        return True


def policy_playbook(config: dict | None = None) -> PlaybookDefinition:
    return PlaybookDefinition(
        playbook_id="phase51.policy-write",
        version="1.0.0",
        schema_version="1.0",
        name="Phase 51 Policy Write",
        requirements={"writer": {"capabilities": ["test.mutation.write"]}},
        nodes=(
            PlaybookNode("trigger", "trigger", {"event_type": "test.mutation.requested"}),
            PlaybookNode(
                "write",
                "capability",
                {"requirement": "writer", "capability": "test.mutation.write", **(config or {})},
            ),
        ),
        edges=(PlaybookEdge("trigger", "write"),),
    )


def policy_registry() -> RuntimeRegistry:
    registry = RuntimeRegistry()
    registry.register_component(
        ComponentManifest(
            component_id="prod-policy-component",
            provider="test",
            version="0.1.0",
            sdk_version="runtime-contracts-0.1",
            capabilities=(CapabilityDescriptor("test.mutation.write", "0.1.0", CapabilityMode.WRITE.value),),
        )
    )
    registry.register_install(
        Install(
            install_id="policy-install",
            workspace_id="workspace",
            provider="test",
            account_ref="memory",
            component_bindings={"test.mutation.write": ComponentBinding("prod-policy-component")},
            grants=InstallGrants(allowed_capabilities=("test.mutation.write",), allow_mutations=True),
        )
    )
    return registry


def policy_executor(handler, config: dict | None = None):
    registry = policy_registry()
    deployment = PlaybookDeployment(
        deployment_id="phase51-policy",
        playbook_id="phase51.policy-write",
        playbook_version="1.0.0",
        workspace_id="workspace",
        requirement_bindings={"writer": RequirementBinding("policy-install")},
        policy=DeploymentPolicy(allow_mutations=True, require_approval_for_writes=False),
    )
    plan = compile_execution_plan(policy_playbook(config), deployment, registry)
    handlers = CapabilityHandlerRegistry()
    handlers.register(handler)
    executor = PlaybookExecutor(
        handlers,
        policy_engine=RuntimePolicyEngine(registry=registry, deployments={deployment.deployment_id: deployment}),
    )
    return executor, handler, plan


def policy_event() -> EventEnvelope:
    return EventEnvelope(
        event_type="test.mutation.requested",
        source=EventSource(component="phase51-test", provider="test"),
        workspace_id="workspace",
        idempotency_key="phase51-policy",
    )


def test_no_mutation_policy_blocks_production_handler_before_side_effect() -> None:
    executor, handler, plan = policy_executor(WriteHandlerWithoutPolicy())

    outcome = executor.execute(plan=plan, trigger_event=policy_event())

    assert outcome.execution.state == ExecutionState.FAILED.value
    assert handler.calls == 0
    assert (
        executor.ledger.list_node_executions(outcome.execution.execution_id)[-1].error_code == "BLOCKED_POLICY_MISSING"
    )


def test_required_readback_without_verifier_blocks_before_side_effect() -> None:
    handler = PolicyWriteHandler(
        MutationPolicy(
            True, True, ReadbackPolicy.REQUIRED.value, CompensationPolicy.UNAVAILABLE.value, RecoveryPolicy.MANUAL.value
        )
    )
    executor, handler, plan = policy_executor(handler)

    outcome = executor.execute(plan=plan, trigger_event=policy_event())

    assert outcome.execution.state == ExecutionState.FAILED.value
    assert handler.calls == 0
    assert executor.ledger.list_node_executions(outcome.execution.execution_id)[-1].error_code == "BLOCKED_READBACK"


def test_compensation_required_blocks_non_compensatable_handler() -> None:
    handler = ReadbackHandler(
        MutationPolicy(
            True, True, ReadbackPolicy.REQUIRED.value, CompensationPolicy.UNAVAILABLE.value, RecoveryPolicy.MANUAL.value
        )
    )
    executor, handler, plan = policy_executor(
        handler,
        {"mutation_policy": {"compensation": CompensationPolicy.REQUIRED.value}},
    )

    outcome = executor.execute(plan=plan, trigger_event=policy_event())

    assert outcome.execution.state == ExecutionState.FAILED.value
    assert handler.calls == 0
    assert executor.ledger.list_node_executions(outcome.execution.execution_id)[-1].error_code == "BLOCKED_COMPENSATION"


def test_mutation_safety_report_is_structured_and_side_effect_free() -> None:
    executor, handler, plan = policy_executor(
        ReadbackHandler(
            MutationPolicy(
                True,
                True,
                ReadbackPolicy.REQUIRED.value,
                CompensationPolicy.UNAVAILABLE.value,
                RecoveryPolicy.MANUAL.value,
            )
        )
    )

    report = mutation_safety_report(plan, executor.handler_registry)

    assert handler.calls == 0
    assert report[0].status == "READY"
    assert report[0].effective_policy.readback == ReadbackPolicy.REQUIRED.value


def test_policy_change_after_approval_invalidates_intent_without_side_effect(calendar_stack) -> None:  # noqa: F811
    executor, handler, plan = mutation_executor(calendar_stack)
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event(idempotency_key="phase51-policy-change"))
    mutation_id = pending_mutation_id(executor, waiting.execution.execution_id)
    approval = executor.approval_store.approve(
        waiting.execution.execution_id,
        "create-calendar",
        actor_id="operator-51",
        actor_type="test_operator",
    )
    executor.mutation_journal.mark_approved(mutation_id, approval_id=approval.approval_id)
    handler.mutation_policy = MutationPolicy(
        requires_approval=True,
        idempotency_required=True,
        readback=ReadbackPolicy.REQUIRED.value,
        compensation=CompensationPolicy.SUPPORTED.value,
        recovery=RecoveryPolicy.MANUAL.value,
    )

    outcome = executor.resume_execution(waiting.execution.execution_id)

    assert outcome.execution.state == ExecutionState.WAITING.value
    assert handler.calls == 0
    assert pending_mutation_id(executor, waiting.execution.execution_id) != mutation_id
