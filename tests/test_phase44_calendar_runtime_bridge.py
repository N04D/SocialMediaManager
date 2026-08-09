from __future__ import annotations

import json
import socket
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from publication_calendar_runtime_handlers import (
    CALENDAR_COMPONENT_ID,
    CALENDAR_EVENT_READ_CAPABILITY,
    CalendarEventReadHandler,
    register_calendar_runtime_handlers,
)
from publication_scheduling import (
    PublicationScheduleRepository,
    ScheduleMaterializationService,
    ScheduleOccurrenceRepository,
)
from runtime_foundation_mappings import phase41_runtime_registry
from src.core.runtime.deployments import PlaybookDeployment, RequirementBinding
from src.core.runtime.errors import DeploymentValidationError, PlaybookExecutionError
from src.core.runtime.events import EventEnvelope, EventSource
from src.core.runtime.execution_context import ExecutionContext
from src.core.runtime.executor import PlaybookExecutor
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.ledger import ExecutionState
from src.core.runtime.plans import ExecutionPlanNode, compile_execution_plan
from src.core.runtime.playbooks import PlaybookDefinition, PlaybookNode
from src.core.runtime.results import NodeResultStatus
from src.core.runtime.tracing import trace_execution
from src.core.scheduling import ScheduleOccurrence
from tests.test_media_library_phase11 import Phase11Config, runtime_with_library
from tests.test_support import isolated_channel_store


def load_calendar_playbook() -> PlaybookDefinition:
    payload = json.loads(Path("tests/fixtures/playbooks/phase44_calendar_read.json").read_text(encoding="utf-8"))
    return PlaybookDefinition.from_dict(payload)


def calendar_deployment(install_id: str = "calendar-publication-local") -> PlaybookDeployment:
    return PlaybookDeployment(
        deployment_id="phase44-calendar-read",
        playbook_id="calendar.phase44.read",
        playbook_version="1.0.0",
        workspace_id="linkedin",
        requirement_bindings={"calendar": RequirementBinding(install_id)},
    )


