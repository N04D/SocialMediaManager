from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from channels.markdown_website.errors import MarkdownWebsiteGitError
from channels.markdown_website.git_publisher import GitIdentity, GitPublisher, revision_binding
from channels.markdown_website.models import (
    MarkdownWebsiteAccountConfig,
    MarkdownWebsiteGitPublishResult,
    WebsiteMutationManifest,
    WebsitePublicationEvidence,
    WebsitePublicationSnapshot,
    WebsiteRepositoryReference,
    WebsiteVariant,
)
from channels.markdown_website.renderer import MarkdownRenderer
from publication_git_publish_safety import (
    WebsitePublishReadbackState,
    verify_website_publish,
)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def make_fixture(tmp_path: Path) -> tuple[Path, WebsiteRepositoryReference, WebsitePublicationSnapshot]:
    repo = tmp_path / "site-repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("fixture site\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "init")
    account = MarkdownWebsiteAccountConfig(
        id="acct-1",
        workspace_id="workspace-1",
        account_id="site-1",
        display_name="Fixture Site",
        repository_reference_id="repo-1",
        branch="main",
        content_root="articles",
        media_root="static/media",
        public_base_url="https://example.test",
        public_url_template="https://example.test/articles/{slug}",
        frontmatter_profile_id="generic_yaml",
    )
    reference = WebsiteRepositoryReference(
        id="repo-1",
        workspace_id="workspace-1",
        display_name="Fixture repo",
        managed_checkout_root=repo,
        allowed_content_roots=("articles",),
        allowed_media_roots=("static/media",),
        allowed_branches=("main",),
        allowed_remote_names=("origin",),
    )
    snapshot = WebsitePublicationSnapshot(
        content_item_id="content-1",
        content_revision_id="revision-1",
        channel_variant_id="variant-website",
        publication_plan_id="plan-1",
        publication_target_id="target-website",
        publication_attempt_id="attempt-1",
        publication_snapshot_checksum="snapshotabc",
        website_profile_id="generic_yaml",
        website_profile_version="1.0",
        account_config=account,
        variant=WebsiteVariant(
            title="A Deterministic Article",
            markdown_body="# Intro\n\nBody",
            summary="Short summary",
            description="SEO description",
            tags=("analytics",),
            published_at=datetime(2026, 7, 27, 8, 0, tzinfo=UTC),
            updated_at=datetime(2026, 7, 27, 8, 0, tzinfo=UTC),
        ),
    )
    return repo, reference, snapshot


def minimal_evidence(
    snapshot: WebsitePublicationSnapshot,
    relative_path: str,
    checksum: str,
    *,
    commit_sha: str = "",
    remote_name: str = "",
) -> WebsitePublicationEvidence:
    return WebsitePublicationEvidence(
        repository_reference_id=snapshot.account_config.repository_reference_id,
        branch=snapshot.account_config.branch,
        base_commit="",
        publication_commit=commit_sha,
        remote_name=remote_name,
        remote_commit="",
        markdown_relative_path=relative_path,
        media_relative_paths=(),
        rendered_markdown_checksum=checksum,
        media_checksums={},
        public_url="https://example.test/articles/a-deterministic-article",
        snapshot_checksum=snapshot.publication_snapshot_checksum,
        revision_binding=revision_binding(snapshot),
        verification_status="",
        verification_timestamp="",
        mutation_manifest=WebsiteMutationManifest(
            created_paths=(relative_path,),
            modified_paths=(),
            deleted_paths=(),
            original_checksums={relative_path: ""},
            resulting_checksums={relative_path: checksum},
            media_bindings={},
            rendered_markdown_checksum=checksum,
            snapshot_checksum=snapshot.publication_snapshot_checksum,
        ),
        publish_result=MarkdownWebsiteGitPublishResult(
            repository_state_before="existing",
            branch=snapshot.account_config.branch,
            generated_files=(relative_path,),
            staged_files=(),
            commit_created=bool(commit_sha),
            commit_sha=commit_sha,
            parent_commit_sha="",
            push_requested=bool(remote_name),
            push_performed=False,
            verification_ready=False,
        ),
    )


