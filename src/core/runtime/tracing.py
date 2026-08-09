from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ledger import ExecutionLedger, ExecutionRecord, NodeExecutionRecord


@dataclass(frozen=True)
class ExecutionTrace:
    execution: ExecutionRecord
    nodes: tuple[NodeExecutionRecord, ...]
    transitions: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution": self.execution.to_dict(),
            "nodes": [node.to_dict() for node in self.nodes],
            "transitions": [transition for transition in self.transitions],
        }


def trace_execution(ledger: ExecutionLedger, execution_id: str) -> ExecutionTrace:
    execution = ledger.get_execution(execution_id)
    if execution is None:
        raise ValueError(f"Execution not found: {execution_id}")
    transitions = []
    list_transitions = getattr(ledger, "list_transitions", None)
    if callable(list_transitions):
        transitions = [item.to_dict() for item in list_transitions()]
    return ExecutionTrace(
        execution=execution,
        nodes=tuple(ledger.list_node_executions(execution_id)),
        transitions=tuple(transitions),
    )
