from __future__ import annotations

import json
import socket
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from publication_calendar_runtime_handlers import (
    CALENDAR_COMPONENT_ID,
    CALENDAR_EVENT_CREATE_CAPABILITY,
    CalendarEventCreateHandler,
)
from runtime_foundation_mappings import phase41_runtime_registry
from src.core.runtime import (
    DeploymentPolicy,
    EventEnvelope,
    EventSource,
    ExecutionState,
    InstallGrants,
    JsonMutationJournal,
    PlaybookDefinition,
    PlaybookDeployment,
    PlaybookExecutor,
    RequirementBinding,
    RuntimePolicyEngine,
    compile_execution_plan,
    trace_execution,
)
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.results import NodeResult
from src.core.scheduling import ScheduleOccurrenceStatus
from tests.test_media_library_phase11 import Phase11Config, runtime_with_library
from tests.test_support import isolated_channel_store


class CountingCalendarEventCreateHandler(CalendarEventCreateHandler):
    def __init__(self, *args, fail_before_once: bool = False, fail_after_once: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0
        self.fail_before_once = fail_before_once
        self.fail_after_once = fail_after_once
        self._failed_before = False
        self._failed_after = False

    def execute(self, **kwargs) -> NodeResult:  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail_before_once and not self._failed_before:
            self._failed_before = True
            return NodeResult.failure("CAPABILITY_EXECUTION_FAILED", "Injected failure before mutation.")
        result = super().execute(**kwargs)
        if self.fail_after_once and not self._failed_after:
            self._failed_after = True
            return NodeResult.failure("CAPABILITY_EXECUTION_FAILED", "Injected failure after mutation.")
        return result


def load_create_playbook() -> PlaybookDefinition:
    payload = json.loads(Path("tests/fixtures/playbooks/phase48_calendar_create.json").read_text(encoding="utf-8"))
    return PlaybookDefinition.from_dict(payload)


def calendar_create_deployment(*, allow_mutations: bool = True) -> PlaybookDeployment:
    return PlaybookDeployment(
        deployment_id="phase48-calendar-create",
        playbook_id="calendar.phase48.create",
        playbook_version="1.0.0",
        workspace_id="linkedin",
        requirement_bindings={"calendar": RequirementBinding("calendar-publication-local")},
        policy=DeploymentPolicy(allow_mutations=allow_mutations, require_approval_for_writes=True),
    )


def calendar_create_event(
    *,
    idempotency_key: str = "phase48-calendar-create",
    occurrence_key: str = "phase48:approved-create",
    start: str = "2026-08-18T09:00:00+02:00",
) -> EventEnvelope:
    return EventEnvelope(
        event_type="calendar.create.requested",
        source=EventSource(component="phase48-test", provider="calendar"),
        workspace_id="linkedin",
        correlation_id="phase48-correlation",
        trace_id="phase48-trace",
        idempotency_key=idempotency_key,
        payload={
            "campaign_id": "campaign-phase48",
            "end": start,
            "occurrence_key": occurrence_key,
            "schedule_id": "schedule-phase48",
            "sequence_number": 1,
            "start": start,
            "status": ScheduleOccurrenceStatus.PROJECTED.value,
            "timezone": "Europe/Amsterdam",
        },
    )


@pytest.fixture()
def calendar_stack():
    with tempfile.TemporaryDirectory() as tmp:
        with isolated_channel_store(Path(tmp)):
            config = Phase11Config()
            config.media_dir = Path(tmp) / "tmp_media"
            config.content_dir = Path(tmp) / "content"
            config.media_storage_root = Path(tmp) / "media-root"
            config.linkedin_user_data_dir = Path(tmp) / "profile"
            config.media_dir.mkdir()
            config.content_dir.mkdir()
            config.linkedin_user_data_dir.mkdir()
            runtime = runtime_with_library(config)
            runtime.content_service(config)
            runtime.publication_planning_service(config)
            runtime.publication_execution_service(config)
            scheduling = runtime.schedule_materialization_service(config)
            calendar_service = runtime.execution_calendar_service(config)
            yield {
                "calendar_service": calendar_service,
                "journal_path": Path(tmp) / "mutation_journal.json",
                "runtime": runtime,
                "scheduling": scheduling,
                "tmp": tmp,
            }


def mutation_registry(*, allow_mutations: bool = True, allow_capability: bool = True):
    registry = phase41_runtime_registry()
    allowed = (CALENDAR_EVENT_CREATE_CAPABILITY,) if allow_capability else ()
    registry.register_install(
        replace(
            registry.installs["calendar-publication-local"],
            grants=InstallGrants(
                allowed_capabilities=allowed,
                allow_mutations=allow_mutations,
                require_approval_for_writes=True,
            ),
        )
    )
    return registry


def compile_create_plan(registry=None, deployment=None):
    registry = registry or mutation_registry()
    deployment = deployment or calendar_create_deployment()
    return compile_execution_plan(load_create_playbook(), deployment, registry)


def mutation_executor(
    calendar_stack,
    *,
    registry=None,
    deployment=None,
    handler: CalendarEventCreateHandler | None = None,
):
    registry = registry or mutation_registry()
    deployment = deployment or calendar_create_deployment()
    handlers = CapabilityHandlerRegistry()
    handler = handler or CountingCalendarEventCreateHandler(
        calendar_service=calendar_stack["calendar_service"],
        occurrence_repository=calendar_stack["scheduling"].occurrence_repository,
    )
    handlers.register(handler)
    executor = PlaybookExecutor(
        handlers,
        policy_engine=RuntimePolicyEngine(registry=registry, deployments={deployment.deployment_id: deployment}),
        mutation_journal=JsonMutationJournal(calendar_stack["journal_path"]),
    )
    return executor, handler, compile_create_plan(registry, deployment)


def create_records(executor: PlaybookExecutor, execution_id: str):
    return [node for node in executor.ledger.list_node_executions(execution_id) if node.node_id == "create-calendar"]


def occurrence_count(calendar_stack, occurrence_key: str = "phase48:approved-create") -> int:
    return sum(
        1
        for item in calendar_stack["scheduling"].occurrence_repository.list_all(workspace_id="linkedin")
        if item.occurrence_key == occurrence_key
    )


def pending_mutation_id(executor: PlaybookExecutor, execution_id: str) -> str:
    approval = executor.approval_store.get(execution_id, "create-calendar")
    assert approval is not None
    return str(approval.metadata["mutation_id"])


def test_calendar_event_create_is_existing_write_capability() -> None:
    component = phase41_runtime_registry().components[CALENDAR_COMPONENT_ID]

    capability = component.capability(CALENDAR_EVENT_CREATE_CAPABILITY)

    assert capability is not None
    assert capability.mode == "write"
    assert component.supports(CALENDAR_EVENT_CREATE_CAPABILITY)


def test_no_approval_creates_intent_but_zero_side_effects(calendar_stack) -> None:
    executor, handler, plan = mutation_executor(calendar_stack)

    with (
        patch.object(socket, "socket", side_effect=AssertionError("network forbidden")),
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess forbidden")),
    ):
        waiting = executor.execute(plan=plan, trigger_event=calendar_create_event())

    assert waiting.execution.state == ExecutionState.WAITING.value
    assert handler.calls == 0
    assert occurrence_count(calendar_stack) == 0
    node = create_records(executor, waiting.execution.execution_id)[-1]
    assert node.state == ExecutionState.WAITING.value
    assert node.metadata["approval_required"] is True
    mutation_id = pending_mutation_id(executor, waiting.execution.execution_id)
    persisted = JsonMutationJournal(calendar_stack["journal_path"]).get(mutation_id)
    assert persisted is not None
    assert persisted.state == "prepared"
    assert persisted.intent.input_fingerprint == node.metadata["input_fingerprint"]


def test_approved_calendar_event_create_executes_once_and_records_receipt(calendar_stack) -> None:
    executor, handler, plan = mutation_executor(calendar_stack)
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event())
    mutation_id = pending_mutation_id(executor, waiting.execution.execution_id)

    approved = executor.approve_mutation_intent(mutation_id, actor_id="operator-1", actor_type="test_operator")
    second = executor.approve_mutation_intent(mutation_id, actor_id="operator-1", actor_type="test_operator")

    assert approved.execution.state == ExecutionState.SUCCEEDED.value
    assert second.execution.state == ExecutionState.SUCCEEDED.value
    assert handler.calls == 1
    assert occurrence_count(calendar_stack) == 1
    output = approved.context.node_outputs["create-calendar"]
    assert output["readback_verified"] is True
    assert output["resource_ref"].startswith("calendar-occurrence:")
    receipt = output["mutation_receipt"]
    assert receipt["mutation_id"] == mutation_id
    assert receipt["resource_ref"] == output["resource_ref"]
    persisted = JsonMutationJournal(calendar_stack["journal_path"]).get(mutation_id)
    assert persisted is not None
    assert persisted.state == "applied"
    assert persisted.receipt is not None
    assert persisted.receipt.resource_ref == output["resource_ref"]
    approval = executor.approval_store.get(waiting.execution.execution_id, "create-calendar")
    assert approval is not None
    assert approval.actor_id == "operator-1"
    assert approval.actor_type == "test_operator"
    trace = trace_execution(executor.ledger, approved.execution.execution_id).to_dict()
    node = next(
        item for item in trace["nodes"] if item["node_id"] == "create-calendar" and item["state"] == "succeeded"
    )
    assert node["metadata"]["mutation_id"] == mutation_id
    assert node["metadata"]["policy_decision"] == "allow"
    assert "secret" not in str(trace).lower()


