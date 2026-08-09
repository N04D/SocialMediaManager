from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from publication_calendar_runtime_handlers import (
    CALENDAR_COMPONENT_ID,
    CALENDAR_EVENT_CREATE_CAPABILITY,
)
from publication_scheduling import ScheduleOccurrenceRepository
from runtime_foundation_mappings import phase41_runtime_registry
from src.core.runtime import (
    CapabilityDescriptor,
    CapabilityMode,
    CapabilityResolutionError,
    ComponentBinding,
    ComponentManifest,
    DeploymentPolicy,
    ExecutionState,
    Install,
    InstallGrants,
    MutationReceipt,
    PlaybookDefinition,
    PlaybookDeployment,
    PlaybookEdge,
    PlaybookExecutor,
    PlaybookNode,
    RequirementBinding,
    RuntimePolicyEngine,
    RuntimeRegistry,
    SqliteMutationJournal,
    compile_execution_plan,
    trace_execution,
)
from src.core.runtime.deployments import DeploymentValidationError
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.mutations import (
    CompensationIntent,
    build_compensation_id,
    build_compensation_idempotency_key,
    mutation_input_fingerprint,
)
from src.core.runtime.results import NodeResult
from src.core.scheduling import ScheduleOccurrence, ScheduleOccurrenceStatus
from tests.test_phase48_production_mutation import (
    CountingCalendarEventCreateHandler,
    calendar_create_deployment,
    calendar_create_event,
    calendar_stack,  # noqa: F401
    mutation_registry,
    pending_mutation_id,
)


@dataclass
class EchoHandler:
    component_id: str = "test-echo-component"
    capability_id: str = "test.echo"
    calls: int = 0

    def execute(self, **kwargs) -> NodeResult:  # type: ignore[no-untyped-def]
        self.calls += 1
        return NodeResult.success({"ok": True})


@dataclass
class FailingHandler:
    component_id: str = "test-failure-component"
    capability_id: str = "test.failure"
    calls: int = 0

    def execute(self, **kwargs) -> NodeResult:  # type: ignore[no-untyped-def]
        self.calls += 1
        return NodeResult.failure("TEST_DOWNSTREAM_FAILED", "Injected downstream failure.")


@dataclass
class MutatingFailureHandler:
    occurrence_repository: ScheduleOccurrenceRepository
    component_id: str = "test-failure-component"
    capability_id: str = "test.failure"
    calls: int = 0

    def execute(self, **kwargs) -> NodeResult:  # type: ignore[no-untyped-def]
        self.calls += 1
        context = kwargs["context"]
        receipt = MutationReceipt.from_dict(context.node_outputs["create-calendar"]["mutation_receipt"])
        occurrence_id = str(receipt.metadata["created_resource"]["resource_id"])
        occurrence = self.occurrence_repository.get(occurrence_id)
        assert occurrence is not None
        occurrence.status = ScheduleOccurrenceStatus.SCHEDULED.value
        self.occurrence_repository.save(occurrence)
        return NodeResult.failure("TEST_DOWNSTREAM_FAILED", "Injected downstream failure after changing resource.")


def phase50_playbook(*, downstream_capability: str, compensation_mode: str) -> PlaybookDefinition:
    return PlaybookDefinition(
        playbook_id="calendar.phase50.compensation",
        version="1.0.0",
        schema_version="1.0",
        name="Phase 50 Calendar Compensation",
        requirements={
            "calendar": {"capabilities": [CALENDAR_EVENT_CREATE_CAPABILITY]},
            "downstream": {"capabilities": [downstream_capability]},
        },
        nodes=(
            PlaybookNode("trigger", "trigger", {"event_type": "calendar.create.requested"}),
            PlaybookNode(
                "create-calendar",
                "capability",
                {
                    "capability": CALENDAR_EVENT_CREATE_CAPABILITY,
                    "compensation": {"mode": compensation_mode},
                    "input": {
                        "campaign_id": {"from_event": "payload", "path": "campaign_id"},
                        "end": {"from_event": "payload", "path": "end"},
                        "occurrence_key": {"from_event": "payload", "path": "occurrence_key"},
                        "schedule_id": {"from_event": "payload", "path": "schedule_id"},
                        "sequence_number": {"from_event": "payload", "path": "sequence_number"},
                        "start": {"from_event": "payload", "path": "start"},
                        "status": {"from_event": "payload", "path": "status"},
                        "timezone": {"from_event": "payload", "path": "timezone"},
                    },
                    "requirement": "calendar",
                    "retry": {"max_attempts": 2},
                },
            ),
            PlaybookNode(
                "downstream",
                "capability",
                {"capability": downstream_capability, "requirement": "downstream"},
            ),
        ),
        edges=(PlaybookEdge("trigger", "create-calendar"), PlaybookEdge("create-calendar", "downstream")),
    )


