from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from channels.markdown_website.errors import MarkdownWebsiteError
from channels.markdown_website.git_publisher import GitPublisher, sha256_path
from channels.markdown_website.models import (
    RenderedMarkdown,
    WebsitePublicationEvidence,
    WebsitePublicationSnapshot,
    WebsiteRepositoryReference,
)
from channels.markdown_website.paths import ensure_under, validate_repository_reference
from src.core.runtime.mutation_policies import MutationPolicy
from src.core.runtime.permissions import EffectivePermissionSet

WEBSITE_PUBLISH_RESOURCE_TYPE = "website-article"


class WebsitePublishReadbackState(StrEnum):
    NO_SIDE_EFFECT = "no_side_effect"
    TARGET_ABSENT = "target_absent"
    TARGET_PRESENT_UNCOMMITTED = "target_present_uncommitted"
    EXPECTED_COMMIT_PRESENT = "expected_commit_present"
    EXPECTED_COMMIT_AT_HEAD = "expected_commit_at_head"
    EXPECTED_COMMIT_REMOTE = "expected_commit_remote"
    STATE_CONFLICT = "state_conflict"
    UNKNOWN = "unknown"
    MANUAL_RECOVERY_REQUIRED = "manual_recovery_required"


@dataclass(frozen=True)
class WebsitePublishIdentity:
    logical_id: str
    idempotency_key: str
    target_relative_path: str
    content_item_id: str
    content_revision_id: str
    publication_target_id: str
    snapshot_checksum: str
    rendered_checksum: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_item_id": self.content_item_id,
            "content_revision_id": self.content_revision_id,
            "idempotency_key": self.idempotency_key,
            "logical_id": self.logical_id,
            "metadata": _json_safe(self.metadata),
            "publication_target_id": self.publication_target_id,
            "rendered_checksum": self.rendered_checksum,
            "snapshot_checksum": self.snapshot_checksum,
            "target_relative_path": self.target_relative_path,
        }


@dataclass(frozen=True)
class WebsitePublishReadbackResult:
    state: str
    target_exists: bool
    target_matches: bool
    commit_exists: bool
    commit_at_head: bool
    remote_contains_commit: bool
    manual_recovery_required: bool
    safe_to_retry: bool
    recommended_action: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit_at_head": self.commit_at_head,
            "commit_exists": self.commit_exists,
            "manual_recovery_required": self.manual_recovery_required,
            "metadata": _json_safe(self.metadata),
            "recommended_action": self.recommended_action,
            "remote_contains_commit": self.remote_contains_commit,
            "safe_to_retry": self.safe_to_retry,
            "state": self.state,
            "target_exists": self.target_exists,
            "target_matches": self.target_matches,
        }


def build_website_publish_identity(
    *,
    install_id: str,
    capability_id: str,
    snapshot: WebsitePublicationSnapshot,
    rendered: RenderedMarkdown,
    remote_name: str = "origin",
    push: bool = False,
) -> WebsitePublishIdentity:
    seed = {
        "branch": snapshot.account_config.branch,
        "capability_id": capability_id,
        "content_item_id": snapshot.content_item_id,
        "content_revision_id": snapshot.content_revision_id,
        "install_id": install_id,
        "publication_plan_id": snapshot.publication_plan_id,
        "publication_target_id": snapshot.publication_target_id,
        "push": push,
        "remote_name": remote_name if push else "",
        "repository_reference_id": snapshot.account_config.repository_reference_id,
        "snapshot_checksum": snapshot.publication_snapshot_checksum,
        "target_relative_path": rendered.relative_path,
    }
    logical_id = _sha256_dict(seed)
    idempotency_key = f"website-publish:{logical_id}"
    return WebsitePublishIdentity(
        logical_id=logical_id,
        idempotency_key=idempotency_key,
        target_relative_path=rendered.relative_path,
        content_item_id=snapshot.content_item_id,
        content_revision_id=snapshot.content_revision_id,
        publication_target_id=snapshot.publication_target_id,
        snapshot_checksum=snapshot.publication_snapshot_checksum,
        rendered_checksum=rendered.checksum,
        metadata={"branch": snapshot.account_config.branch, "push": push},
    )


