from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any

from .errors import PlaybookExecutionError
from .events import EventEnvelope
from .installs import SECRET_VALUE_FRAGMENTS


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))


def _assert_no_secret_values(value: Any, *, code: str = "execution_context.secret_value") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SECRET_VALUE_FRAGMENTS) and not lowered.endswith("_ref"):
                raise PlaybookExecutionError(
                    code,
                    "Execution context must not contain secret-shaped values.",
                    {"field": str(key)},
                )
            _assert_no_secret_values(child, code=code)
    elif isinstance(value, list):
        for item in value:
            _assert_no_secret_values(item, code=code)


@dataclass(frozen=True)
class ExecutionContext:
    execution_id: str
    deployment_id: str
    trigger_event: EventEnvelope
    correlation_id: str = ""
    trace_id: str = ""
    variables: dict[str, Any] = field(default_factory=dict)
    node_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _assert_no_secret_values(self.variables)
        _assert_no_secret_values(self.node_outputs)
        _assert_no_secret_values(self.metadata)
        object.__setattr__(self, "variables", _json_safe(self.variables))
        object.__setattr__(self, "node_outputs", _json_safe(self.node_outputs))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))
        object.__setattr__(self, "correlation_id", self.correlation_id or self.trigger_event.correlation_id)
        object.__setattr__(self, "trace_id", self.trace_id or self.trigger_event.trace_id)

    def with_node_output(self, node_id: str, output: dict[str, Any]) -> ExecutionContext:
        _assert_no_secret_values(output, code="node_result.secret_value")
        outputs = dict(self.node_outputs)
        outputs[node_id] = _json_safe(output)
        return replace(self, node_outputs=outputs)