def phase50_registry(*, downstream_capability: str) -> RuntimeRegistry:
    registry = mutation_registry()
    registry.register_component(
        ComponentManifest(
            component_id=f"{downstream_capability.replace('.', '-')}-component",
            provider="test",
            version="0.1.0",
            sdk_version="runtime-contracts-0.1",
            capabilities=(CapabilityDescriptor(downstream_capability, "0.1.0", CapabilityMode.READ.value),),
        )
    )
    registry.register_install(
        Install(
            install_id="test-downstream-install",
            workspace_id="linkedin",
            provider="test",
            account_ref="memory",
            component_bindings={
                downstream_capability: ComponentBinding(f"{downstream_capability.replace('.', '-')}-component")
            },
            grants=InstallGrants(allowed_capabilities=(downstream_capability,)),
        )
    )
    return registry


def phase50_deployment() -> PlaybookDeployment:
    base = calendar_create_deployment()
    return replace(
        base,
        deployment_id="phase50-calendar-compensation",
        playbook_id="calendar.phase50.compensation",
        requirement_bindings={
            "calendar": RequirementBinding("calendar-publication-local"),
            "downstream": RequirementBinding("test-downstream-install"),
        },
        policy=DeploymentPolicy(allow_mutations=True, require_approval_for_writes=True),
    )


def phase50_executor(stack: dict[str, Any], downstream_handler: Any, *, compensation_mode: str):
    registry = phase50_registry(downstream_capability=downstream_handler.capability_id)
    deployment = phase50_deployment()
    plan = compile_execution_plan(
        phase50_playbook(
            downstream_capability=downstream_handler.capability_id,
            compensation_mode=compensation_mode,
        ),
        deployment,
        registry,
    )
    handlers = CapabilityHandlerRegistry()
    create_handler = CountingCalendarEventCreateHandler(
        calendar_service=stack["calendar_service"],
        occurrence_repository=stack["scheduling"].occurrence_repository,
    )
    handlers.register(create_handler)
    handlers.register(downstream_handler)
    executor = PlaybookExecutor(
        handlers,
        policy_engine=RuntimePolicyEngine(registry=registry, deployments={deployment.deployment_id: deployment}),
        mutation_journal=SqliteMutationJournal(Path(stack["tmp"]) / "runtime-mutations.sqlite3"),
    )
    return executor, create_handler, downstream_handler, plan


def occurrence_records(stack: dict[str, Any]) -> list[ScheduleOccurrence]:
    return stack["scheduling"].occurrence_repository.list_all(workspace_id="linkedin")


def create_preexisting_occurrence(stack: dict[str, Any]) -> ScheduleOccurrence:
    occurrence = ScheduleOccurrence(
        id="preexisting-occurrence",
        workspace_id="linkedin",
        schedule_id="schedule-preexisting",
        campaign_id="campaign-preexisting",
        occurrence_key="phase50:preexisting",
        generation_version=1,
        sequence_number=1,
        scheduled_at_local="2026-08-18T08:00:00+02:00",
        timezone="Europe/Amsterdam",
        scheduled_at_utc="2026-08-18T06:00:00+00:00",
        status=ScheduleOccurrenceStatus.PROJECTED.value,
        metadata={"created_by": "fixture"},
    )
    return stack["scheduling"].occurrence_repository.create(occurrence)


