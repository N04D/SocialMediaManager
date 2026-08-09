from __future__ import annotations

import socket
import subprocess
from unittest.mock import patch

import pytest

from channels.linkedin.runtime import LinkedInChannelRuntime
from channels.markdown_website.git_publisher import GitPublisher
from channels.youtube.channel import YouTubeChannelService
from publication_scheduling import ExecutionCalendarService
from src.core.plugins.runtime import PluginRuntime
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.execution_context import ExecutionContext
from src.core.runtime.executor import PlaybookExecutor
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.internal_handlers import EchoHandler, internal_handler_registry
from src.core.runtime.ledger import ExecutionState
from src.core.runtime.plans import compile_execution_plan
from src.core.runtime.playbooks import CapabilityRequirement, PlaybookDefinition, PlaybookEdge, PlaybookNode
from src.core.runtime.tracing import trace_execution

from .phase43_support import compile_reference_plan, event, phase43_deployment, phase43_registry, reference_playbook


def test_reference_execution_succeeds_deterministically() -> None:
    executor = PlaybookExecutor(internal_handler_registry())

    outcome = executor.execute(plan=compile_reference_plan(), trigger_event=event({"text": "hello"}))

    assert outcome.execution.state == ExecutionState.SUCCEEDED.value
    assert outcome.context.correlation_id == "corr-1"
    assert outcome.context.trace_id == "trace-1"
    assert outcome.context.node_outputs["uppercase"] == {"text": "HELLO"}
    assert outcome.context.node_outputs["echo"] == {"value": "HELLO"}
    node_by_record_id = {
        record.node_execution_id: record.node_id
        for record in executor.ledger.list_node_executions(outcome.execution.execution_id)
    }
    running_order = [
        node_by_record_id[transition.record_id]
        for transition in executor.ledger.list_transitions()
        if transition.record_type == "node_execution" and transition.to_state == ExecutionState.RUNNING.value
    ]
    assert running_order == ["trigger", "uppercase", "is-hello", "echo"]
    assert [record.node_id for record in executor.ledger.list_node_executions(outcome.execution.execution_id)] == [
        "echo",
        "is-hello",
        "trigger",
        "uppercase",
    ]


def test_false_condition_skips_true_branch_and_still_succeeds() -> None:
    executor = PlaybookExecutor(internal_handler_registry())

    outcome = executor.execute(plan=compile_reference_plan(), trigger_event=event({"text": "bye"}))
    node_records = executor.ledger.list_node_executions(outcome.execution.execution_id)

    assert outcome.execution.state == ExecutionState.SUCCEEDED.value
    assert outcome.context.node_outputs["uppercase"] == {"text": "BYE"}
    assert "echo" not in outcome.context.node_outputs
    assert any(record.node_id == "echo" and record.state == ExecutionState.SKIPPED.value for record in node_records)


def test_failure_records_structured_error_and_terminal_state() -> None:
    plan = compile_reference_plan()
    executor = PlaybookExecutor(CapabilityHandlerRegistry())

    outcome = executor.execute(plan=plan, trigger_event=event())

    assert outcome.execution.state == ExecutionState.FAILED.value
    failed = [
        record
        for record in executor.ledger.list_node_executions(outcome.execution.execution_id)
        if record.node_id == "echo"
    ]
    assert failed[-1].state == ExecutionState.FAILED.value
    assert failed[-1].error_code == "HANDLER_NOT_FOUND"


def test_handler_registry_uses_component_and_capability_pair() -> None:
    registry = CapabilityHandlerRegistry()
    primary = registry.register(EchoHandler(component_id="test-echo-component"))
    alternate = registry.register(EchoHandler(component_id="test-echo-alt-component"))

    assert registry.resolve("test-echo-component", "test.echo") is primary
    assert registry.resolve("test-echo-alt-component", "test.echo") is alternate

    with pytest.raises(PlaybookExecutionError) as exc:
        registry.resolve("missing-component", "test.echo")
    assert exc.value.code == "HANDLER_NOT_FOUND"


def test_same_playbook_resolves_different_components_from_deployment_binding() -> None:
    playbook = reference_playbook()
    registry = phase43_registry()

    primary = compile_execution_plan(playbook, phase43_deployment("test-install"), registry)
    alternate = compile_execution_plan(playbook, phase43_deployment("test-install-alt"), registry)

    assert primary.to_json() != alternate.to_json()
    assert [node.component_id for node in primary.nodes if node.node_id == "echo"] == ["test-echo-component"]
    assert [node.component_id for node in alternate.nodes if node.node_id == "echo"] == ["test-echo-alt-component"]