def test_phase54_readback_classifies_no_side_effect(tmp_path: Path) -> None:
    _, reference, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)
    evidence = minimal_evidence(snapshot, rendered.relative_path, rendered.checksum)

    result = verify_website_publish(evidence=evidence, repository=reference)

    assert result.state == WebsitePublishReadbackState.NO_SIDE_EFFECT.value
    assert result.safe_to_retry is True
    assert result.recommended_action == "retry_from_start"


def test_phase54_readback_classifies_file_only_state(tmp_path: Path) -> None:
    repo, reference, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)
    target = repo / rendered.relative_path
    target.parent.mkdir(parents=True)
    target.write_bytes(rendered.markdown_bytes)
    evidence = minimal_evidence(snapshot, rendered.relative_path, rendered.checksum)

    result = verify_website_publish(evidence=evidence, repository=reference)

    assert result.state == WebsitePublishReadbackState.TARGET_PRESENT_UNCOMMITTED.value
    assert result.manual_recovery_required is True
    assert result.safe_to_retry is False


def test_phase54_readback_classifies_local_commit(tmp_path: Path) -> None:
    _, reference, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)
    evidence = GitPublisher().publish(
        snapshot,
        reference,
        rendered,
        identity=GitIdentity("Publisher", "publisher@example.test"),
    )

    result = verify_website_publish(evidence=evidence, repository=reference)

    assert result.state == WebsitePublishReadbackState.EXPECTED_COMMIT_AT_HEAD.value
    assert result.commit_exists is True
    assert result.target_matches is True


def test_phase54_readback_classifies_remote_commit_with_local_bare_remote(tmp_path: Path) -> None:
    repo, reference, snapshot = make_fixture(tmp_path)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, text=True, capture_output=True)
    git(repo, "remote", "add", "origin", str(bare))
    rendered = MarkdownRenderer().render(snapshot)

    evidence = GitPublisher().publish(
        snapshot,
        reference,
        rendered,
        identity=GitIdentity("Publisher", "publisher@example.test"),
        push=True,
    )
    result = verify_website_publish(evidence=evidence, repository=reference)

    assert result.state == WebsitePublishReadbackState.EXPECTED_COMMIT_REMOTE.value
    assert result.remote_contains_commit is True


def test_phase54_readback_blocks_content_mismatch(tmp_path: Path) -> None:
    repo, reference, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)
    evidence = GitPublisher().publish(
        snapshot,
        reference,
        rendered,
        identity=GitIdentity("Publisher", "publisher@example.test"),
    )
    (repo / rendered.relative_path).write_text("manual edit\n", encoding="utf-8")

    result = verify_website_publish(evidence=evidence, repository=reference)

    assert result.state == WebsitePublishReadbackState.STATE_CONFLICT.value
    assert result.manual_recovery_required is True


def test_phase54_exact_staging_blocks_unrelated_staged_files(tmp_path: Path) -> None:
    repo, reference, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)
    (repo / "already-staged.txt").write_text("do not include\n", encoding="utf-8")
    git(repo, "add", "already-staged.txt")

    with pytest.raises(MarkdownWebsiteGitError) as exc:
        GitPublisher().publish(
            snapshot,
            reference,
            rendered,
            identity=GitIdentity("Publisher", "publisher@example.test"),
        )

    assert exc.value.code == "markdown_website.git.staged_set_mismatch"
    staged = git(repo, "diff", "--cached", "--name-only")
    assert "already-staged.txt" in staged


def test_phase54_exact_staging_preserves_unrelated_unstaged_files(tmp_path: Path) -> None:
    repo, reference, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)
    (repo / "README.md").write_text("fixture site changed by user\n", encoding="utf-8")
    draft = repo / "content" / "drafts" / "example.md"
    draft.parent.mkdir(parents=True)
    draft.write_text("user draft\n", encoding="utf-8")

    evidence = GitPublisher().publish(
        snapshot,
        reference,
        rendered,
        identity=GitIdentity("Publisher", "publisher@example.test"),
    )
    committed_files = git(repo, "show", "--name-only", "--format=", evidence.publication_commit)

    assert rendered.relative_path in committed_files
    assert "README.md" not in committed_files
    assert "content/drafts/example.md" not in committed_files
    assert draft.read_text(encoding="utf-8") == "user draft\n"