def approved_publish_fingerprint(
    *,
    snapshot: WebsitePublicationSnapshot,
    rendered: RenderedMarkdown,
    effective_policy: MutationPolicy,
    effective_permissions: EffectivePermissionSet | None = None,
    remote_name: str = "origin",
    push: bool = False,
) -> str:
    payload: dict[str, Any] = {
        "branch": snapshot.account_config.branch,
        "content_item_id": snapshot.content_item_id,
        "content_revision_id": snapshot.content_revision_id,
        "frontmatter_profile_id": snapshot.account_config.frontmatter_profile_id,
        "markdown_sha256": rendered.checksum,
        "policy": effective_policy.to_dict(),
        "public_url": rendered.public_url,
        "publication_attempt_id": snapshot.publication_attempt_id,
        "publication_plan_id": snapshot.publication_plan_id,
        "publication_target_id": snapshot.publication_target_id,
        "push": push,
        "remote_name": remote_name if push else "",
        "repository_reference_id": snapshot.account_config.repository_reference_id,
        "snapshot_checksum": snapshot.publication_snapshot_checksum,
        "target_relative_path": rendered.relative_path,
    }
    if effective_permissions is not None:
        payload["permissions"] = effective_permissions.to_dict()["effective"]
    return _sha256_dict(payload)


def verify_website_publish(
    *,
    evidence: WebsitePublicationEvidence,
    repository: WebsiteRepositoryReference,
    git_publisher: GitPublisher | None = None,
    check_remote: bool = True,
) -> WebsitePublishReadbackResult:
    publisher = git_publisher or GitPublisher()
    try:
        validate_repository_reference(repository)
        repo_root = repository.managed_checkout_root.resolve()
        target_path = ensure_under(repo_root, evidence.markdown_relative_path)
        target_exists = target_path.exists()
        target_matches = target_exists and sha256_path(target_path) == evidence.rendered_markdown_checksum
        expected_files = (evidence.markdown_relative_path, *evidence.media_relative_paths)
        commit_sha = evidence.publication_commit
        if target_exists and not target_matches:
            return _result(
                WebsitePublishReadbackState.STATE_CONFLICT,
                target_exists=target_exists,
                target_matches=False,
                metadata={"reason": "target_content_mismatch"},
            )
        commit_exists = _commit_exists(publisher, repo_root, commit_sha)
        if commit_exists:
            commit_files = tuple(
                item for item in publisher.git(repo_root, "show", "--name-only", "--format=", commit_sha).splitlines()
            )
            expected_set = set(expected_files)
            if set(commit_files) != expected_set:
                return _result(
                    WebsitePublishReadbackState.STATE_CONFLICT,
                    target_exists=target_exists,
                    target_matches=target_matches,
                    commit_exists=True,
                    metadata={
                        "committed_files": sorted(commit_files),
                        "expected_files": sorted(expected_files),
                        "reason": "commit_file_set_mismatch",
                    },
                )
            message = publisher.git(repo_root, "show", "-s", "--format=%B", commit_sha)
            provenance = _commit_matches_provenance(message or "", evidence)
            if not provenance:
                return _result(
                    WebsitePublishReadbackState.STATE_CONFLICT,
                    target_exists=target_exists,
                    target_matches=target_matches,
                    commit_exists=True,
                    metadata={"reason": "commit_provenance_mismatch"},
                )
            commit_at_head = publisher.git(repo_root, "rev-parse", "HEAD", check=False) == commit_sha
            remote_contains = False
            if check_remote and evidence.remote_name and evidence.branch:
                remote_contains = _remote_contains_commit(
                    publisher,
                    repo_root,
                    evidence.remote_name,
                    evidence.branch,
                    commit_sha,
                )
            if remote_contains:
                return _result(
                    WebsitePublishReadbackState.EXPECTED_COMMIT_REMOTE,
                    target_exists=target_exists,
                    target_matches=target_matches,
                    commit_exists=True,
                    commit_at_head=commit_at_head,
                    remote_contains_commit=True,
                    metadata={"commit_sha": commit_sha},
                )
            if commit_at_head:
                return _result(
                    WebsitePublishReadbackState.EXPECTED_COMMIT_AT_HEAD,
                    target_exists=target_exists,
                    target_matches=target_matches,
                    commit_exists=True,
                    commit_at_head=True,
                    metadata={"commit_sha": commit_sha},
                )
            return _result(
                WebsitePublishReadbackState.EXPECTED_COMMIT_PRESENT,
                target_exists=target_exists,
                target_matches=target_matches,
                commit_exists=True,
                metadata={"commit_sha": commit_sha},
            )
        if target_exists and target_matches:
            return _result(
                WebsitePublishReadbackState.TARGET_PRESENT_UNCOMMITTED,
                target_exists=True,
                target_matches=True,
                safe_to_retry=False,
                manual_recovery_required=True,
                recommended_action="manual_recovery_required",
                metadata={"reason": "file_written_without_expected_commit"},
            )
        if target_exists:
            return _result(WebsitePublishReadbackState.STATE_CONFLICT, target_exists=True, metadata={})
        state = (
            WebsitePublishReadbackState.NO_SIDE_EFFECT if not commit_sha else WebsitePublishReadbackState.TARGET_ABSENT
        )
        return _result(
            state,
            safe_to_retry=True,
            recommended_action="retry_from_start",
            metadata={"reason": "no_target_or_expected_commit"},
        )
    except MarkdownWebsiteError as exc:
        return _result(
            WebsitePublishReadbackState.MANUAL_RECOVERY_REQUIRED,
            manual_recovery_required=True,
            recommended_action="manual_recovery_required",
            metadata={"error_code": exc.code},
        )
    except Exception as exc:
        return _result(
            WebsitePublishReadbackState.UNKNOWN,
            manual_recovery_required=True,
            recommended_action="manual_recovery_required",
            metadata={"error": type(exc).__name__},
        )


