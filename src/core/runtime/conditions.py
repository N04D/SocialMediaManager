from __future__ import annotations

from typing import Any

from .errors import PlaybookExecutionError
from .execution_context import ExecutionContext
from .input_resolution import resolve_input_mapping


def evaluate_condition(config: dict[str, Any], context: ExecutionContext) -> bool:
    try:
        left = resolve_input_mapping(config.get("left", {}), context)
        operator = str(config.get("operator") or "")
        right = resolve_input_mapping(config.get("right", {}), context) if "right" in config else None
        if operator == "equals":
            return left == right
        if operator == "not_equals":
            return left != right
        if operator == "exists":
            return left is not None
        if operator == "contains":
            return right in left
        if operator in {"gt", "gte", "lt", "lte"}:
            return _compare(left, right, operator)
    except PlaybookExecutionError:
        raise
    except Exception as exc:
        raise PlaybookExecutionError(
            "CONDITION_EVALUATION_FAILED",
            "Condition evaluation failed.",
            {"error": type(exc).__name__},
        ) from exc
    raise PlaybookExecutionError(
        "CONDITION_EVALUATION_FAILED",
        "Condition operator is not supported.",
        {"operator": operator},
    )


def _compare(left: Any, right: Any, operator: str) -> bool:
    if operator == "gt":
        return left > right
    if operator == "gte":
        return left >= right
    if operator == "lt":
        return left < right
    return left <= right
