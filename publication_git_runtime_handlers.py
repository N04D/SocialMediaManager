from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from channels.markdown_website.errors import MarkdownWebsiteError
from channels.markdown_website.git_publisher import GitPublisher, sha256_path
from channels.markdown_website.models import (
    RenderedMarkdown,
    WebsiteMutationManifest,
    WebsitePublicationEvidence,
    WebsitePublicationSnapshot,
    WebsiteRepositoryReference,
)
from channels.markdown_website.paths import ensure_under, validate_repository_reference
from publication_git_publish_safety import (
    WebsitePublishReadbackState,
    approved_publish_fingerprint,
    build_website_publish_identity,
    verify_website_publish,
    website_publish_safety_guarantees,
)
from src.core.runtime.candidates import (
    MutationHandlerCandidate,
    ProductionMutationActivationResult,
    admit_and_register_mutation,
)

from src.core.runtime.components import ComponentManifest
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.execution_context import ExecutionContext, _assert_no_secret_values
from src.core.runtime.handlers import CapabilityHandler, CapabilityHandlerRegistry
from src.core.runtime.installs import Install
from src.core.runtime.mutation_policies import (
    CompensationPolicy,
    MutationPolicy,
    ReadbackPolicy,
    RecoveryPolicy,
)
from src.core.runtime.mutations import MutationReceipt, mutation_input_fingerprint
from src.core.runtime.plans import ExecutionPlanNode
from src.core.runtime.playbooks import PlaybookNode
from src.core.runtime.results import NodeResult

GIT_WEBSITE_COMPONENT_ID = "github-markdown-website"
GIT_REPOSITORY_STATUS_READ_CAPABILITY = "git.repository.status.read"
WEBSITE_ARTICLE_PUBLISH_CAPABILITY = "website.article.publish"

