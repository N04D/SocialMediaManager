from __future__ import annotations

import inspect
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from channels.markdown_website.git_publisher import GitHeadState, GitPublisher
from channels.markdown_website.models import WebsiteRepositoryReference
from publication_git_runtime_handlers import (
    GIT_REPOSITORY_STATUS_READ_CAPABILITY,
    GIT_WEBSITE_COMPONENT_ID,
    GitRepositoryStatusReadHandler,
    register_git_runtime_handlers,
)
from runtime_foundation_mappings import phase41_runtime_registry
from src.core.runtime.capabilities import CapabilityMode
from src.core.runtime.deployments import PlaybookDeployment, RequirementBinding
from src.core.runtime.errors import DeploymentValidationError, PlaybookExecutionError
from src.core.runtime.events import EventEnvelope, EventSource
from src.core.runtime.executor import PlaybookExecutor
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.installs import ComponentBinding, Install
from src.core.runtime.ledger import ExecutionState
from src.core.runtime.plans import ExecutionPlanNode, compile_execution_plan
from src.core.runtime.playbooks import PlaybookDefinition, PlaybookNode
from src.core.runtime.resolver import RuntimeRegistry
from src.core.runtime.results import NodeResultStatus
from src.core.runtime.tracing import trace_execution


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def init_repo(root: Path, *, commit: bool = True) -> Path:
    repo = root / "site-repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    if commit:
        (repo / "README.md").write_text("fixture site\n", encoding="utf-8")
        (repo / "docs").mkdir()
        (repo / "docs" / "example.md").write_text("example\n", encoding="utf-8")
        git(repo, "add", "README.md", "docs/example.md")
        git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "init")
    return repo


def repository_reference(repo: Path, *, enabled: bool = True) -> WebsiteRepositoryReference:
    return WebsiteRepositoryReference(
        id="repo-phase45",
        workspace_id="workspace-1",
        display_name="Phase 45 repo",
        managed_checkout_root=repo,
        allowed_content_roots=("articles",),
        allowed_media_roots=("static/media",),
        allowed_branches=("main",),
        enabled=enabled,
    )


def load_git_playbook() -> PlaybookDefinition:
    payload = json.loads(
        Path("tests/fixtures/playbooks/phase45_git_repository_status.json").read_text(encoding="utf-8")
    )
    return PlaybookDefinition.from_dict(payload)


def git_deployment(install_id: str = "website-local-test") -> PlaybookDeployment:
    return PlaybookDeployment(
        deployment_id="phase45-git-status",
        playbook_id="git.phase45.repository-status",
        playbook_version="1.0.0",
        workspace_id="workspace-1",
        requirement_bindings={"repository": RequirementBinding(install_id)},
    )


def git_registry(install_id: str = "website-local-test") -> RuntimeRegistry:
    registry = phase41_runtime_registry()
    registry.register_install(
        Install(
            install_id=install_id,
            workspace_id="workspace-1",
            provider="github",
            account_ref="repo-phase45",
            component_bindings={
                "git.repository.status.read": ComponentBinding(GIT_WEBSITE_COMPONENT_ID),
            },
            config={"repository_reference_id": "repo-phase45"},
            secret_refs=(),
        )
    )
    return registry


def git_event(payload: dict[str, object] | None = None) -> EventEnvelope:
    return EventEnvelope(
        event_type="git.repository.status.requested",
        source=EventSource(component="phase45-test", provider="github"),
        workspace_id="workspace-1",
        correlation_id="phase45-correlation",
        trace_id="phase45-trace",
        idempotency_key="phase45-git-status",
        payload=payload or {"include_changed_paths": True},
    )


def compile_git_plan(install_id: str = "website-local-test"):
    return compile_execution_plan(load_git_playbook(), git_deployment(install_id), git_registry(install_id))


def repo_integrity(repo: Path) -> dict[str, str]:
    return {
        "head": git(repo, "rev-parse", "HEAD"),
        "status": git(repo, "status", "--porcelain"),
        "tracked": git(repo, "ls-files", "-s"),
        "readme": (repo / "README.md").read_text(encoding="utf-8") if (repo / "README.md").exists() else "",
        "example": (repo / "docs" / "example.md").read_text(encoding="utf-8")
        if (repo / "docs" / "example.md").exists()
        else "",
    }