def test_reject_never_applies_calendar_mutation(calendar_stack) -> None:
    executor, handler, plan = mutation_executor(calendar_stack)
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event())
    mutation_id = pending_mutation_id(executor, waiting.execution.execution_id)

    rejected = executor.reject_execution_node(
        waiting.execution.execution_id,
        "create-calendar",
        actor_id="operator-1",
        actor_type="test_operator",
    )

    assert rejected.execution.state == ExecutionState.FAILED.value
    assert handler.calls == 0
    assert occurrence_count(calendar_stack) == 0
    persisted = JsonMutationJournal(calendar_stack["journal_path"]).get(mutation_id)
    assert persisted is not None
    assert persisted.state == "failed"
    assert persisted.receipt is None


def test_changed_input_after_approval_invalidates_old_approval(calendar_stack) -> None:
    executor, handler, plan = mutation_executor(calendar_stack)
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event())
    mutation_id = pending_mutation_id(executor, waiting.execution.execution_id)
    approval = executor.approval_store.approve(
        waiting.execution.execution_id,
        "create-calendar",
        actor_id="operator-1",
        actor_type="test_operator",
    )
    executor.mutation_journal.mark_approved(mutation_id, approval_id=approval.approval_id)
    context = executor._contexts[waiting.execution.execution_id]
    changed_event = replace(
        context.trigger_event,
        payload={
            **context.trigger_event.payload,
            "start": "2026-08-18T10:00:00+02:00",
            "end": "2026-08-18T10:00:00+02:00",
        },
    )
    executor._contexts[waiting.execution.execution_id] = replace(context, trigger_event=changed_event)

    outcome = executor.resume_execution(waiting.execution.execution_id)

    assert outcome.execution.state == ExecutionState.WAITING.value
    assert handler.calls == 0
    assert occurrence_count(calendar_stack) == 0
    assert pending_mutation_id(executor, waiting.execution.execution_id) != mutation_id