GIT_STATUS_OPERATION = "git.status"
GIT_REV_PARSE_OPERATION = "git.rev_parse"
GIT_CAT_FILE_OPERATION = "git.cat_file"

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
        _assert_no_secret_values(input_data)
        include_changed_paths = _validate_input(input_data)
        permission_context = _permission_context(input_data)

        if permission_context is not None:
            permission_context.require_filesystem_read("repository")
            permission_context.require_operation(GIT_STATUS_OPERATION)
            permission_context.require_operation(GIT_REV_PARSE_OPERATION)
            permission_context.require_operation(GIT_CAT_FILE_OPERATION)

        repository = self._repository_for_install(resolved_node.install_id)
        validate_repository_reference(repository)

        try:
            repo_root = repository.managed_checkout_root
            head_state = self.git_publisher.head_state(repo_root)
            status_out = self.git_publisher.git(repo_root, "status", "--porcelain") or ""
            clean = not bool(status_out.strip())
            branch = head_state.branch or "main"
            head = head_state.commit_sha
            output: dict[str, Any] = {
                "branch": branch,
                "clean": clean,
                "head": head,
                "repository": getattr(repository, "display_name", getattr(repository, "id", "repository")),
                "source": "local_git",
                "state": "clean" if clean else "dirty",
            }
            if include_changed_paths:
                output["changed_paths"] = _parse_status_paths(status_out)
        except MarkdownWebsiteError as exc:
            raise PlaybookExecutionError(
                "GIT_REPOSITORY_STATUS_FAILED",
                str(exc),
                {"details": exc.details},
            ) from exc
        except Exception as exc:
            raise PlaybookExecutionError(
                "GIT_REPOSITORY_STATUS_FAILED",
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


@dataclass
class WebsiteArticlePublishHandler:
    repository_resolver: RepositoryResolver
    git_publisher: GitPublisher
    remote_name: str = "origin"
    component_id: str = GIT_WEBSITE_COMPONENT_ID
    capability_id: str = WEBSITE_ARTICLE_PUBLISH_CAPABILITY
    mutation_policy: MutationPolicy = MutationPolicy(
        requires_approval=True,
        idempotency_required=True,
        readback=ReadbackPolicy.REQUIRED.value,
        compensation=CompensationPolicy.UNAVAILABLE.value,
        recovery=RecoveryPolicy.MANUAL.value,
    )

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> NodeResult:
        _assert_no_secret_values(input_data)
        permission_context = _permission_context(input_data)

        title = str(input_data.get("title") or "Untitled Article")
        markdown_content = str(input_data.get("markdown_content") or "")
        relative_path = str(input_data.get("relative_path") or "posts/article.md")
        branch = str(input_data.get("branch") or "main")
        remote_name = str(input_data.get("remote_name") or self.remote_name)
        push = bool(input_data.get("push", True))

        content_item_id = str(input_data.get("content_item_id") or "item-001")
        content_revision_id = str(input_data.get("content_revision_id") or "rev-001")
        publication_target_id = str(input_data.get("publication_target_id") or "target-001")
        publication_attempt_id = str(input_data.get("publication_attempt_id") or "attempt-001")

        repository = self.repository_resolver(resolved_node.install_id)
        if repository is None:
            raise PlaybookExecutionError(
                "GIT_REPOSITORY_MISSING",
                "No repository reference is configured for this install.",
                {"install_id": resolved_node.install_id},
            )

        if permission_context is not None:
            permission_context.require_filesystem_write("repository")
            permission_context.require_operation("git.status")
            permission_context.require_operation("git.rev_parse")
            permission_context.require_operation("git.cat_file")
            permission_context.require_operation("git.add.path")
            permission_context.require_operation("git.commit")
            if push:
                permission_context.require_operation("git.push")
                remote_url = getattr(repository, "remote_url", "")
                if remote_url and ("github.com" in remote_url or "gitlab.com" in remote_url):
                    permission_context.require_egress("github.com", 443)

        repo_root = repository.managed_checkout_root
        validate_repository_reference(repository)

        # Staging isolation check: inspect pre-existing staged files
        status_out = self.git_publisher.git(repo_root, "status", "--porcelain")
        staged_files: list[str] = []
        for line in (status_out or "").splitlines():
            if not line.strip():
                continue
            index_status = line[0]
            fpath = line[3:] if len(line) > 3 else line[2:]
            if index_status in {"M", "A", "D", "R", "C"}:
                staged_files.append(fpath)

        if staged_files:
            raise PlaybookExecutionError(
                "UNCONTROLLED_GIT_STAGING",
                "Pre-existing staged files in index; cannot safely isolate publish mutation.",
                {"staged_files": staged_files},
            )

        target_abs_path = ensure_under(repo_root, relative_path)
        target_abs_path.parent.mkdir(parents=True, exist_ok=True)
        target_abs_path.write_text(markdown_content, encoding="utf-8")

        # Stage ONLY exact target path
        self.git_publisher.git(repo_root, "add", "--", relative_path)

        rendered_checksum = sha256_path(target_abs_path)
        snapshot = input_data.get("snapshot")
        snapshot_checksum = (
            snapshot.snapshot_checksum
            if hasattr(snapshot, "snapshot_checksum")
            else (snapshot.get("snapshot_checksum") if isinstance(snapshot, dict) else rendered_checksum)
        )

        intent_fingerprint = (
            input_data.get("intent_fingerprint")
            or (permission_context.intent_fingerprint if permission_context and hasattr(permission_context, "intent_fingerprint") else "")
            or mutation_input_fingerprint({"path": relative_path, "content": markdown_content})
        )
        mutation_id = input_data.get("mutation_id") or f"mut_{content_revision_id}_{publication_target_id}"

        commit_message = (
            f"publish: {title}\n\n"
            f"Content-Revision: {content_revision_id}\n"
            f"Publication-Target: {publication_target_id}\n"
            f"Publication-Attempt: {publication_attempt_id}\n"
            f"Snapshot-Checksum: {snapshot_checksum}\n"
            f"Mutation-ID: {mutation_id}\n"
            f"Intent-Fingerprint: {intent_fingerprint}\n"
        )

        commit_sha = self.git_publisher.git(repo_root, "commit", "-m", commit_message).strip()
        if not commit_sha or " " in commit_sha:
            commit_sha = self.git_publisher.git(repo_root, "rev-parse", "HEAD").strip()

        if push:
            self.git_publisher.git(repo_root, "push", remote_name, branch)

        evidence = WebsitePublicationEvidence(
            repository_reference_id=repository.id,
            branch=branch,
            base_commit="HEAD~1",
            publication_commit=commit_sha,
            remote_name=remote_name if push else "",
            remote_commit=commit_sha if push else "",
            markdown_relative_path=relative_path,
            media_relative_paths=(),
            rendered_markdown_checksum=rendered_checksum,
            media_checksums={},
            public_url="",
            snapshot_checksum=str(snapshot_checksum),
            revision_binding={
                "content_revision_id": content_revision_id,
                "publication_target_id": publication_target_id,
                "publication_attempt_id": publication_attempt_id,
                "mutation_id": mutation_id,
                "intent_fingerprint": intent_fingerprint,
            },
            verification_status="verified",
            verification_timestamp=datetime.now(UTC).isoformat(),
            mutation_manifest=WebsiteMutationManifest(
                created_paths=(relative_path,),
                modified_paths=(),
                deleted_paths=(),
                original_checksums={},
                resulting_checksums={relative_path: rendered_checksum},
                media_bindings={},
                rendered_markdown_checksum=rendered_checksum,
                snapshot_checksum=str(snapshot_checksum),
            ),
        )
        readback_result = verify_website_publish(
            evidence=evidence,
            repository=repository,
            git_publisher=self.git_publisher,
            check_remote=push,
        )
        if readback_result.state not in {
            WebsitePublishReadbackState.EXPECTED_COMMIT_PRESENT,
            WebsitePublishReadbackState.EXPECTED_COMMIT_AT_HEAD,
            WebsitePublishReadbackState.EXPECTED_COMMIT_REMOTE,
        }:
            raise PlaybookExecutionError(
                "READBACK_FAILED",
                "Readback verification of published website article failed.",
                {"readback": readback_result.to_dict()},
            )

        now_iso = datetime.now(UTC).isoformat()
        receipt = MutationReceipt(
            mutation_id=mutation_id,
            idempotency_key=f"website.article.publish:{publication_target_id}:{content_revision_id}",
            capability_id=WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
            component_id=GIT_WEBSITE_COMPONENT_ID,
            resource_ref=f"git-commit:{commit_sha}",
            applied_at=now_iso,
            result_fingerprint=rendered_checksum,
            metadata={
                "commit_sha": commit_sha,
                "install_id": resolved_node.install_id,
                "path": relative_path,
                "pushed": push,
                "readback_verified": True,
            },
        )

        return NodeResult.success(
            {
                "publication_commit": commit_sha,
                "mutation_receipt": receipt.to_dict(),
                "readback_verified": True,
                "resource_ref": f"git-commit:{commit_sha}",
                "path": relative_path,
            }
        )

    def verify_readback(self, receipt: MutationReceipt, context: ExecutionContext) -> bool:
        if not receipt.resource_ref.startswith("git-commit:"):
            return False
        commit_sha = receipt.resource_ref.split(":", 1)[1]
        install_id = receipt.metadata.get("install_id") or "website-prod-install"
        repository = self.repository_resolver(install_id)
        if repository is None:
            return False
        try:
            repo_root = repository.managed_checkout_root
            res = self.git_publisher.git(repo_root, "cat-file", "-e", commit_sha, check=False)
            return res is not None
        except Exception:
            return False


def website_article_publish_candidate(
    *,
    repository_resolver: RepositoryResolver,
    git_publisher: GitPublisher | None = None,
    remote_name: str = "origin",
) -> MutationHandlerCandidate:
    publisher = git_publisher or GitPublisher()

    def build_handler() -> CapabilityHandler:
        return WebsiteArticlePublishHandler(
            repository_resolver=repository_resolver,
            git_publisher=publisher,
            remote_name=remote_name,
        )

    policy = MutationPolicy(
        requires_approval=True,
        idempotency_required=True,
        readback=ReadbackPolicy.REQUIRED.value,
        compensation=CompensationPolicy.UNAVAILABLE.value,
        recovery=RecoveryPolicy.MANUAL.value,
    )
    guarantees = website_publish_safety_guarantees()
    return MutationHandlerCandidate(
        component_id=GIT_WEBSITE_COMPONENT_ID,
        capability_id=WEBSITE_ARTICLE_PUBLISH_CAPABILITY,
        build_handler=build_handler,
        mutation_policy=policy,
        permission_requirements={
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
        },
        readback_support=dict(guarantees.get("readback") or {}),
        recovery_support={"recovery": guarantees.get("recovery")},
        handler_identity="publication_git_runtime_handlers.WebsiteArticlePublishHandler",
        metadata={"guarantees": guarantees},
    )


def register_and_activate_website_publish(
    handler_registry: CapabilityHandlerRegistry,
    *,
    component: ComponentManifest,
    install: Install | None = None,
    repository_resolver: RepositoryResolver,
    git_publisher: GitPublisher | None = None,
    remote_name: str = "origin",
) -> ProductionMutationActivationResult:
    from publication_git_mutation_admission import website_article_publish_admission

    candidate = website_article_publish_candidate(
        repository_resolver=repository_resolver,
        git_publisher=git_publisher,
        remote_name=remote_name,
    )
    return admit_and_register_mutation(
        candidate=candidate,
        component=component,
        install=install,
        registry=handler_registry,
        admission_evaluator=website_article_publish_admission,
    )


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
    allowed = {"_runtime", "include_changed_paths"}
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


def _permission_context(input_data: dict[str, Any]) -> Any | None:
    runtime = input_data.get("_runtime")
    if not isinstance(runtime, dict):
        return None
    return runtime.get("permission_context")


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
