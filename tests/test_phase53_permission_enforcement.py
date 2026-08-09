from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

from channels.markdown_website.git_publisher import GitPublisher
from publication_git_mutation_admission import WEBSITE_ARTICLE_PUBLISH_CAPABILITY, website_article_publish_admission
from publication_git_runtime_handlers import (
    GIT_REPOSITORY_STATUS_READ_CAPABILITY,
    GIT_WEBSITE_COMPONENT_ID,
    register_git_runtime_handlers,
)
from runtime_foundation_mappings import phase41_runtime_registry
from src.core.runtime import (
    CapabilityHandlerRegistry,
    ComponentBinding,
    DeploymentPolicy,
    EventEnvelope,
    EventSource,
    Install,
    InstallGrants,
    PlaybookExecutor,
    RuntimePolicyEngine,
    compile_execution_plan,
)
from src.core.runtime.ledger import ExecutionState
from src.core.runtime.permissions import InstallPermissionGrants, capability_permission_requirements
from tests.test_phase45_git_runtime_bridge import (
    git,
    git_deployment,
    init_repo,
    load_git_playbook,
    repository_reference,
)


class CountingGitPublisher(GitPublisher):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def git(self, cwd: Path, *args: str, check: bool = True) -> str | None:
        self.calls += 1
        return super().git(cwd, *args, check=check)


def _event() -> EventEnvelope:
    return EventEnvelope(
        event_type="git.repository.status.requested",
        source=EventSource(component="phase53-test", provider="github"),
        workspace_id="workspace-1",
        idempotency_key="phase53-git-read",
        payload={"include_changed_paths": True},
    )


def _install(permission_grants: InstallPermissionGrants) -> Install:
    return Install(
        install_id="website-local-test",
        workspace_id="workspace-1",
        provider="github",
        account_ref="repo-phase53",
        component_bindings={GIT_REPOSITORY_STATUS_READ_CAPABILITY: ComponentBinding(GIT_WEBSITE_COMPONENT_ID)},
        config={"repository_reference_id": "repo-phase53"},
        grants=InstallGrants(
            allowed_capabilities=(GIT_REPOSITORY_STATUS_READ_CAPABILITY,),
            allow_filesystem=True,
            allow_subprocess=True,
            permission_grants=permission_grants,
        ),
    )


def _executor(
    repo: Path, permission_grants: InstallPermissionGrants
) -> tuple[PlaybookExecutor, CountingGitPublisher, object]:
    registry = phase41_runtime_registry()
    install = _install(permission_grants)
    registry.register_install(install)
    deployment = replace(
        git_deployment(),
        policy=DeploymentPolicy(allow_filesystem=True, allow_subprocess=True),
    )
    plan = compile_execution_plan(load_git_playbook(), deployment, registry)
    handlers = CapabilityHandlerRegistry()
    publisher = CountingGitPublisher()
    register_git_runtime_handlers(
        handlers,
        repositories_by_install_id={"website-local-test": repository_reference(repo)},
        git_publisher=publisher,
    )
    return (
        PlaybookExecutor(
            handlers,
            policy_engine=RuntimePolicyEngine(registry=registry, deployments={deployment.deployment_id: deployment}),
        ),
        publisher,
        plan,
    )


def test_git_read_with_explicit_permission_grants_succeeds() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = init_repo(Path(tmp))
        before = git(repo, "rev-parse", "HEAD")
        executor, publisher, plan = _executor(
            repo,
            InstallPermissionGrants.from_dict(
                {
                    "filesystem": {"read": ["repository"]},
                    "operations": ["git.status", "git.rev_parse", "git.cat_file"],
                }
            ),
        )

        outcome = executor.execute(plan=plan, trigger_event=_event())

        assert outcome.execution.state == ExecutionState.SUCCEEDED.value
        assert publisher.calls > 0
        assert outcome.context.node_outputs["read-repository"]["head"] == before


def test_git_read_missing_operation_grant_blocks_before_subprocess() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = init_repo(Path(tmp))
        executor, publisher, plan = _executor(
            repo,
            InstallPermissionGrants.from_dict({"filesystem": {"read": ["repository"]}, "operations": ["git.status"]}),
        )

        outcome = executor.execute(plan=plan, trigger_event=_event())

        assert outcome.execution.state == ExecutionState.FAILED.value
        assert publisher.calls == 0
        assert _node_error(executor, outcome.execution.execution_id, "read-repository") == "SUBPROCESS_NOT_ALLOWED"


def test_git_read_missing_repository_read_grant_blocks_before_subprocess() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = init_repo(Path(tmp))
        executor, publisher, plan = _executor(
            repo,
            InstallPermissionGrants.from_dict({"operations": ["git.status", "git.rev_parse", "git.cat_file"]}),
        )

        outcome = executor.execute(plan=plan, trigger_event=_event())

        assert outcome.execution.state == ExecutionState.FAILED.value
        assert publisher.calls == 0
        assert _node_error(executor, outcome.execution.execution_id, "read-repository") == (
            "FILESYSTEM_ACCESS_NOT_ALLOWED"
        )


def test_phase53_website_admission_permission_blockers_are_structurally_resolved() -> None:
    registry = phase41_runtime_registry()
    component = registry.components[GIT_WEBSITE_COMPONENT_ID]
    install = registry.installs["github-don-website"]

    result = website_article_publish_admission(component=component, install=install)
    requested = capability_permission_requirements(component, WEBSITE_ARTICLE_PUBLISH_CAPABILITY)

    assert "repository" in requested.filesystem.write
    assert {"git.add.path", "git.commit", "git.push"}.issubset(set(requested.operations.operations))
    assert requested.network.egress
    assert "BLOCKED_COMPONENT_PERMISSION_MISMATCH" not in result.reasons
    assert "BLOCKED_UNCONTROLLED_GIT_OPERATION" not in result.reasons
    assert "BLOCKED_REMOTE_EGRESS_POLICY" not in result.reasons
    assert "BLOCKED_IDEMPOTENCY" not in result.reasons
    assert "BLOCKED_READBACK" not in result.reasons
    assert "BLOCKED_RECOVERY" not in result.reasons
    assert "BLOCKED_HANDLER_NOT_REGISTERED" not in result.reasons


def test_website_publish_handler_is_still_not_registered() -> None:
    handlers = CapabilityHandlerRegistry()
    register_git_runtime_handlers(handlers, repositories_by_install_id={})

    assert handlers.resolve(GIT_WEBSITE_COMPONENT_ID, GIT_REPOSITORY_STATUS_READ_CAPABILITY)
    try:
        handlers.resolve(GIT_WEBSITE_COMPONENT_ID, WEBSITE_ARTICLE_PUBLISH_CAPABILITY)
    except Exception as exc:
        assert getattr(exc, "code", "") == "HANDLER_NOT_FOUND"
    else:  # pragma: no cover
        raise AssertionError("website.article.publish must remain blocked in Phase 53")


def _node_error(executor: PlaybookExecutor, execution_id: str, node_id: str) -> str:
    records = [record for record in executor.ledger.list_node_executions(execution_id) if record.node_id == node_id]
    return records[-1].error_code