def test_idempotent_start_returns_existing_execution_for_same_trigger() -> None:
    executor = PlaybookExecutor(internal_handler_registry())
    plan = compile_reference_plan()
    trigger = event({"text": "hello"}, idempotency_key="same-event")

    first = executor.start_execution_once(plan=plan, trigger_event=trigger)
    second = executor.start_execution_once(plan=plan, trigger_event=trigger)

    assert first.execution.execution_id == second.execution.execution_id
    assert len(executor.ledger.executions) == 1


def test_trace_execution_returns_structured_execution_and_node_records() -> None:
    executor = PlaybookExecutor(internal_handler_registry())
    outcome = executor.execute(plan=compile_reference_plan(), trigger_event=event())

    trace = trace_execution(executor.ledger, outcome.execution.execution_id).to_dict()

    assert trace["execution"]["execution_id"] == outcome.execution.execution_id
    assert {node["node_id"] for node in trace["nodes"]} == {"trigger", "uppercase", "is-hello", "echo"}
    assert any(transition["record_type"] == "execution" for transition in trace["transitions"])


def test_executor_does_not_call_legacy_or_external_side_effect_paths() -> None:
    executor = PlaybookExecutor(internal_handler_registry())

    with (
        patch.object(socket, "socket", side_effect=AssertionError("network is forbidden")) as socket_mock,
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess is forbidden")) as run_mock,
        patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess is forbidden")) as popen_mock,
        patch.object(
            LinkedInChannelRuntime, "publish", side_effect=AssertionError("legacy linkedin forbidden")
        ) as li_mock,
        patch.object(YouTubeChannelService, "publish_video", create=True) as yt_mock,
        patch.object(GitPublisher, "publish", side_effect=AssertionError("git publish forbidden")) as git_mock,
        patch.object(ExecutionCalendarService, "list_calendar_entries") as calendar_mock,
        patch.object(PluginRuntime, "service", side_effect=AssertionError("plugin runtime forbidden")) as plugin_mock,
    ):
        outcome = executor.execute(plan=compile_reference_plan(), trigger_event=event())

    assert outcome.execution.state == ExecutionState.SUCCEEDED.value
    for mocked in (socket_mock, run_mock, popen_mock, li_mock, yt_mock, git_mock, calendar_mock, plugin_mock):
        mocked.assert_not_called()


def test_execution_context_rejects_secret_values() -> None:
    with pytest.raises(PlaybookExecutionError):
        ExecutionContext(
            execution_id="exec_test",
            deployment_id="deployment-test",
            trigger_event=event(),
            metadata={"client_" + "secret": "value"},
        )


def test_dependency_waits_for_parent_output_and_invalid_input_fails() -> None:
    playbook = PlaybookDefinition(
        playbook_id="test.phase43.reference",
        version="1.0.0",
        schema_version="1.0",
        name="Invalid Input",
        requirements={"echoer": CapabilityRequirement(("test.echo",))},
        nodes=(
            PlaybookNode("trigger", "trigger"),
            PlaybookNode(
                "echo",
                "capability",
                {
                    "requirement": "echoer",
                    "capability": "test.echo",
                    "input": {"value": {"from_node": "missing", "path": "value"}},
                },
            ),
        ),
        edges=(PlaybookEdge("trigger", "echo"),),
    )
    plan = compile_execution_plan(playbook, phase43_deployment(), phase43_registry())
    executor = PlaybookExecutor(internal_handler_registry())

    outcome = executor.execute(plan=plan, trigger_event=event())

    assert outcome.execution.state == ExecutionState.FAILED.value
    failed = [
        node for node in executor.ledger.list_node_executions(outcome.execution.execution_id) if node.node_id == "echo"
    ]
    assert failed[-1].error_code == "INPUT_RESOLUTION_FAILED"


def test_non_node_result_is_reported_as_invalid() -> None:
    class BadHandler(EchoHandler):
        def execute(self, **kwargs):  # type: ignore[no-untyped-def]
            return {"not": "a node result"}

    registry = CapabilityHandlerRegistry()
    registry.register(BadHandler())
    executor = PlaybookExecutor(registry)

    outcome = executor.execute(plan=compile_reference_plan(), trigger_event=event())

    assert outcome.execution.state == ExecutionState.FAILED.value
    failed = [
        node for node in executor.ledger.list_node_executions(outcome.execution.execution_id) if node.node_id == "echo"
    ]
    assert failed[-1].error_code == "INVALID_NODE_RESULT"
