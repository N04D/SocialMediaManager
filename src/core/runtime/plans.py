from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .deployments import PlaybookDeployment, validate_deployment
from .playbooks import PlaybookDefinition, PlaybookNodeKind, validate_playbook
from .resolver import CapabilityResolver, RuntimeRegistry


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))


@dataclass(frozen=True)
class ExecutionPlanNode:
    node_id: str
    kind: str
    requirement: str = ""
    capability: str = ""
    install_id: str = ""
    component_id: str = ""
    provider: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "component_id": self.component_id,
            "config": _json_safe(self.config),
            "install_id": self.install_id,
            "kind": self.kind,
            "node_id": self.node_id,
            "provider": self.provider,
            "requirement": self.requirement,
        }


@dataclass(frozen=True)
class ExecutionPlan:
    playbook_id: str
    playbook_version: str
    deployment_id: str
    workspace_id: str
    nodes: tuple[ExecutionPlanNode, ...]
    edges: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "edges": list(self.edges),
            "nodes": [node.to_dict() for node in self.nodes],
            "playbook_id": self.playbook_id,
            "playbook_version": self.playbook_version,
            "workspace_id": self.workspace_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compile_execution_plan(
    playbook: PlaybookDefinition, deployment: PlaybookDeployment, registry: RuntimeRegistry
) -> ExecutionPlan:
    validate_playbook(playbook)
    validate_deployment(playbook, deployment, registry)
    resolver = CapabilityResolver(registry)
    plan_nodes: list[ExecutionPlanNode] = []
    for node in playbook.nodes:
        requirement = ""
        capability = ""
        install_id = ""
        component_id = ""
        provider = ""
        if node.kind == PlaybookNodeKind.CAPABILITY.value:
            requirement = str(node.config.get("requirement") or "")
            capability = str(node.config.get("capability") or "")
            binding = deployment.binding_for(requirement)
            if binding is not None:
                resolution = resolver.resolve(install_id=binding.install_id, capability=capability)
                install_id = resolution.install.install_id
                component_id = resolution.component.component_id
                provider = resolution.component.provider
        plan_nodes.append(
            ExecutionPlanNode(
                node_id=node.node_id,
                kind=node.kind,
                requirement=requirement,
                capability=capability,
                install_id=install_id,
                component_id=component_id,
                provider=provider,
                config=node.config,
            )
        )
    return ExecutionPlan(
        playbook_id=playbook.playbook_id,
        playbook_version=playbook.version,
        deployment_id=deployment.deployment_id,
        workspace_id=deployment.workspace_id,
        nodes=tuple(plan_nodes),
        edges=tuple(edge.to_dict() for edge in playbook.edges),
    )