def calendar_event(payload: dict[str, object] | None = None) -> EventEnvelope:
    return EventEnvelope(
        event_type="calendar.read.requested",
        source=EventSource(component="phase44-test", provider="calendar"),
        workspace_id="linkedin",
        correlation_id="phase44-correlation",
        trace_id="phase44-trace",
        idempotency_key="phase44-calendar-read",
        payload=payload
        or {
            "start": "2026-08-10T00:00:00+02:00",
            "end": "2026-08-17T00:00:00+02:00",
            "timezone": "Europe/Amsterdam",
            "status": "scheduled",
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
                "tmp": tmp,
                "config": config,
                "runtime": runtime,
                "scheduling": scheduling,
                "calendar_service": calendar_service,
            }


def seed_occurrence(scheduling: ScheduleMaterializationService, *, occurrence_id: str, at: str, status: str) -> None:
    scheduling.occurrence_repository.create(
        ScheduleOccurrence(
            id=occurrence_id,
            workspace_id="linkedin",
            schedule_id="schedule-phase44",
            campaign_id="campaign-phase44",
            occurrence_key=f"phase44:{occurrence_id}",
            generation_version=1,
            sequence_number=1 if occurrence_id.endswith("1") else 2,
            scheduled_at_local=at,
            timezone="Europe/Amsterdam",
            scheduled_at_utc=at,
            status=status,
        )
    )


def compile_calendar_plan():
    return compile_execution_plan(load_calendar_playbook(), calendar_deployment(), phase41_runtime_registry())


def test_real_calendar_service_read_through_playbook_executor(calendar_stack) -> None:
    seed_occurrence(
        calendar_stack["scheduling"],
        occurrence_id="occurrence-1",
        at="2026-08-11T08:00:00+00:00",
        status="scheduled",
    )
    seed_occurrence(
        calendar_stack["scheduling"],
        occurrence_id="occurrence-2",
        at="2026-08-20T08:00:00+00:00",
        status="scheduled",
    )
    handler_registry = CapabilityHandlerRegistry()
    handler = register_calendar_runtime_handlers(
        handler_registry,
        calendar_service=calendar_stack["calendar_service"],
    )
    executor = PlaybookExecutor(handler_registry)

    with (
        patch.object(socket, "socket", side_effect=AssertionError("network forbidden")) as socket_mock,
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess forbidden")) as run_mock,
        patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess forbidden")) as popen_mock,
        patch.object(PublicationScheduleRepository, "create", side_effect=AssertionError("mutation forbidden")) as sc,
        patch.object(PublicationScheduleRepository, "save", side_effect=AssertionError("mutation forbidden")) as ss,
        patch.object(ScheduleOccurrenceRepository, "create", side_effect=AssertionError("mutation forbidden")) as oc,
        patch.object(ScheduleOccurrenceRepository, "save", side_effect=AssertionError("mutation forbidden")) as os,
        patch.object(
            ScheduleMaterializationService,
            "materialize_schedule",
            side_effect=AssertionError("materialization forbidden"),
        ) as materialize,
        patch.object(
            calendar_stack["calendar_service"],
            "list_calendar_entries",
            wraps=calendar_stack["calendar_service"].list_calendar_entries,
        ) as read_spy,
    ):
        outcome = executor.execute(plan=compile_calendar_plan(), trigger_event=calendar_event())

    assert handler.component_id == CALENDAR_COMPONENT_ID
    assert handler.capability_id == CALENDAR_EVENT_READ_CAPABILITY
    assert outcome.execution.state == ExecutionState.SUCCEEDED.value
    assert read_spy.call_count == 1
    for mutation in (sc, ss, oc, os, materialize, socket_mock, run_mock, popen_mock):
        mutation.assert_not_called()
    output = outcome.context.node_outputs["read-calendar"]
    assert output["events"] == [
        {
            "attention_required": False,
            "blockers": [],
            "campaign_id": "campaign-phase44",
            "channel_account_id": "",
            "channel_plugin_id": "",
            "end": "2026-08-11T08:00:00+00:00",
            "entry_type": "projected_occurrence",
            "id": "calendar_occurrence_occurrence-1",
            "occurrence_id": "occurrence-1",
            "plan_id": "",
            "safe_summary": "",
            "schedule_id": "schedule-phase44",
            "source": "publication-calendar-local",
            "start": "2026-08-11T08:00:00+00:00",
            "status": "scheduled",
            "target_id": "",
            "timezone": "Europe/Amsterdam",
            "title": "Occurrence 1",
            "workspace_id": "linkedin",
        }
    ]
    trace = trace_execution(executor.ledger, outcome.execution.execution_id).to_dict()
    read_node = next(node for node in trace["nodes"] if node["node_id"] == "read-calendar")
    assert read_node["metadata"] == {
        "capability": "calendar.event.read",
        "component_id": "publication-calendar-local",
        "install_id": "calendar-publication-local",
        "kind": "capability",
        "provider": "calendar",
        "requirement": "calendar",
    }


def test_calendar_read_empty_result_succeeds(calendar_stack) -> None:
    handler_registry = CapabilityHandlerRegistry()
    register_calendar_runtime_handlers(handler_registry, calendar_service=calendar_stack["calendar_service"])
    executor = PlaybookExecutor(handler_registry)

    outcome = executor.execute(plan=compile_calendar_plan(), trigger_event=calendar_event())

    assert outcome.execution.state == ExecutionState.SUCCEEDED.value
    assert outcome.context.node_outputs["read-calendar"] == {"events": [], "source": "publication-calendar-local"}


def test_calendar_read_invalid_range_fails_cleanly(calendar_stack) -> None:
    handler_registry = CapabilityHandlerRegistry()
    register_calendar_runtime_handlers(handler_registry, calendar_service=calendar_stack["calendar_service"])
    executor = PlaybookExecutor(handler_registry)

    outcome = executor.execute(
        plan=compile_calendar_plan(),
        trigger_event=calendar_event(
            {
                "start": "2026-08-17T00:00:00+02:00",
                "end": "2026-08-10T00:00:00+02:00",
                "timezone": "Europe/Amsterdam",
                "status": "scheduled",
            }
        ),
    )

    assert outcome.execution.state == ExecutionState.FAILED.value
    failed = [
        node
        for node in executor.ledger.list_node_executions(outcome.execution.execution_id)
        if node.node_id == "read-calendar"
    ]
    assert failed[-1].error_code == "CALENDAR_INVALID_RANGE"


def test_calendar_read_service_failure_maps_to_capability_error() -> None:
    class FailingCalendarService:
        def list_calendar_entries(self, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("storage unavailable")

    handler_registry = CapabilityHandlerRegistry()
    register_calendar_runtime_handlers(handler_registry, calendar_service=FailingCalendarService())  # type: ignore[arg-type]
    executor = PlaybookExecutor(handler_registry)

    outcome = executor.execute(plan=compile_calendar_plan(), trigger_event=calendar_event())

    assert outcome.execution.state == ExecutionState.FAILED.value
    failed = [
        node
        for node in executor.ledger.list_node_executions(outcome.execution.execution_id)
        if node.node_id == "read-calendar"
    ]
    assert failed[-1].error_code == "CAPABILITY_EXECUTION_FAILED"


def test_missing_install_fails_before_execution() -> None:
    with pytest.raises(DeploymentValidationError) as exc:
        compile_execution_plan(
            load_calendar_playbook(), calendar_deployment("missing-calendar"), phase41_runtime_registry()
        )

    assert exc.value.details["error_code"] == "INSTALL_MISSING"


def test_missing_handler_is_controlled_runtime_failure() -> None:
    executor = PlaybookExecutor(CapabilityHandlerRegistry())

    outcome = executor.execute(plan=compile_calendar_plan(), trigger_event=calendar_event())

    assert outcome.execution.state == ExecutionState.FAILED.value
    failed = [
        node
        for node in executor.ledger.list_node_executions(outcome.execution.execution_id)
        if node.node_id == "read-calendar"
    ]
    assert failed[-1].error_code == "HANDLER_NOT_FOUND"


def test_calendar_mutation_capability_is_not_registered_as_handler(calendar_stack) -> None:
    handler_registry = CapabilityHandlerRegistry()
    register_calendar_runtime_handlers(handler_registry, calendar_service=calendar_stack["calendar_service"])

    with pytest.raises(PlaybookExecutionError) as exc:
        handler_registry.resolve("publication-calendar-local", "calendar.event.create")

    assert exc.value.code == "HANDLER_NOT_FOUND"


def test_calendar_handler_rejects_secret_shaped_input(calendar_stack) -> None:
    handler = CalendarEventReadHandler(calendar_service=calendar_stack["calendar_service"])

    result = handler.execute(
        context=ExecutionContext(
            execution_id="exec_phase44",
            deployment_id="phase44-calendar-read",
            trigger_event=calendar_event(),
        ),
        node=PlaybookNode("read-calendar", "capability"),
        resolved_node=ExecutionPlanNode("read-calendar", "capability"),
        input_data={"api_" + "key": "value"},
    )

    assert result.status == NodeResultStatus.FAILURE.value
    assert result.error_code == "calendar.input_secret_value"