def approve_waiting_mutation(executor: PlaybookExecutor, execution_id: str):
    mutation_id = pending_mutation_id(executor, execution_id)
    return executor.approve_mutation_intent(mutation_id, actor_id="operator-50", actor_type="test_operator")


def compensation_records(executor: PlaybookExecutor, execution_id: str):
    return [
        node
        for node in executor.ledger.list_node_executions(execution_id)
        if node.node_id == "create-calendar.compensation"
    ]


def test_public_delete_capability_is_not_exposed() -> None:
    component = phase41_runtime_registry().components[CALENDAR_COMPONENT_ID]

    assert component.capability("calendar.event.delete") is None
    assert not component.supports("calendar.event.delete")
    assert not hasattr(ScheduleOccurrenceRepository, "delete")


def test_successful_downstream_keeps_created_resource_and_skips_compensation(calendar_stack) -> None:  # noqa: F811
    executor, create_handler, echo, plan = phase50_executor(
        calendar_stack,
        EchoHandler(),
        compensation_mode="on_downstream_failure",
    )
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event(idempotency_key="phase50-success"))

    approved = approve_waiting_mutation(executor, waiting.execution.execution_id)

    assert approved.execution.state == ExecutionState.SUCCEEDED.value
    assert create_handler.calls == 1
    assert echo.calls == 1
    assert len(occurrence_records(calendar_stack)) == 1
    assert compensation_records(executor, approved.execution.execution_id) == []


def test_downstream_failure_compensates_exact_created_resource(calendar_stack) -> None:  # noqa: F811
    preexisting = create_preexisting_occurrence(calendar_stack)
    executor, create_handler, failing, plan = phase50_executor(
        calendar_stack,
        FailingHandler(),
        compensation_mode="on_downstream_failure",
    )
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event(idempotency_key="phase50-failure"))

    approved = approve_waiting_mutation(executor, waiting.execution.execution_id)

    records = occurrence_records(calendar_stack)
    assert approved.execution.state == ExecutionState.FAILED.value
    assert create_handler.calls == 1
    assert failing.calls == 1
    assert [item.id for item in records] == [preexisting.id]
    compensation = compensation_records(executor, approved.execution.execution_id)[-1]
    assert compensation.state == ExecutionState.SUCCEEDED.value
    assert compensation.metadata["compensation_state"] == "compensated"
    assert compensation.metadata["verified"] is True
    trace = trace_execution(executor.ledger, approved.execution.execution_id).to_dict()
    assert "calendar-occurrence:" in str(trace)
    assert "secret" not in str(trace).lower()


def test_changed_resource_blocks_private_compensation(calendar_stack) -> None:  # noqa: F811
    executor, _create_handler, _failing, plan = phase50_executor(
        calendar_stack,
        MutatingFailureHandler(calendar_stack["scheduling"].occurrence_repository),
        compensation_mode="on_downstream_failure",
    )
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event(idempotency_key="phase50-changed"))

    approved = approve_waiting_mutation(executor, waiting.execution.execution_id)

    records = occurrence_records(calendar_stack)
    assert approved.execution.state == ExecutionState.FAILED.value
    assert len(records) == 1
    assert records[0].status == ScheduleOccurrenceStatus.SCHEDULED.value
    compensation = compensation_records(executor, approved.execution.execution_id)[-1]
    assert compensation.state == ExecutionState.FAILED.value
    assert compensation.error_code == "COMPENSATION_BLOCKED_RESOURCE_CHANGED"


