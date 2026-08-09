from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .execution_context import ExecutionContext
from .handlers import CapabilityHandlerRegistry
from .plans import ExecutionPlanNode
from .playbooks import PlaybookNode
from .results import NodeResult


@dataclass
class EchoHandler:
    component_id: str = "test-echo-component"
    capability_id: str = "test.echo"

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> NodeResult:
        return NodeResult.success(dict(input_data))


@dataclass
class UppercaseHandler:
    component_id: str = "test-text-component"
    capability_id: str = "test.text.uppercase"

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> NodeResult:
        text = str(input_data.get("text", ""))
        return NodeResult.success({"text": text.upper()})


@dataclass
class CounterIncrementHandler:
    component_id: str = "test-counter-component"
    capability_id: str = "test.counter.increment"

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> NodeResult:
        current = int(input_data.get("value", context.variables.get("counter", 0) or 0))
        return NodeResult.success({"value": current + 1})


@dataclass
class WaitOnceHandler:
    component_id: str = "test-wait-component"
    capability_id: str = "test.wait"
    released: bool = False

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> NodeResult:
        if not self.released:
            return NodeResult.wait({"waiting": True})
        return NodeResult.success({"resumed": True})


@dataclass
class FlakyHandler:
    component_id: str = "test-flaky-component"
    capability_id: str = "test.flaky"
    failures_before_success: int = 1
    calls: int = 0

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> NodeResult:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            return NodeResult.failure("test.flaky", "Flaky handler failed.")
        return NodeResult.success({"attempts": self.calls})


def internal_handler_registry() -> CapabilityHandlerRegistry:
    registry = CapabilityHandlerRegistry()
    registry.register(EchoHandler())
    registry.register(UppercaseHandler())
    registry.register(CounterIncrementHandler())
    registry.register(WaitOnceHandler())
    registry.register(FlakyHandler())
    return registry