def read_only_subprocess_spy(commands: list[tuple[str, ...]]):
    original_run = subprocess.run
    forbidden = {"add", "commit", "push", "reset", "checkout", "clean", "merge", "rebase", "fetch", "pull", "tag"}

    def run(command, *args, **kwargs):  # type: ignore[no-untyped-def]
        normalized = tuple(str(part) for part in command)
        commands.append(normalized)
        if normalized and Path(normalized[0]).name == "git":
            operation = normalized[1] if len(normalized) > 1 else ""
            if operation in forbidden:
                raise AssertionError(f"forbidden git command: {' '.join(normalized)}")
            if operation == "branch" and "-D" in normalized:
                raise AssertionError(f"forbidden git command: {' '.join(normalized)}")
            if operation in {"ls-remote"}:
                raise AssertionError(f"forbidden remote git command: {' '.join(normalized)}")
        return original_run(command, *args, **kwargs)

    return run


def test_real_git_repository_status_read_through_playbook_executor() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = init_repo(Path(tmp))
        before = repo_integrity(repo)
        commands: list[tuple[str, ...]] = []
        handler_registry = CapabilityHandlerRegistry()
        handler = register_git_runtime_handlers(
            handler_registry,
            repositories_by_install_id={"website-local-test": repository_reference(repo)},
        )
        executor = PlaybookExecutor(handler_registry)

        with patch(
            "channels.markdown_website.git_publisher.subprocess.run", side_effect=read_only_subprocess_spy(commands)
        ):
            outcome = executor.execute(plan=compile_git_plan(), trigger_event=git_event())

        after = repo_integrity(repo)
        assert handler.component_id == GIT_WEBSITE_COMPONENT_ID
        assert handler.capability_id == GIT_REPOSITORY_STATUS_READ_CAPABILITY
        assert outcome.execution.state == ExecutionState.SUCCEEDED.value
        assert outcome.context.node_outputs["read-repository"] == {
            "branch": "main",
            "changed_paths": [],
            "clean": True,
            "head": before["head"],
            "repository": "repo-phase45",
            "source": "github-markdown-website",
            "state": "existing",
        }
        assert before == after
        observed_ops = [command[1:] for command in commands]
        assert ("branch", "--show-current") in observed_ops
        assert ("rev-parse", "--verify", "HEAD") in observed_ops
        assert ("cat-file", "-e", f"{before['head']}^{{commit}}") in observed_ops
        assert ("status", "--porcelain") in observed_ops
        trace = trace_execution(executor.ledger, outcome.execution.execution_id).to_dict()
        read_node = next(node for node in trace["nodes"] if node["node_id"] == "read-repository")
        assert read_node["metadata"] == {
            "capability": "git.repository.status.read",
            "component_id": "github-markdown-website",
            "install_id": "website-local-test",
            "kind": "capability",
            "provider": "github",
            "requirement": "repository",
        }


def test_dirty_repository_normalized_output_is_read_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = init_repo(Path(tmp))
        (repo / "README.md").write_text("fixture site\nuser edit\n", encoding="utf-8")
        before_head = git(repo, "rev-parse", "HEAD")
        handler_registry = CapabilityHandlerRegistry()
        register_git_runtime_handlers(
            handler_registry,
            repositories_by_install_id={"website-local-test": repository_reference(repo)},
        )

        outcome = PlaybookExecutor(handler_registry).execute(plan=compile_git_plan(), trigger_event=git_event())

        output = outcome.context.node_outputs["read-repository"]
        assert outcome.execution.state == ExecutionState.SUCCEEDED.value
        assert output["clean"] is False
        assert output["changed_paths"] == ["README.md"]
        assert git(repo, "rev-parse", "HEAD") == before_head


def test_unborn_empty_repository_is_valid_status_result() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = init_repo(Path(tmp), commit=False)
        handler_registry = CapabilityHandlerRegistry()
        register_git_runtime_handlers(
            handler_registry,
            repositories_by_install_id={"website-local-test": repository_reference(repo)},
        )

        outcome = PlaybookExecutor(handler_registry).execute(plan=compile_git_plan(), trigger_event=git_event())

        assert outcome.execution.state == ExecutionState.SUCCEEDED.value
        assert outcome.context.node_outputs["read-repository"]["state"] == "unborn"
        assert outcome.context.node_outputs["read-repository"]["head"] == ""


def test_missing_repo_failure_code_in_ledger() -> None:
    handler_registry = CapabilityHandlerRegistry()
    register_git_runtime_handlers(handler_registry, repositories_by_install_id={})
    executor = PlaybookExecutor(handler_registry)

    outcome = executor.execute(plan=compile_git_plan(), trigger_event=git_event())
    failed = [
        node
        for node in executor.ledger.list_node_executions(outcome.execution.execution_id)
        if node.node_id == "read-repository"
    ]

    assert failed[-1].error_code == "GIT_REPOSITORY_MISSING"


