from __future__ import annotations

from typing import Any

from .errors import PlaybookExecutionError
from .execution_context import ExecutionContext, _assert_no_secret_values


def resolve_input_mapping(mapping: Any, context: ExecutionContext) -> Any:
    if isinstance(mapping, dict):
        if "literal" in mapping:
            value = mapping["literal"]
            _assert_no_secret_values({"literal": value})
            return value
        if "from_event" in mapping:
            source = str(mapping.get("from_event") or "payload")
            if source != "payload":
                raise PlaybookExecutionError(
                    "INPUT_RESOLUTION_FAILED",
                    "Only trigger event payload input mappings are supported.",
                    {"source": source},
                )
            return _path_get(context.trigger_event.payload, str(mapping.get("path") or ""))
        if "from_node" in mapping:
            node_id = str(mapping.get("from_node") or "")
            if node_id not in context.node_outputs:
                raise PlaybookExecutionError(
                    "INPUT_RESOLUTION_FAILED",
                    "Input mapping references a node without output.",
                    {"node_id": node_id},
                )
            return _path_get(context.node_outputs[node_id], str(mapping.get("path") or ""))
        return {str(key): resolve_input_mapping(value, context) for key, value in mapping.items()}
    if isinstance(mapping, list):
        return [resolve_input_mapping(item, context) for item in mapping]
    _assert_no_secret_values({"literal": mapping})
    return mapping


def resolve_node_input(config: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    raw = config.get("input", {})
    if not isinstance(raw, dict):
        raise PlaybookExecutionError("INPUT_RESOLUTION_FAILED", "Node input mapping must be an object.")
    resolved = {str(key): resolve_input_mapping(value, context) for key, value in raw.items()}
    _assert_no_secret_values(resolved)
    return resolved


def _path_get(payload: Any, path: str) -> Any:
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
            continue
        raise PlaybookExecutionError(
            "INPUT_RESOLUTION_FAILED",
            "Input path could not be resolved.",
            {"path": path, "missing": part},
        )
    return current
