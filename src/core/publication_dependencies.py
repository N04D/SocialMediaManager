"""Publication target dependency graph for website-first funnels."""

from __future__ import annotations

from dataclasses import dataclass


class PublicationDependencyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PublicationTargetDependency:
    id: str
    plan_id: str
    predecessor_target_id: str
    dependent_target_id: str
    required_state: str
    dependency_type: str = "publication_state"
    timeout_policy: str = "block"
    failure_policy: str = "block"
    workspace_id: str = ""
    created_at: str = ""


class PublicationDependencyGraph:
    def __init__(self) -> None:
        self._dependencies: dict[str, PublicationTargetDependency] = {}

    def add(self, dependency: PublicationTargetDependency) -> None:
        if dependency.predecessor_target_id == dependency.dependent_target_id:
            raise PublicationDependencyError("publication_dependency.self", "Self-dependencies are rejected.")
        if dependency.dependency_type != "publication_state":
            raise PublicationDependencyError("publication_dependency.type", "Unsupported dependency type.")
        self._dependencies[dependency.id] = dependency
        if self.has_cycle():
            self._dependencies.pop(dependency.id, None)
            raise PublicationDependencyError("publication_dependency.cycle", "Dependency graph must be acyclic.")

    def remove(self, dependency_id: str) -> None:
        self._dependencies.pop(dependency_id, None)

    def list(self) -> tuple[PublicationTargetDependency, ...]:
        return tuple(self._dependencies.values())

    def claimable(self, target_id: str, states: dict[str, str]) -> bool:
        for dependency in self._dependencies.values():
            if dependency.dependent_target_id != target_id:
                continue
            predecessor_state = states.get(dependency.predecessor_target_id, "not_started")
            if predecessor_state in {"failed", "cancelled"}:
                return False
            if predecessor_state in {"mutation_uncertain", "uncertain"}:
                return False
            if predecessor_state != dependency.required_state:
                return False
        return True

    def has_cycle(self) -> bool:
        edges: dict[str, list[str]] = {}
        for dependency in self._dependencies.values():
            edges.setdefault(dependency.predecessor_target_id, []).append(dependency.dependent_target_id)
        visiting: set[str] = set()
        visited: set[str] = set()

        def walk(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for child in edges.get(node, []):
                if walk(child):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(walk(node) for node in edges)
