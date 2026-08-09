from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .identifiers import validate_namespaced_id


class CapabilityMode(StrEnum):
    READ = "read"
    WRITE = "write"
    EVENT = "event"


@dataclass(frozen=True, order=True)
class CapabilityDescriptor:
    capability_id: str
    version: str
    mode: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    policy: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_namespaced_id(self.capability_id, field_name="capability_id")
        CapabilityMode(self.mode)
        if not str(self.version or "").strip():
            raise ValueError("CapabilityDescriptor version is required.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "description": self.description,
            "input_schema": json.loads(json.dumps(self.input_schema, sort_keys=True, ensure_ascii=True)),
            "mode": self.mode,
            "output_schema": json.loads(json.dumps(self.output_schema, sort_keys=True, ensure_ascii=True)),
            "policy": json.loads(json.dumps(self.policy, sort_keys=True, ensure_ascii=True)),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CapabilityDescriptor:
        return cls(
            capability_id=str(payload.get("capability_id") or ""),
            version=str(payload.get("version") or ""),
            mode=str(payload.get("mode") or ""),
            input_schema=dict(payload.get("input_schema") or {}),
            output_schema=dict(payload.get("output_schema") or {}),
            description=str(payload.get("description") or ""),
            policy=dict(payload.get("policy") or {}),
        )
