from __future__ import annotations

import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

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
from publication_git_mutation_admission import website_article_publish_admission
from publication_git_publish_safety import (
    WebsitePublishReadbackState,
    inspect_website_publish_recovery,
    verify_website_publish,
)
from publication_git_runtime_handlers import GIT_WEBSITE_COMPONENT_ID, register_git_runtime_handlers
from runtime_foundation_mappings import phase41_component_manifests, phase41_sample_installs
from src.core.runtime import CapabilityHandlerRegistry
from src.core.runtime.errors import PlaybookExecutionError


class BrokenReadbackGitPublisher(GitPublisher):
    def git(self, cwd: Path, *args: str, check: bool = True) -> str | None:
        del cwd, args, check
        raise RuntimeError("simulated readback failure")


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
) -> WebsitePublicationEvidence:
    return WebsitePublicationEvidence(
        repository_reference_id=snapshot.account_config.repository_reference_id,
        branch=snapshot.account_config.branch,
        base_commit="",
        publication_commit=commit_sha,
        remote_name="",
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
            push_requested=False,
            push_performed=False,
            verification_ready=False,
        ),
    )


def _git_component():
    return next(item for item in phase41_component_manifests() if item.component_id == GIT_WEBSITE_COMPONENT_ID)


def _git_install():
    return next(item for item in phase41_sample_installs() if item.install_id == "github-don-website")


def test_phase54_crash_before_file_write_is_safe_retry_state(tmp_path: Path) -> None:
    _, reference, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)
    evidence = minimal_evidence(snapshot, rendered.relative_path, rendered.checksum)

    inspection = inspect_website_publish_recovery(evidence=evidence, repository=reference)

    assert inspection["readback"]["state"] == WebsitePublishReadbackState.NO_SIDE_EFFECT.value
    assert inspection["recommended_safe_action"] == "retry_from_start"


def test_phase54_crash_after_commit_before_push_does_not_create_second_commit(tmp_path: Path) -> None:
    repo, reference, snapshot = make_fixture(tmp_path)
    subprocess.run(["git", "init", "--bare", str(tmp_path / "remote.git")], check=True, text=True, capture_output=True)
    git(repo, "remote", "add", "origin", str(tmp_path / "remote.git"))
    rendered = MarkdownRenderer().render(snapshot)

    evidence = GitPublisher().publish(
        snapshot,
        reference,
        rendered,
        identity=GitIdentity("Publisher", "publisher@example.test"),
        push=False,
        mutation_id="mutation_phase54",
    )
    commits_before = git(repo, "rev-list", "--count", "HEAD")
    stale_evidence = replace(evidence, remote_name="origin")

    readback = verify_website_publish(evidence=stale_evidence, repository=reference)
    commits_after = git(repo, "rev-list", "--count", "HEAD")

    assert readback.state == WebsitePublishReadbackState.EXPECTED_COMMIT_AT_HEAD.value
    assert commits_after == commits_before


def test_phase54_crash_after_push_before_journal_update_marks_applied_by_readback(tmp_path: Path) -> None:
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
        mutation_id="mutation_phase54",
    )
    inspection = inspect_website_publish_recovery(evidence=evidence, repository=reference)

    assert inspection["readback"]["state"] == WebsitePublishReadbackState.EXPECTED_COMMIT_REMOTE.value
    assert inspection["recommended_safe_action"] == "mark_applied"


def test_phase54_unknown_readback_requires_manual_recovery_not_blind_retry(tmp_path: Path) -> None:
    _, reference, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)
    evidence = minimal_evidence(snapshot, rendered.relative_path, rendered.checksum, commit_sha="abc123")

    readback = verify_website_publish(
        evidence=evidence,
        repository=reference,
        git_publisher=BrokenReadbackGitPublisher(),
    )

    assert readback.state == WebsitePublishReadbackState.UNKNOWN.value
    assert readback.manual_recovery_required is True
    assert readback.safe_to_retry is False
    assert readback.recommended_action == "manual_recovery_required"


def test_phase54_downstream_failure_keeps_publication_without_compensation(tmp_path: Path) -> None:
    repo, reference, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)
    evidence = GitPublisher().publish(
        snapshot,
        reference,
        rendered,
        identity=GitIdentity("Publisher", "publisher@example.test"),
    )
    head_before_failure = git(repo, "rev-parse", "HEAD")

    readback = verify_website_publish(evidence=evidence, repository=reference)

    assert readback.state == WebsitePublishReadbackState.EXPECTED_COMMIT_AT_HEAD.value
    assert git(repo, "rev-parse", "HEAD") == head_before_failure
    assert (repo / rendered.relative_path).exists()


def test_phase54_admission_resolves_safety_blockers_but_handler_is_not_registered() -> None:
    result = website_article_publish_admission(component=_git_component(), install=_git_install())

    assert "BLOCKED_IDEMPOTENCY" not in result.reasons
    assert "BLOCKED_READBACK" not in result.reasons
    assert "BLOCKED_RECOVERY" not in result.reasons
    assert "BLOCKED_HANDLER_NOT_REGISTERED" not in result.reasons
    assert result.metadata["guarantees"]["recovery"] == "manual"


def test_phase54_publish_handler_still_not_publicly_registered() -> None:
    registry = CapabilityHandlerRegistry()
    register_git_runtime_handlers(registry, repositories_by_install_id={})

    try:
        registry.resolve(GIT_WEBSITE_COMPONENT_ID, "website.article.publish")
    except PlaybookExecutionError as exc:
        assert exc.code == "HANDLER_NOT_FOUND"
    else:  # pragma: no cover
        raise AssertionError("website.article.publish must remain unregistered until admission is complete")