def test_policy_revocation_after_approval_blocks_before_handler(calendar_stack) -> None:
    registry = mutation_registry()
    deployment = calendar_create_deployment()
    executor, handler, plan = mutation_executor(calendar_stack, registry=registry, deployment=deployment)
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event())
    mutation_id = pending_mutation_id(executor, waiting.execution.execution_id)
    approval = executor.approval_store.approve(waiting.execution.execution_id, "create-calendar", actor="tester")
    executor.mutation_journal.mark_approved(mutation_id, approval_id=approval.approval_id)
    registry.register_install(replace(registry.installs["calendar-publication-local"], grants=InstallGrants()))

    outcome = executor.resume_execution(waiting.execution.execution_id)

    assert outcome.execution.state == ExecutionState.FAILED.value
    assert create_records(executor, waiting.execution.execution_id)[-1].error_code == "CAPABILITY_NOT_GRANTED"
    assert handler.calls == 0
    assert occurrence_count(calendar_stack) == 0


def test_duplicate_event_does_not_create_duplicate_resource(calendar_stack) -> None:
    executor, handler, plan = mutation_executor(calendar_stack)
    first = executor.start_execution_once(plan=plan, trigger_event=calendar_create_event())
    mutation_id = pending_mutation_id(executor, first.execution.execution_id)
    approved = executor.approve_mutation_intent(mutation_id, actor="tester")

    duplicate = executor.start_execution_once(plan=plan, trigger_event=calendar_create_event())

    assert approved.execution.execution_id == duplicate.execution.execution_id
    assert handler.calls == 1
    assert occurrence_count(calendar_stack) == 1


