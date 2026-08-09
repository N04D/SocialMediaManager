from __future__ import annotations

from .errors import PlaybookExecutionError
from .execution_context import ExecutionContext
from .input_resolution import resolve_node_input
from .playbooks import PlaybookNode
from .results import NodeResult


def execute_transform(node: PlaybookNode, context: ExecutionContext) -> NodeResult:
    transformer = str(node.config.get("transformer") or "identity")
    input_data = resolve_node_input(node.config, context)
    if transformer == "identity":
        return NodeResult.success(input_data)
    if transformer == "uppercase":
        field = str(node.config.get("field") or "text")
        text = str(input_data.get(field, ""))
        return NodeResult.success({field: text.upper()})
    if transformer == "field_map":
        return NodeResult.success(input_data)
    raise PlaybookExecutionError(
        "CAPABILITY_EXECUTION_FAILED",
        "Transform is not supported.",
        {"transformer": transformer, "node_id": node.node_id},
    )