def test_invalid_repository_root_fails_controlled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        not_repo = Path(tmp) / "not-repo"
        not_repo.mkdir()
        handler_registry = CapabilityHandlerRegistry()
        register_git_runtime_handlers(
            handler_registry,
            repositories_by_install_id={"website-local-test": repository_reference(not_repo)},
        )
        executor = PlaybookExecutor(handler_registry)

        outcome = executor.execute(plan=compile_git_plan(), trigger_event=git_event())
        failed = [
            node
            for node in executor.ledger.list_node_executions(outcome.execution.execution_id)
            if node.node_id == "read-repository"
        ]

    assert outcome.execution.state == ExecutionState.FAILED.value
    assert failed[-1].error_code == "CAPABILITY_EXECUTION_FAILED"


def test_missing_install_fails_before_execution() -> None:
    with pytest.raises(DeploymentValidationError) as exc:
        compile_execution_plan(load_git_playbook(), git_deployment("missing-install"), git_registry())

    assert exc.value.details["error_code"] == "INSTALL_MISSING"


def test_missing_handler_is_controlled_runtime_failure() -> None:
    executor = PlaybookExecutor(CapabilityHandlerRegistry())

    outcome = executor.execute(plan=compile_git_plan(), trigger_event=git_event())
    failed = [
        node
        for node in executor.ledger.list_node_executions(outcome.execution.execution_id)
        if node.node_id == "read-repository"
    ]

    assert outcome.execution.state == ExecutionState.FAILED.value
    assert failed[-1].error_code == "HANDLER_NOT_FOUND"


def test_invalid_input_and_path_traversal_are_rejected() -> None:
    handler = GitRepositoryStatusReadHandler(
        repository_resolver=lambda install_id: None,
        git_publisher=GitPublisher(),
    )

    for payload in (
        {"command": "git status"},
        {"path": "../secret.txt"},
        {"path": "/etc/passwd"},
        {"include_changed_paths": "yes"},
    ):
        result = handler.execute(
            context=git_event().source and None,  # type: ignore[arg-type]
            node=PlaybookNode("read-repository", "capability"),
            resolved_node=ExecutionPlanNode("read-repository", "capability", install_id="website-local-test"),
            input_data=payload,
        )
        assert result.status == NodeResultStatus.FAILURE.value
        assert result.error_code == "GIT_INPUT_INVALID"


def test_service_failure_maps_to_capability_execution_failed() -> None:
    class FailingGitPublisher(GitPublisher):
        def head_state(self, repo_root: Path) -> GitHeadState:
            raise RuntimeError("git unavailable")

    with tempfile.TemporaryDirectory() as tmp:
        repo = init_repo(Path(tmp))
        handler_registry = CapabilityHandlerRegistry()
        register_git_runtime_handlers(
            handler_registry,
            repositories_by_install_id={"website-local-test": repository_reference(repo)},
            git_publisher=FailingGitPublisher(),
        )
        executor = PlaybookExecutor(handler_registry)

        outcome = executor.execute(plan=compile_git_plan(), trigger_event=git_event())
        failed = [
            node
            for node in executor.ledger.list_node_executions(outcome.execution.execution_id)
            if node.node_id == "read-repository"
        ]

    assert outcome.execution.state == ExecutionState.FAILED.value
    assert failed[-1].error_code == "CAPABILITY_EXECUTION_FAILED"


def test_only_status_read_handler_is_registered_and_descriptor_is_read_mode() -> None:
    registry = phase41_runtime_registry()
    component = registry.components[GIT_WEBSITE_COMPONENT_ID]
    descriptor = component.capability(GIT_REPOSITORY_STATUS_READ_CAPABILITY)
    assert descriptor is not None
    assert descriptor.mode == CapabilityMode.READ.value
    handler_registry = CapabilityHandlerRegistry()
    register_git_runtime_handlers(handler_registry, repositories_by_install_id={})

    with pytest.raises(PlaybookExecutionError):
        handler_registry.resolve(GIT_WEBSITE_COMPONENT_ID, "github.file.write")


def test_calendar_and_git_bridges_use_same_generic_runtime_shape() -> None:
    from publication_calendar_runtime_handlers import CalendarEventReadHandler

    assert isinstance(CalendarEventReadHandler, type)
    assert isinstance(GitRepositoryStatusReadHandler, type)
    assert hasattr(PlaybookExecutor, "execute")
    executor_source = inspect.getsource(PlaybookExecutor)
    assert "calendar.event.read" not in executor_source
    assert "git.repository.status.read" not in executor_source
    assert "github-markdown-website" not in executor_source