@pytest.mark.parametrize("failure_mode", ["before", "after"])
def test_retry_paths_do_not_duplicate_calendar_mutation(calendar_stack, failure_mode: str) -> None:
    handler = CountingCalendarEventCreateHandler(
        calendar_service=calendar_stack["calendar_service"],
        occurrence_repository=calendar_stack["scheduling"].occurrence_repository,
        fail_before_once=failure_mode == "before",
        fail_after_once=failure_mode == "after",
    )
    executor, handler, plan = mutation_executor(calendar_stack, handler=handler)
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event())
    mutation_id = pending_mutation_id(executor, waiting.execution.execution_id)

    approved = executor.approve_mutation_intent(mutation_id, actor="tester")

    assert approved.execution.state == ExecutionState.SUCCEEDED.value
    assert handler.calls == 2
    assert occurrence_count(calendar_stack) == 1
    attempts = create_records(executor, approved.execution.execution_id)
    terminal_attempts = [item for item in attempts if item.state in {"failed", "succeeded"}]
    assert [item.state for item in terminal_attempts] == ["failed", "succeeded"]
    assert [item.attempt for item in terminal_attempts] == sorted(item.attempt for item in terminal_attempts)


def test_write_policy_denies_before_handler(calendar_stack) -> None:
    registry = mutation_registry(allow_mutations=False)
    deployment = calendar_create_deployment(allow_mutations=False)
    executor, handler, plan = mutation_executor(calendar_stack, registry=registry, deployment=deployment)

    outcome = executor.execute(plan=plan, trigger_event=calendar_create_event())

    assert outcome.execution.state == ExecutionState.FAILED.value
    assert create_records(executor, outcome.execution.execution_id)[-1].error_code == "MUTATION_NOT_ALLOWED"
    assert handler.calls == 0
    assert occurrence_count(calendar_stack) == 0


def test_secrets_absent_from_intent_receipt_and_audit(calendar_stack) -> None:
    executor, _handler, plan = mutation_executor(calendar_stack)
    waiting = executor.execute(plan=plan, trigger_event=calendar_create_event())
    mutation_id = pending_mutation_id(executor, waiting.execution.execution_id)
    approved = executor.approve_mutation_intent(mutation_id, actor="tester")
    persisted = JsonMutationJournal(calendar_stack["journal_path"]).get(mutation_id)

    combined = json.dumps(
        {
            "intent": persisted.intent.to_dict() if persisted else {},
            "receipt": persisted.receipt.to_dict() if persisted and persisted.receipt else {},
            "trace": trace_execution(executor.ledger, approved.execution.execution_id).to_dict(),
        },
        sort_keys=True,
    ).lower()
    assert "password" not in combined
    assert "credential" not in combined
    assert "api_key" not in combined
    assert "token" not in combined
