from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest
from channels.markdown_website.git_publisher import GitPublisher
from channels.markdown_website.models import WebsiteRepositoryReference
from publication_calendar_runtime_handlers import (
    CalendarEventCreateHandler,
    register_calendar_mutation_runtime_handlers,
)
from publication_git_mutation_admission import WEBSITE_ARTICLE_PUBLISH_CAPABILITY
from publication_git_runtime_handlers import (
    GIT_WEBSITE_COMPONENT_ID,
    register_and_activate_website_publish,
)
from runtime_foundation_mappings import phase41_component_manifests
from src.core.runtime.capabilities import CapabilityDescriptor, CapabilityMode
from src.core.runtime.components import ComponentManifest
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.events import EventEnvelope, EventSource
from src.core.runtime.execution_context import ExecutionContext
from src.core.runtime.executor import PlaybookExecutor
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.installs import ComponentBinding, Install, InstallGrants
from src.core.runtime.mutations import SqliteMutationJournal
from src.core.runtime.permissions import (
    ComponentPermissions,
    EffectivePermissionSet,
    EgressDestination,
    FilesystemPermissions,
    InstallPermissionGrants,
    NetworkPermissions,
    OperationPermissions,
    PermissionContext,
    resolve_effective_permissions,
)
from src.core.runtime.plans import ExecutionPlanNode, compile_execution_plan
from src.core.runtime.playbooks import (
    CapabilityRequirement,
    PlaybookDefinition,
    PlaybookEdge,
    PlaybookNode,
    PlaybookNodeKind,
)
from src.core.runtime.policy import ApprovalRecord, ApprovalStatus, InMemoryApprovalStore


def _git_component() -> ComponentManifest:
    manifests = {m.component_id: m for m in phase41_component_manifests()}
    return manifests[GIT_WEBSITE_COMPONENT_ID]


def _admitted_install(remote_url: str = "") -> Install:
    return Install(
        install_id="website-prod-install",
        workspace_id="local",
        provider="github",
        account_ref="main_repo",
        component_bindings={
            WEBSITE_ARTICLE_PUBLISH_CAPABILITY: ComponentBinding(GIT_WEBSITE_COMPONENT_ID),
        },
        grants=InstallGrants(
            allowed_capabilities=(
                "git.repository.status.read",
                "github.file.read",
                "website.publication.verify",
                WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
            ),
            allow_mutations=True,
            allow_filesystem=True,
            allow_subprocess=True,
            permission_grants=InstallPermissionGrants.from_dict({
                "filesystem": {"read": ["repository"], "write": ["repository"]},
                "operations": [
                    "git.status",
                    "git.rev_parse",
                    "git.cat_file",
                    "git.add.path",
                    "git.commit",
                    "git.push",
                ],
                "network": {"egress": [{"host": "github.com", "port": 443, "scheme": "https"}]},
            }),
        ),
    )


def _setup_git_repo(tmp_path: Path) -> tuple[Path, Path, WebsiteRepositoryReference]:
    remote_dir = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote_dir)], check=True, capture_output=True)

    repo_dir = tmp_path / "checkout"
    repo_dir.mkdir()
    subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    (repo_dir / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote_dir)], cwd=repo_dir, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo_dir, check=True, capture_output=True)

    ref = WebsiteRepositoryReference(
        id="test-repo-ref",
        workspace_id="local",
        display_name="test-repo",
        managed_checkout_root=repo_dir,
        allowed_remote_names=("origin",),
        allowed_branches=("main",),
    )
    return repo_dir, remote_dir, ref


def test_production_capability_boundary_exactly_two_mutations() -> None:
    registry = CapabilityHandlerRegistry()
    component = _git_component()
    install = _admitted_install()

    # Register only admitted production handlers
    handler_cal = CalendarEventCreateHandler(calendar_service=None, occurrence_repository=None)  # type: ignore
    registry.register(handler_cal)
    activation_result = register_and_activate_website_publish(
        registry,
        component=component,
        install=install,
        repository_resolver=lambda iid: None,
    )
    assert activation_result.activated

    registered_mutations = []
    for (comp_id, cap_id), handler in registry._handlers.items():
        policy = getattr(handler, "mutation_policy", None)
        if policy is not None:
            registered_mutations.append((comp_id, cap_id))

    # Total active production mutations MUST be exactly 2!
    assert len(registered_mutations) == 2
    assert ("publication-calendar-local", "calendar.event.create") in registered_mutations
    assert ("github-markdown-website", "website.article.publish") in registered_mutations

    # Unadmitted capabilities MUST NOT be registered
    with pytest.raises(PlaybookExecutionError):
        registry.resolve("github-markdown-website", "github.file.write")


