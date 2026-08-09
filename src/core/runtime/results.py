from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .execution_context import _assert_no_secret_values


class NodeResultStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    WAIT = "wait"
    SKIP = "skip"


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))


@dataclass(frozen=True)
class NodeResult:
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", NodeResultStatus(self.status).value)
        _assert_no_secret_values(self.output, code="node_result.secret_value")
        _assert_no_secret_values(self.metadata, code="node_result.secret_value")
        object.__setattr__(self, "output", _json_safe(self.output))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    @classmethod
    def success(cls, output: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> NodeResult:
        return cls(NodeResultStatus.SUCCESS.value, output or {}, metadata or {})

    @classmethod
    def failure(cls, error_code: str, error_message: str, metadata: dict[str, Any] | None = None) -> NodeResult:
        return cls(NodeResultStatus.FAILURE.value, {}, metadata or {}, error_code, error_message)

    @classmethod
    def wait(cls, output: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> NodeResult:
        return cls(NodeResultStatus.WAIT.value, output or {}, metadata or {})

    @classmethod
    def skip(cls, output: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> NodeResult:
        return cls(NodeResultStatus.SKIP.value, output or {}, metadata or {})