def inspect_website_publish_recovery(
    *,
    evidence: WebsitePublicationEvidence,
    repository: WebsiteRepositoryReference,
    git_publisher: GitPublisher | None = None,
) -> dict[str, Any]:
    readback = verify_website_publish(
        evidence=evidence,
        repository=repository,
        git_publisher=git_publisher,
        check_remote=True,
    )
    return {
        "journal_state": "applying",
        "mutation_id": evidence.revision_binding.get("mutation_id", ""),
        "readback": readback.to_dict(),
        "recommended_safe_action": readback.recommended_action,
        "target_relative_path": evidence.markdown_relative_path,
    }


def website_publish_safety_guarantees() -> dict[str, Any]:
    return {
        "approved_content_fingerprint": True,
        "commit_provenance": True,
        "compensation": "unavailable",
        "exact_target_staging": True,
        "idempotency": True,
        "manual_recovery_state": True,
        "readback": {
            "commit": True,
            "file": True,
            "remote": True,
        },
        "recovery": "manual",
    }


def _commit_exists(publisher: GitPublisher, repo_root: Any, commit_sha: str) -> bool:
    if not commit_sha:
        return False
    return publisher.git(repo_root, "cat-file", "-e", f"{commit_sha}^{{commit}}", check=False) is not None


def _remote_contains_commit(
    publisher: GitPublisher,
    repo_root: Any,
    remote_name: str,
    branch: str,
    commit_sha: str,
) -> bool:
    output = publisher.git(repo_root, "ls-remote", remote_name, f"refs/heads/{branch}", check=False)
    if not output:
        return False
    remote_sha = output.split()[0]
    if remote_sha == commit_sha:
        return True
    merge_base = publisher.git(repo_root, "merge-base", commit_sha, remote_sha, check=False)
    return merge_base == commit_sha


def _commit_matches_provenance(message: str, evidence: WebsitePublicationEvidence) -> bool:
    expected = {
        "Content-Revision": evidence.revision_binding.get("content_revision_id", ""),
        "Publication-Target": evidence.revision_binding.get("publication_target_id", ""),
        "Publication-Attempt": evidence.revision_binding.get("publication_attempt_id", ""),
        "Snapshot-Checksum": evidence.snapshot_checksum,
    }
    for key, value in expected.items():
        if value and f"{key}: {value}" not in message:
            return False
    mutation_id = evidence.revision_binding.get("mutation_id", "")
    if mutation_id and f"Mutation-ID: {mutation_id}" not in message:
        return False
    intent_fingerprint = evidence.revision_binding.get("intent_fingerprint", "")
    if intent_fingerprint and f"Intent-Fingerprint: {intent_fingerprint}" not in message:
        return False
    return True


def _result(
    state: WebsitePublishReadbackState,
    *,
    target_exists: bool = False,
    target_matches: bool = False,
    commit_exists: bool = False,
    commit_at_head: bool = False,
    remote_contains_commit: bool = False,
    manual_recovery_required: bool | None = None,
    safe_to_retry: bool = False,
    recommended_action: str = "",
    metadata: dict[str, Any] | None = None,
) -> WebsitePublishReadbackResult:
    manual = (
        state
        in {
            WebsitePublishReadbackState.STATE_CONFLICT,
            WebsitePublishReadbackState.UNKNOWN,
            WebsitePublishReadbackState.MANUAL_RECOVERY_REQUIRED,
        }
        if manual_recovery_required is None
        else manual_recovery_required
    )
    action = recommended_action or ("manual_recovery_required" if manual else "mark_applied")
    return WebsitePublishReadbackResult(
        state=state.value,
        target_exists=target_exists,
        target_matches=target_matches,
        commit_exists=commit_exists,
        commit_at_head=commit_at_head,
        remote_contains_commit=remote_contains_commit,
        manual_recovery_required=manual,
        safe_to_retry=safe_to_retry,
        recommended_action=action,
        metadata=_json_safe(metadata or {}),
    )


def _sha256_dict(payload: dict[str, Any]) -> str:
    encoded = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True))