def test_end_to_end_website_article_publish(tmp_path: Path) -> None:
    repo_dir, remote_dir, repo_ref = _setup_git_repo(tmp_path)
    publisher = GitPublisher()
    registry = CapabilityHandlerRegistry()

    activation_result = register_and_activate_website_publish(
        registry,
        component=_git_component(),
        install=_admitted_install(),
        repository_resolver=lambda iid: repo_ref,
        git_publisher=publisher,
    )
    assert activation_result.activated
    handler = activation_result.handler
    assert handler is not None

    trigger_ev = EventEnvelope(
        event_type="test.publish",
        source=EventSource(component="test", provider="github"),
        workspace_id="local",
        correlation_id="corr-55",
        trace_id="trace-55",
        idempotency_key="idemp-55",
        payload={},
    )
    ctx = ExecutionContext(
        execution_id="exec-55-e2e",
        deployment_id="dep-55",
        trigger_event=trigger_ev,
    )
    node = PlaybookNode(
        node_id="publish_node",
        kind=PlaybookNodeKind.CAPABILITY.value,
        config={"requirement": "website", "capability": WEBSITE_ARTICLE_PUBLISH_CAPABILITY},
    )

    perm_ctx = PermissionContext(
        effective=resolve_effective_permissions(
            requested=ComponentPermissions.from_dict({
                "filesystem": {"read": ["repository"], "write": ["repository"]},
                "operations": ["git.status", "git.rev_parse", "git.cat_file", "git.add.path", "git.commit", "git.push"],
                "network": {"egress": [{"host": "github.com", "port": 443, "scheme": "https"}]},
            }),
            grants=InstallPermissionGrants.from_dict({
                "filesystem": {"read": ["repository"], "write": ["repository"]},
                "operations": ["git.status", "git.rev_parse", "git.cat_file", "git.add.path", "git.commit", "git.push"],
                "network": {"egress": [{"host": "github.com", "port": 443, "scheme": "https"}]},
            }),
        )
    )

    input_data = {
        "title": "Phase 55 Launch Article",
        "markdown_content": "# Hello Phase 55\n\nWebsite article publish is now active.\n",
        "relative_path": "posts/phase55-launch.md",
        "branch": "main",
        "remote_name": "origin",
        "push": True,
        "content_item_id": "item-55",
        "content_revision_id": "rev-55",
        "publication_target_id": "target-55",
        "publication_attempt_id": "att-55",
        "mutation_id": "mut-55-e2e",
        "intent_fingerprint": "fp-intent-55",
        "_runtime": {"permission_context": perm_ctx},
    }

    resolved_node = ExecutionPlanNode(
        node_id="publish_node",
        kind=PlaybookNodeKind.CAPABILITY.value,
        requirement="website",
        capability=WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
        component_id=GIT_WEBSITE_COMPONENT_ID,
        install_id="website-prod-install",
        provider="github",
    )

    res = handler.execute(
        context=ctx,
        node=node,
        resolved_node=resolved_node,
        input_data=input_data,
    )

    assert res.status == "success"
    assert res.output["readback_verified"] is True
    commit_sha = res.output["publication_commit"]
    assert commit_sha

    # Verify provenance headers in local Git commit message
    commit_msg = publisher.git(repo_dir, "log", "-1", "--pretty=%B", commit_sha)
    assert "Content-Revision: rev-55" in commit_msg
    assert "Publication-Target: target-55" in commit_msg
    assert "Mutation-ID: mut-55-e2e" in commit_msg
    assert "Intent-Fingerprint: fp-intent-55" in commit_msg

    # Verify target file exists in working tree and remote
    target_file = repo_dir / "posts/phase55-launch.md"
    assert target_file.exists()
    assert "# Hello Phase 55" in target_file.read_text(encoding="utf-8")

    # Readback verification check
    verified = handler.verify_readback(
        receipt=from_dict_receipt(res.output["mutation_receipt"]),
        context=ctx,
    )
    assert verified is True


