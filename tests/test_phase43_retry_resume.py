from __future__ import annotations

import pytest

from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.executor import PlaybookExecutor
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.internal_handlers import EchoHandler, FlakyHandler, WaitOnceHandler
from src.core.runtime.ledger import ExecutionState
from src.core.runtime.plans import compile_execution_plan
from src.core.runtime.playbooks import CapabilityRequirement, PlaybookDefinition, PlaybookEdge, PlaybookNode

from .phase43_support import event, phase43_deployment, phase43_registry


def capability_playbook(
    capability: str, requirement: str, *, retry: dict[str, int] | None = None
) -> PlaybookDefinition:
    config = {
        "requirement": requirement,
        "capability": capability,
        "input": {"value": {"literal": 1}},
    }
    if retry:
        config["retry"] = retry
    return PlaybookDefinition(
        playbook_id="test.phase43.reference",
        version="1.0.0",
        schema_version="1.0",
        name="Single Capability",
        requirements={requirement: CapabilityRequirement((capability,))},
        nodes=(
            PlaybookNode("trigger", "trigger"),
            PlaybookNode("capability-node", "capability", config),
        ),
        edges=(PlaybookEdge("trigger", "capability-node"),),
    )


def compile_capability_plan(capability: str, requirement: str, *, retry: dict[str, int] | None = None):
    return compile_execution_plan(
        capability_playbook(capability, requirement, retry=retry),
        phase43_deployment(),
        phase43_registry(),
    )


def test_retry_success_first_attempt_records_single_attempt() -> None:
    registry = CapabilityHandlerRegistry()
    registry.register(EchoHandler())
    executor = PlaybookExecutor(registry)

    outcome = executor.execute(plan=compile_capability_plan("test.echo", "echoer"), trigger_event=event())
    attempts = [
        item
        for item in executor.ledger.list_node_executions(outcome.execution.execution_id)
        if item.node_id == "capability-node"
    ]

    assert outcome.execution.state == ExecutionState.SUCCEEDED.value
    assert [item.attempt for item in attempts] == [1]


def test_retry_failure_then_success_records_attempt_history() -> None:
    registry = CapabilityHandlerRegistry()
    flaky = registry.register(FlakyHandler(failures_before_success=1))
    executor = PlaybookExecutor(registry)

    outcome = executor.execute(
        plan=compile_capability_plan("test.flaky", "flaky", retry={"max_attempts": 3}),
        trigger_event=event(),
    )
    attempts = [
        item
        for item in executor.ledger.list_node_executions(outcome.execution.execution_id)
        if item.node_id == "capability-node"
    ]

    assert outcome.execution.state == ExecutionState.SUCCEEDED.value
    assert flaky.calls == 2
    assert [item.state for item in attempts] == [ExecutionState.FAILED.value, ExecutionState.SUCCEEDED.value]
    assert [item.attempt for item in attempts] == [1, 2]


def test_retry_exhausted_fails_execution() -> None:
    registry = CapabilityHandlerRegistry()
    flaky = registry.register(FlakyHandler(failures_before_success=5))
    executor = PlaybookExecutor(registry)

    outcome = executor.execute(
        plan=compile_capability_plan("test.flaky", "flaky", retry={"max_attempts": 2}),
        trigger_event=event(),
    )
    attempts = [
        item
        for item in executor.ledger.list_node_executions(outcome.execution.execution_id)
        if item.node_id == "capability-node"
    ]

    assert outcome.execution.state == ExecutionState.FAILED.value
    assert flaky.calls == 2
    assert [item.attempt for item in attempts] == [1, 2]


def test_wait_then_resume_succeeds() -> None:
    wait_handler = WaitOnceHandler()
    registry = CapabilityHandlerRegistry()
    registry.register(wait_handler)
    executor = PlaybookExecutor(registry)

    waiting = executor.execute(plan=compile_capability_plan("test.wait", "waiter"), trigger_event=event())

    assert waiting.execution.state == ExecutionState.WAITING.value
    assert "capability-node" not in waiting.context.node_outputs

    wait_handler.released = True
    resumed = executor.resume_execution(waiting.execution.execution_id)

    assert resumed.execution.state == ExecutionState.SUCCEEDED.value
    assert resumed.context.node_outputs["capability-node"] == {"resumed": True}
    attempts = [
        item
        for item in executor.ledger.list_node_executions(resumed.execution.execution_id)
        if item.node_id == "capability-node"
    ]
    assert [item.state for item in attempts] == [ExecutionState.WAITING.value, ExecutionState.SUCCEEDED.value]
    assert [item.attempt for item in attempts] == [1, 2]


def test_terminal_execution_cannot_resume() -> None:
    registry = CapabilityHandlerRegistry()
    registry.register(EchoHandler())
    executor = PlaybookExecutor(registry)
    outcome = executor.execute(plan=compile_capability_plan("test.echo", "echoer"), trigger_event=event())

    with pytest.raises(PlaybookExecutionError) as exc:
        executor.resume_execution(outcome.execution.execution_id)

    assert exc.value.code == "EXECUTION_ALREADY_TERMINAL"
