from __future__ import annotations

import pytest

from src.core.runtime.conditions import evaluate_condition
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.execution_context import ExecutionContext
from src.core.runtime.input_resolution import resolve_node_input

from .phase43_support import event


def context_with_outputs() -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec_test",
        deployment_id="deployment-test",
        trigger_event=event({"text": "hello", "score": 81, "tags": ["lead", "demo"]}),
        node_outputs={"score": {"value": 81}, "text": {"value": "HELLO"}},
    )


def test_input_resolution_supports_literals_event_payload_and_node_output() -> None:
    resolved = resolve_node_input(
        {
            "input": {
                "literal_value": {"literal": "fixed"},
                "event_text": {"from_event": "payload", "path": "text"},
                "node_score": {"from_node": "score", "path": "value"},
            }
        },
        context_with_outputs(),
    )

    assert resolved == {"event_text": "hello", "literal_value": "fixed", "node_score": 81}


def test_input_resolution_rejects_missing_path_and_invalid_input_mapping() -> None:
    with pytest.raises(PlaybookExecutionError) as missing:
        resolve_node_input({"input": {"value": {"from_event": "payload", "path": "missing"}}}, context_with_outputs())
    assert missing.value.code == "INPUT_RESOLUTION_FAILED"

    with pytest.raises(PlaybookExecutionError) as invalid:
        resolve_node_input({"input": []}, context_with_outputs())
    assert invalid.value.code == "INPUT_RESOLUTION_FAILED"


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"left": {"from_node": "text", "path": "value"}, "operator": "equals", "right": {"literal": "HELLO"}}, True),
        (
            {"left": {"from_node": "text", "path": "value"}, "operator": "not_equals", "right": {"literal": "hello"}},
            True,
        ),
        ({"left": {"from_node": "score", "path": "value"}, "operator": "exists"}, True),
        ({"left": {"from_node": "score", "path": "value"}, "operator": "gt", "right": {"literal": 80}}, True),
        ({"left": {"from_node": "score", "path": "value"}, "operator": "gte", "right": {"literal": 81}}, True),
        ({"left": {"from_node": "score", "path": "value"}, "operator": "lt", "right": {"literal": 90}}, True),
        ({"left": {"from_node": "score", "path": "value"}, "operator": "lte", "right": {"literal": 81}}, True),
        (
            {"left": {"from_event": "payload", "path": "tags"}, "operator": "contains", "right": {"literal": "lead"}},
            True,
        ),
    ],
)
def test_condition_operators_are_deterministic(config: dict[str, object], expected: bool) -> None:
    assert evaluate_condition(config, context_with_outputs()) is expected


def test_condition_rejects_unsupported_operator_without_eval() -> None:
    with pytest.raises(PlaybookExecutionError) as exc:
        evaluate_condition(
            {"left": {"literal": 1}, "operator": "__import__", "right": {"literal": 1}}, context_with_outputs()
        )

    assert exc.value.code == "CONDITION_EVALUATION_FAILED"


def test_context_and_node_results_reject_obvious_secret_shaped_values() -> None:
    with pytest.raises(PlaybookExecutionError):
        ExecutionContext(
            execution_id="exec_test",
            deployment_id="deployment-test",
            trigger_event=event(),
            variables={"access_" + "token": "value"},
        )

    with pytest.raises(PlaybookExecutionError):
        resolve_node_input({"input": {"value": {"literal": {"api_" + "key": "value"}}}}, context_with_outputs())
