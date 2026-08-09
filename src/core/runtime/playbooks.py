from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .errors import PlaybookValidationError
from .identifiers import validate_namespaced_id, validate_runtime_id

PLAYBOOK_SCHEMA_VERSION = "1.0"
SUPPORTED_PLAYBOOK_SCHEMA_VERSIONS = {PLAYBOOK_SCHEMA_VERSION}
KNOWN_NODE_KINDS = {"trigger", "capability", "transform", "condition", "approval", "delay", "join"}
SECRET_OR_ENVIRONMENT_KEYS = {
    "account_id",
    "api_key",
    "client_secret",
    "credential",
    "credentials",
    "install",
    "install_id",
    "password",
    "refresh_token",
    "secret",
    "secret_ref",
    "secret_refs",
    "token",
    "workspace_id",
}


class PlaybookNodeKind(StrEnum):
    TRIGGER = "trigger"
    CAPABILITY = "capability"
    TRANSFORM = "transform"
    CONDITION = "condition"
    APPROVAL = "approval"
    DELAY = "delay"
    JOIN = "join"


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in SECRET_OR_ENVIRONMENT_KEYS:
                return True
            if _contains_forbidden_key(child):
                return True
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _validate_node_kind(kind: str) -> str:
    normalized = str(kind or "").strip()
    if normalized in KNOWN_NODE_KINDS:
        return normalized
    if "." in normalized:
        return validate_namespaced_id(normalized, field_name="node.kind")
    raise PlaybookValidationError(
        "playbook.node_kind_unknown",
        "Playbook node kind is not supported by this schema.",
        {"kind": kind},
    )


