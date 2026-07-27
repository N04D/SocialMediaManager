"""Safe Git worktree publisher for Markdown Website."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import MarkdownWebsiteGitError
from .models import (
    RenderedMarkdown,
    WebsiteMutationManifest,
    WebsitePublicationEvidence,
    WebsitePublicationSnapshot,
    WebsiteRepositoryReference,
)
from .paths import assert_allowed_roots, ensure_under, validate_repository_reference


@dataclass(frozen=True)
class GitIdentity:
    name: str
    email: str


class GitPublisher:
    def __init__(self, *, git_executable: str = "git", timeout_seconds: int = 20) -> None:
        self.git_executable = git_executable
        self.timeout_seconds = timeout_seconds

    def publish(
        self,
        snapshot: WebsitePublicationSnapshot,
        repository: WebsiteRepositoryReference,
        rendered: RenderedMarkdown,
        *,
        identity: GitIdentity,
        remote_name: str = "origin",
        media_paths: tuple[str, ...] = (),
        push: bool = False,
    ) -> WebsitePublicationEvidence:
        self.validate_preflight(snapshot, repository, remote_name=remote_name, push=push)
        repo_root = repository.managed_checkout_root.resolve()
        base_commit = self.git(repo_root, "rev-parse", "HEAD")
        target_path = ensure_under(repo_root, rendered.relative_path)
        relative_paths = (rendered.relative_path, *media_paths)
        conflict = self.changed_paths(repo_root, relative_paths)
        if conflict:
            raise MarkdownWebsiteGitError(
                "markdown_website.git.conflicting_user_change", "Target path has user changes."
            )
        original_checksums = {rendered.relative_path: sha256_path(target_path) if target_path.exists() else ""}
        write_atomic(target_path, rendered.markdown_bytes)
        resulting_checksums = {rendered.relative_path: sha256_path(target_path)}
        if resulting_checksums[rendered.relative_path] != rendered.checksum:
            raise MarkdownWebsiteGitError("markdown_website.git.checksum", "Rendered Markdown checksum mismatch.")
        manifest = WebsiteMutationManifest(
            created_paths=tuple(path for path in relative_paths if not original_checksums.get(path)),
            modified_paths=tuple(path for path in relative_paths if original_checksums.get(path)),
            deleted_paths=(),
            original_checksums=original_checksums,
            resulting_checksums=resulting_checksums,
            media_bindings={},
            rendered_markdown_checksum=rendered.checksum,
            snapshot_checksum=snapshot.publication_snapshot_checksum,
        )
        self.git(repo_root, "add", "--", *relative_paths)
        message = commit_message(snapshot.variant.title, snapshot)
        self.git(
            repo_root,
            "-c",
            f"user.name={identity.name}",
            "-c",
            f"user.email={identity.email}",
            "commit",
            "-m",
            message,
            "--",
            *relative_paths,
        )
        publication_commit = self.git(repo_root, "rev-parse", "HEAD")
        remote_commit = ""
        verification_status = "mutation_verified"
        if push:
            self.verify_fast_forward(repo_root, remote_name, snapshot.account_config.branch, base_commit)
            self.git(repo_root, "push", remote_name, f"HEAD:{snapshot.account_config.branch}")
            remote_commit = self.git(repo_root, "rev-parse", "HEAD")
            verification_status = "remote_acknowledged"
        return WebsitePublicationEvidence(
            repository_reference_id=repository.id,
            branch=snapshot.account_config.branch,
            base_commit=base_commit,
            publication_commit=publication_commit,
            remote_name=remote_name if push else "",
            remote_commit=remote_commit,
            markdown_relative_path=rendered.relative_path,
            media_relative_paths=media_paths,
            rendered_markdown_checksum=rendered.checksum,
            media_checksums={},
            public_url=rendered.public_url,
            snapshot_checksum=snapshot.publication_snapshot_checksum,
            revision_binding=revision_binding(snapshot),
            verification_status=verification_status,
            verification_timestamp="",
            mutation_manifest=manifest,
        )

    def validate_preflight(
        self,
        snapshot: WebsitePublicationSnapshot,
        repository: WebsiteRepositoryReference,
        *,
        remote_name: str,
        push: bool,
    ) -> None:
        validate_repository_reference(repository)
        if snapshot.account_config.branch not in repository.allowed_branches:
            raise MarkdownWebsiteGitError("markdown_website.git.branch_not_allowed", "Branch is not allowlisted.")
        assert_allowed_roots(snapshot.account_config.content_root, repository.allowed_content_roots, kind="content")
        assert_allowed_roots(snapshot.account_config.media_root, repository.allowed_media_roots, kind="media")
        if push and remote_name not in repository.allowed_remote_names:
            raise MarkdownWebsiteGitError("markdown_website.git.remote_not_allowed", "Remote is not allowlisted.")
        status = self.git(repository.managed_checkout_root, "status", "--porcelain")
        if self.git(repository.managed_checkout_root, "status", "--porcelain=v2", check=False) is None:
            raise MarkdownWebsiteGitError("markdown_website.git.status", "Could not read worktree status.")
        if "rebase-merge" in status or "MERGE_HEAD" in status:
            raise MarkdownWebsiteGitError(
                "markdown_website.git.conflict_state", "Repository has an active conflict state."
            )

    def changed_paths(self, repo_root: Path, paths: tuple[str, ...]) -> tuple[str, ...]:
        if not paths:
            return ()
        output = self.git(repo_root, "status", "--porcelain", "--", *paths)
        changed = []
        for line in output.splitlines():
            if line.strip():
                changed.append(line[3:] if len(line) > 3 else line)
        return tuple(changed)

    def verify_fast_forward(self, repo_root: Path, remote: str, branch: str, base_commit: str) -> None:
        self.git(repo_root, "fetch", remote, branch, check=False)
        upstream = self.git(repo_root, "rev-parse", f"{remote}/{branch}", check=False)
        if upstream is None:
            return
        merge_base = self.git(repo_root, "merge-base", "HEAD", f"{remote}/{branch}")
        if merge_base != upstream and upstream != base_commit:
            raise MarkdownWebsiteGitError("markdown_website.git.remote_diverged", "Remote branch diverged.")

    def git(self, cwd: Path, *args: str, check: bool = True) -> str | None:
        command = [self.git_executable, *args]
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(cwd)}
        result = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            shell=False,
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if result.returncode and check:
            raise MarkdownWebsiteGitError(
                "markdown_website.git.failed", redact_git_output(result.stderr or result.stdout)
            )
        if result.returncode:
            return None
        return result.stdout.strip()


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def commit_message(title: str, snapshot: WebsitePublicationSnapshot) -> str:
    safe_title = " ".join(title.split())[:72]
    return (
        f"publish: {safe_title}\n\n"
        f"Content-Revision: {snapshot.content_revision_id}\n"
        f"Publication-Target: {snapshot.publication_target_id}\n"
        f"Publication-Attempt: {snapshot.publication_attempt_id}\n"
        f"Snapshot-Checksum: {snapshot.publication_snapshot_checksum}"
    )


def revision_binding(snapshot: WebsitePublicationSnapshot) -> dict[str, str]:
    return {
        "content_item_id": snapshot.content_item_id,
        "content_revision_id": snapshot.content_revision_id,
        "channel_variant_id": snapshot.channel_variant_id,
        "publication_plan_id": snapshot.publication_plan_id,
        "publication_target_id": snapshot.publication_target_id,
        "publication_attempt_id": snapshot.publication_attempt_id,
        "publication_snapshot_checksum": snapshot.publication_snapshot_checksum,
    }


def redact_git_output(value: str) -> str:
    value = value.replace(str(Path.home()), "<home>")
    return value[:500]