def test_working_tree_isolation_preexisting_unrelated_unstaged(tmp_path: Path) -> None:
    repo_dir, remote_dir, repo_ref = _setup_git_repo(tmp_path)
    publisher = GitPublisher()
    registry = CapabilityHandlerRegistry()

    activation_result = register_and_activate_website_publish(
        registry,
        component=_git_component(),
        install=_admitted_install(),
        repository_resolver=lambda iid: repo_ref,
        git_publisher=publisher,
    )
    handler = activation_result.handler
    assert handler is not None

    # Pre-existing UNSTAGED file in working tree
    unrelated_file = repo_dir / "unrelated-notes.txt"
    unrelated_file.write_text("untracked notes", encoding="utf-8")

    trigger_ev = EventEnvelope(
        event_type="test.publish",
        source=EventSource(component="test", provider="github"),
        workspace_id="local",
        correlation_id="corr-iso",
        trace_id="trace-iso",
        idempotency_key="idemp-iso",
        payload={},
    )
    ctx = ExecutionContext(
        execution_id="exec-isolation-unstaged",
        deployment_id="dep-iso",
        trigger_event=trigger_ev,
    )

    resolved_node = ExecutionPlanNode(
        node_id="publish_node",
        kind=PlaybookNodeKind.CAPABILITY.value,
        requirement="website",
        capability=WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
        component_id=GIT_WEBSITE_COMPONENT_ID,
        install_id="website-prod-install",
        provider="github",
    )
    node = PlaybookNode(
        node_id="publish_node",
        kind=PlaybookNodeKind.CAPABILITY.value,
        config={"requirement": "website", "capability": WEBSITE_ARTICLE_PUBLISH_CAPABILITY},
    )

    input_data = {
        "title": "Isolated Article",
        "markdown_content": "# Isolated Article\n",
        "relative_path": "posts/isolated.md",
        "push": False,
        "content_revision_id": "rev-iso",
        "publication_target_id": "target-iso",
    }

    res = handler.execute(context=ctx, node=node, resolved_node=resolved_node, input_data=input_data)
    assert res.status == "success"

    # Unrelated unstaged file MUST REMAIN UNSTAGED and UNCOMMITTED!
    status_out = publisher.git(repo_dir, "status", "--porcelain")
    assert "unrelated-notes.txt" in status_out

    commit_sha = res.output["publication_commit"]
    commit_files = publisher.git(repo_dir, "show", "--name-only", "--pretty=", commit_sha)
    assert "posts/isolated.md" in commit_files
    assert "unrelated-notes.txt" not in commit_files


def test_working_tree_isolation_preexisting_staged_blocks_publish(tmp_path: Path) -> None:
    repo_dir, remote_dir, repo_ref = _setup_git_repo(tmp_path)
    publisher = GitPublisher()
    registry = CapabilityHandlerRegistry()

    activation_result = register_and_activate_website_publish(
        registry,
        component=_git_component(),
        install=_admitted_install(),
        repository_resolver=lambda iid: repo_ref,
        git_publisher=publisher,
    )
    handler = activation_result.handler
    assert handler is not None

    # Pre-existing STAGED file in git index
    staged_file = repo_dir / "staged-draft.txt"
    staged_file.write_text("staged draft", encoding="utf-8")
    publisher.git(repo_dir, "add", "staged-draft.txt")

    trigger_ev = EventEnvelope(
        event_type="test.publish",
        source=EventSource(component="test", provider="github"),
        workspace_id="local",
        correlation_id="corr-staged",
        trace_id="trace-staged",
        idempotency_key="idemp-staged",
        payload={},
    )
    ctx = ExecutionContext(
        execution_id="exec-isolation-staged",
        deployment_id="dep-staged",
        trigger_event=trigger_ev,
    )

    resolved_node = ExecutionPlanNode(
        node_id="publish_node",
        kind=PlaybookNodeKind.CAPABILITY.value,
        requirement="website",
        capability=WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
        component_id=GIT_WEBSITE_COMPONENT_ID,
        install_id="website-prod-install",
        provider="github",
    )
    node = PlaybookNode(
        node_id="publish_node",
        kind=PlaybookNodeKind.CAPABILITY.value,
        config={"requirement": "website", "capability": WEBSITE_ARTICLE_PUBLISH_CAPABILITY},
    )

    input_data = {
        "title": "Blocked Publish",
        "markdown_content": "# Should be blocked\n",
        "relative_path": "posts/should-block.md",
        "push": False,
    }

    # Pre-existing staged files MUST block publish execution safely!
    with pytest.raises(PlaybookExecutionError) as exc_info:
        handler.execute(context=ctx, node=node, resolved_node=resolved_node, input_data=input_data)
    assert exc_info.value.code == "UNCONTROLLED_GIT_STAGING"

    # 0 target files written, 0 extra commits
    assert not (repo_dir / "posts/should-block.md").exists()


def from_dict_receipt(payload: dict[str, Any]) -> Any:
    from src.core.runtime.mutations import MutationReceipt

    return MutationReceipt(
        mutation_id=payload["mutation_id"],
        idempotency_key=payload["idempotency_key"],
        capability_id=payload["capability_id"],
        component_id=payload["component_id"],
        resource_ref=payload["resource_ref"],
        applied_at=payload["applied_at"],
        result_fingerprint=payload["result_fingerprint"],
        metadata=dict(payload.get("metadata") or {}),
    )