@dataclass(frozen=True)
class CapabilityRequirement:
    capabilities: tuple[str, ...]
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = tuple(
            validate_namespaced_id(item, field_name="requirement.capability") for item in self.capabilities
        )
        if not normalized:
            raise PlaybookValidationError(
                "playbook.requirement_empty",
                "Capability requirement must declare at least one capability.",
            )
        if _contains_forbidden_key(self.metadata):
            raise PlaybookValidationError(
                "playbook.requirement_not_portable",
                "Playbook requirements must not contain environment-specific or secret fields.",
            )
        object.__setattr__(self, "capabilities", normalized)
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilities": list(self.capabilities),
            "description": self.description,
            "metadata": _json_safe(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CapabilityRequirement:
        return cls(
            capabilities=tuple(str(item) for item in payload.get("capabilities", [])),
            description=str(payload.get("description") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class PlaybookNode:
    node_id: str
    kind: str
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", validate_runtime_id(self.node_id, field_name="node_id"))
        object.__setattr__(self, "kind", _validate_node_kind(self.kind))
        if _contains_forbidden_key(self.config):
            raise PlaybookValidationError(
                "playbook.node_not_portable",
                "Playbook nodes must not contain environment-specific or secret fields.",
                {"node_id": self.node_id},
            )
        object.__setattr__(self, "config", _json_safe(self.config))

    def to_dict(self) -> dict[str, Any]:
        return {"config": _json_safe(self.config), "kind": self.kind, "node_id": self.node_id}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlaybookNode:
        return cls(
            node_id=str(payload.get("node_id") or payload.get("id") or ""),
            kind=str(payload.get("kind") or ""),
            config=dict(payload.get("config") or {}),
        )


@dataclass(frozen=True)
class PlaybookEdge:
    source: str
    target: str
    source_port: str = ""
    target_port: str = ""
    condition: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", validate_runtime_id(self.source, field_name="edge.source"))
        object.__setattr__(self, "target", validate_runtime_id(self.target, field_name="edge.target"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "source": self.source,
            "source_port": self.source_port,
            "target": self.target,
            "target_port": self.target_port,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlaybookEdge:
        return cls(
            source=str(payload.get("source") or ""),
            target=str(payload.get("target") or ""),
            source_port=str(payload.get("source_port") or ""),
            target_port=str(payload.get("target_port") or ""),
            condition=str(payload.get("condition") or ""),
        )


@dataclass(frozen=True)
class PlaybookDefinition:
    playbook_id: str
    version: str
    schema_version: str
    name: str
    description: str = ""
    requirements: dict[str, CapabilityRequirement] = field(default_factory=dict)
    nodes: tuple[PlaybookNode, ...] = field(default_factory=tuple)
    edges: tuple[PlaybookEdge, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "playbook_id", validate_namespaced_id(self.playbook_id, field_name="playbook_id"))
        if not self.version.strip():
            raise PlaybookValidationError("playbook.version_required", "Playbook version is required.")
        if self.schema_version not in SUPPORTED_PLAYBOOK_SCHEMA_VERSIONS:
            raise PlaybookValidationError(
                "playbook.schema_version_unsupported",
                "Playbook schema version is not supported.",
                {"schema_version": self.schema_version},
            )
        normalized_requirements: dict[str, CapabilityRequirement] = {}
        for slot, requirement in self.requirements.items():
            normalized_slot = validate_runtime_id(slot, field_name="requirement.slot")
            normalized_requirements[normalized_slot] = (
                requirement
                if isinstance(requirement, CapabilityRequirement)
                else CapabilityRequirement.from_dict(dict(requirement))
            )
        if _contains_forbidden_key(self.metadata):
            raise PlaybookValidationError(
                "playbook.metadata_not_portable",
                "Playbook metadata must not contain environment-specific or secret fields.",
            )
        object.__setattr__(self, "requirements", normalized_requirements)
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "edges": [edge.to_dict() for edge in self.edges],
            "metadata": _json_safe(self.metadata),
            "name": self.name,
            "nodes": [node.to_dict() for node in self.nodes],
            "playbook_id": self.playbook_id,
            "requirements": {slot: requirement.to_dict() for slot, requirement in sorted(self.requirements.items())},
            "schema_version": self.schema_version,
            "version": self.version,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlaybookDefinition:
        return cls(
            playbook_id=str(payload.get("playbook_id") or ""),
            version=str(payload.get("version") or ""),
            schema_version=str(payload.get("schema_version") or PLAYBOOK_SCHEMA_VERSION),
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            requirements={
                str(slot): CapabilityRequirement.from_dict(dict(requirement))
                for slot, requirement in dict(payload.get("requirements") or {}).items()
                if isinstance(requirement, dict)
            },
            nodes=tuple(PlaybookNode.from_dict(item) for item in payload.get("nodes", []) if isinstance(item, dict)),
            edges=tuple(PlaybookEdge.from_dict(item) for item in payload.get("edges", []) if isinstance(item, dict)),
            metadata=dict(payload.get("metadata") or {}),
        )

    @classmethod
    def from_json(cls, payload: str) -> PlaybookDefinition:
        return cls.from_dict(json.loads(payload))


def validate_playbook(playbook: PlaybookDefinition) -> None:
    node_ids: set[str] = set()
    for node in playbook.nodes:
        if node.node_id in node_ids:
            raise PlaybookValidationError(
                "playbook.duplicate_node",
                "Playbook node IDs must be unique.",
                {"node_id": node.node_id},
            )
        node_ids.add(node.node_id)
    if not any(node.kind == PlaybookNodeKind.TRIGGER.value for node in playbook.nodes):
        raise PlaybookValidationError("playbook.trigger_missing", "Playbook requires at least one trigger node.")
    for edge in playbook.edges:
        if edge.source not in node_ids or edge.target not in node_ids:
            raise PlaybookValidationError(
                "playbook.edge_node_missing",
                "Playbook edge references a missing node.",
                edge.to_dict(),
            )
        if edge.source == edge.target:
            raise PlaybookValidationError(
                "playbook.self_edge",
                "Playbook edge cannot point to the same node.",
                edge.to_dict(),
            )
    for node in playbook.nodes:
        if node.kind != PlaybookNodeKind.CAPABILITY.value:
            continue
        requirement_slot = str(node.config.get("requirement") or "")
        capability = str(node.config.get("capability") or "")
        if requirement_slot not in playbook.requirements:
            raise PlaybookValidationError(
                "playbook.requirement_unknown",
                "Capability node references an unknown requirement.",
                {"node_id": node.node_id, "requirement": requirement_slot},
            )
        validate_namespaced_id(capability, field_name="node.capability")
        if capability not in playbook.requirements[requirement_slot].capabilities:
            raise PlaybookValidationError(
                "playbook.capability_not_declared",
                "Capability node requests a capability not declared by its requirement.",
                {"node_id": node.node_id, "requirement": requirement_slot, "capability": capability},
            )
    _assert_acyclic(playbook.nodes, playbook.edges)


def _assert_acyclic(nodes: tuple[PlaybookNode, ...], edges: tuple[PlaybookEdge, ...]) -> None:
    graph: dict[str, list[str]] = {node.node_id: [] for node in nodes}
    for edge in edges:
        graph.setdefault(edge.source, []).append(edge.target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        for child in graph.get(node_id, []):
            if walk(child):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    for node in graph:
        if walk(node):
            raise PlaybookValidationError("playbook.cycle", "Playbook graph must be a DAG.")
