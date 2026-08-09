from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .errors import PlaybookExecutionError
from .execution_context import ExecutionContext
from .plans import ExecutionPlanNode
from .playbooks import PlaybookNode
from .results import NodeResult


class CapabilityHandler(Protocol):
    capability_id: str
    component_id: str

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> NodeResult: ...


@dataclass
class CapabilityHandlerRegistry:
    _handlers: dict[tuple[str, str], CapabilityHandler] = field(default_factory=dict)

    def register(self, handler: CapabilityHandler) -> CapabilityHandler:
        key = (handler.component_id, handler.capability_id)
        if key in self._handlers:
            raise PlaybookExecutionError(
                "HANDLER_ALREADY_REGISTERED",
                "Capability handler is already registered.",
                {"component_id": handler.component_id, "capability_id": handler.capability_id},
            )
        self._handlers[key] = handler
        return handler

    def resolve(self, component_id: str, capability_id: str) -> CapabilityHandler:
        handler = self._handlers.get((component_id, capability_id))
        if handler is None:
            raise PlaybookExecutionError(
                "HANDLER_NOT_FOUND",
                "No handler is registered for the resolved component and capability.",
                {"component_id": component_id, "capability_id": capability_id},
            )
        return handler
