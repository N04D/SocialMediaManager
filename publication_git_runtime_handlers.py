from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from channels.markdown_website.errors import MarkdownWebsiteError
from channels.markdown_website.git_publisher import GitPublisher
from channels.markdown_website.models import WebsiteRepositoryReference
from channels.markdown_website.paths import validate_repository_reference
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.execution_context import ExecutionContext, _assert_no_secret_values
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.plans import ExecutionPlanNode
from src.core.runtime.playbooks import PlaybookNode
from src.core.runtime.results import NodeResult

GIT_WEBSITE_COMPONENT_ID = "github-markdown-website"
GIT_REPOSITORY_STATUS_READ_CAPABILITY = "git.repository.status.read"

GIT_REPOSITORY_STATUS_READ_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "include_changed_paths": {"type": "boolean", "default": True},
    },
}

GIT_REPOSITORY_STATUS_READ_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["repository", "state", "branch", "head", "clean", "source"],
    "properties": {
        "repository": {"type": "string"},
        "state": {"type": "string"},
        "branch": {"type": "string"},
        "head": {"type": "string"},
        "clean": {"type": "boolean"},
        "changed_paths": {"type": "array", "items": {"type": "string"}},
        "source": {"type": "string"},
    },
}

RepositoryResolver = Callable[[str], WebsiteRepositoryReference | None]


@dataclass
class GitRepositoryStatusReadHandler:
    repository_resolver: RepositoryResolver
    git_publisher: GitPublisher
    component_id: str = GIT_WEBSITE_COMPONENT_ID
    capability_id: str = GIT_REPOSITORY_STATUS_READ_CAPABILITY

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> NodeResult:
        del context, node
        try:
            _assert_no_secret_values(input_data, code="git.input_secret_value")
            include_changed_paths = _validate_input(input_data)
            repository = self._repository_for_install(resolved_node.install_id)
            validate_repository_reference(repository)
            head = self.git_publisher.head_state(repository.managed_checkout_root)
            status_output = self.git_publisher.git(repository.managed_checkout_root, "status", "--porcelain")
            changed_paths = _parse_status_paths(status_output or "")
            output = {
                "repository": repository.id,
                "state": head.state,
                "branch": head.branch,
                "head": head.commit_sha,
                "clean": not changed_paths,
                "changed_paths": changed_paths if include_changed_paths else [],
                "source": GIT_WEBSITE_COMPONENT_ID,
            }
        except PlaybookExecutionError as exc:
            return NodeResult.failure(exc.code, exc.user_message, exc.details)
        except MarkdownWebsiteError as exc:
            return NodeResult.failure(
                "CAPABILITY_EXECUTION_FAILED",
                "Git repository status read failed.",
                {"error_code": exc.code},
            )
        except Exception as exc:
            return NodeResult.failure(
                "CAPABILITY_EXECUTION_FAILED",
                "Git repository status read failed.",
                {"error": type(exc).__name__},
            )
        return NodeResult.success(output)

    def _repository_for_install(self, install_id: str) -> WebsiteRepositoryReference:
        repository = self.repository_resolver(install_id)
        if repository is None:
            raise PlaybookExecutionError(
                "GIT_REPOSITORY_MISSING",
                "No repository reference is configured for this install.",
                {"install_id": install_id},
            )
        return repository


def register_git_runtime_handlers(
    handler_registry: CapabilityHandlerRegistry,
    *,
    repositories_by_install_id: dict[str, WebsiteRepositoryReference] | None = None,
    repository_resolver: RepositoryResolver | None = None,
    git_publisher: GitPublisher | None = None,
) -> GitRepositoryStatusReadHandler:
    resolver = repository_resolver or (repositories_by_install_id or {}).get
    handler = GitRepositoryStatusReadHandler(
        repository_resolver=resolver,
        git_publisher=git_publisher or GitPublisher(),
    )
    handler_registry.register(handler)
    return handler


def _validate_input(input_data: dict[str, Any]) -> bool:
    allowed = {"include_changed_paths"}
    unknown = sorted(set(input_data) - allowed)
    if unknown:
        raise PlaybookExecutionError(
            "GIT_INPUT_INVALID",
            "Git repository status read does not accept arbitrary input.",
            {"fields": unknown},
        )
    value = input_data.get("include_changed_paths", True)
    if not isinstance(value, bool):
        raise PlaybookExecutionError(
            "GIT_INPUT_INVALID",
            "include_changed_paths must be a boolean.",
            {"field": "include_changed_paths"},
        )
    return value


def _parse_status_paths(status_output: str) -> list[str]:
    paths: list[str] = []
    for line in status_output.splitlines():
        if not line.strip():
            continue
        if len(line) > 3 and line[2] == " ":
            path = line[3:]
        elif len(line) > 2 and line[1] == " ":
            path = line[2:]
        else:
            path = line
        paths.append(str(Path(path)))
    return sorted(paths)