def test_receipt_tampering_cannot_delete_wrong_resource(calendar_stack) -> None:  # noqa: F811
    preexisting = create_preexisting_occurrence(calendar_stack)
    executor, handler, _echo, plan = phase50_executor(
        calendar_stack,
        EchoHandler(),
        compensation_mode="on_downstream_failure",
    )
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event(idempotency_key="phase50-tamper"))
    approved = approve_waiting_mutation(executor, waiting.execution.execution_id)
    receipt = MutationReceipt.from_dict(approved.context.node_outputs["create-calendar"]["mutation_receipt"])
    tampered = replace(
        receipt,
        resource_ref=f"calendar-occurrence:{preexisting.id}",
        metadata={
            **receipt.metadata,
            "created_resource": {"resource_id": preexisting.id, "resource_type": "schedule_occurrence"},
        },
    )
    compensation = _compensation_intent_for_receipt(approved.execution.execution_id, tampered)

    with pytest.raises(PlaybookExecutionError) as error:
        handler.compensate(receipt=tampered, context=approved.context, compensation=compensation)

    assert error.value.code == "COMPENSATION_BLOCKED_OWNERSHIP_MISMATCH"
    assert {item.id for item in occurrence_records(calendar_stack)} == {
        preexisting.id,
        str(receipt.metadata["created_resource"]["resource_id"]),
    }


def test_direct_compensation_is_idempotent_after_journaled_success(calendar_stack) -> None:  # noqa: F811
    executor, handler, _echo, plan = phase50_executor(
        calendar_stack,
        EchoHandler(),
        compensation_mode="on_downstream_failure",
    )
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event(idempotency_key="phase50-direct-idem"))
    approved = approve_waiting_mutation(executor, waiting.execution.execution_id)
    receipt = MutationReceipt.from_dict(approved.context.node_outputs["create-calendar"]["mutation_receipt"])
    compensation = _compensation_intent_for_receipt(approved.execution.execution_id, receipt)

    first = handler.compensate(receipt=receipt, context=approved.context, compensation=compensation)
    second = handler.compensate(receipt=receipt, context=approved.context, compensation=compensation)

    assert first.verified is True
    assert second.verified is True
    assert second.metadata["already_absent"] is True
    assert occurrence_records(calendar_stack) == []


def test_playbook_cannot_resolve_private_compensator(calendar_stack) -> None:  # noqa: F811
    registry = mutation_registry()
    deployment = replace(
        calendar_create_deployment(),
        playbook_id="calendar.phase50.bad-delete",
    )
    playbook = PlaybookDefinition(
        playbook_id="calendar.phase50.bad-delete",
        version="1.0.0",
        schema_version="1.0",
        name="Bad Delete",
        requirements={"calendar": {"capabilities": ["calendar.event.delete"]}},
        nodes=(
            PlaybookNode("trigger", "trigger", {"event_type": "calendar.delete.requested"}),
            PlaybookNode(
                "delete-calendar",
                "capability",
                {"requirement": "calendar", "capability": "calendar.event.delete"},
            ),
        ),
        edges=(PlaybookEdge("trigger", "delete-calendar"),),
    )

    with pytest.raises((CapabilityResolutionError, DeploymentValidationError)):
        compile_execution_plan(playbook, deployment, registry)


def test_generic_core_has_no_calendar_compensation_branch() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/core/runtime").glob("*.py"))

    assert "calendar.event.create" not in combined
    assert "calendar.event.delete" not in combined
    assert "ScheduleOccurrence" not in combined


def _compensation_intent_for_receipt(execution_id: str, receipt: MutationReceipt) -> CompensationIntent:
    fingerprint = mutation_input_fingerprint(
        {
            "mode": "on_downstream_failure",
            "mutation_id": receipt.mutation_id,
            "resource_ref": receipt.resource_ref,
            "result_fingerprint": receipt.result_fingerprint,
        }
    )
    return CompensationIntent(
        compensation_id=build_compensation_id(
            original_mutation_id=receipt.mutation_id,
            resource_ref=receipt.resource_ref,
            compensation_fingerprint=fingerprint,
        ),
        original_mutation_id=receipt.mutation_id,
        execution_id=execution_id,
        node_id="create-calendar",
        capability_id=receipt.capability_id,
        component_id=receipt.component_id,
        install_id=receipt.install_id,
        resource_ref=receipt.resource_ref,
        compensation_fingerprint=fingerprint,
        idempotency_key=build_compensation_idempotency_key(
            original_mutation_id=receipt.mutation_id,
            resource_ref=receipt.resource_ref,
        ),
    )
