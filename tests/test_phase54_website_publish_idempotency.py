from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from channels.markdown_website.git_publisher import GitIdentity, GitPublisher
from channels.markdown_website.models import (
    MarkdownWebsiteAccountConfig,
    WebsitePublicationSnapshot,
    WebsiteRepositoryReference,
    WebsiteVariant,
)
from channels.markdown_website.renderer import MarkdownRenderer
from publication_git_publish_safety import (
    approved_publish_fingerprint,
    build_website_publish_identity,
)
from src.core.runtime.mutation_policies import (
    CompensationPolicy,
    MutationPolicy,
    ReadbackPolicy,
    RecoveryPolicy,
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


def mutation_policy() -> MutationPolicy:
    return MutationPolicy(
        requires_approval=True,
        idempotency_required=True,
        readback=ReadbackPolicy.REQUIRED.value,
        compensation=CompensationPolicy.UNAVAILABLE.value,
        recovery=RecoveryPolicy.MANUAL.value,
    )


def test_phase54_logical_identity_is_deterministic(tmp_path: Path) -> None:
    _, _, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)

    first = build_website_publish_identity(
        install_id="website-local",
        capability_id="website.article.publish",
        snapshot=snapshot,
        rendered=rendered,
        push=True,
    )
    second = build_website_publish_identity(
        install_id="website-local",
        capability_id="website.article.publish",
        snapshot=snapshot,
        rendered=rendered,
        push=True,
    )

    assert first == second
    assert first.idempotency_key.startswith("website-publish:")
    assert first.target_relative_path == rendered.relative_path


def test_phase54_new_revision_changes_identity(tmp_path: Path) -> None:
    _, _, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)
    changed = snapshot.__class__(**{**snapshot.__dict__, "content_revision_id": "revision-2"})
    changed_rendered = MarkdownRenderer().render(changed)

    first = build_website_publish_identity(
        install_id="website-local",
        capability_id="website.article.publish",
        snapshot=snapshot,
        rendered=rendered,
    )
    second = build_website_publish_identity(
        install_id="website-local",
        capability_id="website.article.publish",
        snapshot=changed,
        rendered=changed_rendered,
    )

    assert first.idempotency_key != second.idempotency_key


def test_phase54_approved_fingerprint_binds_content_policy_and_target(tmp_path: Path) -> None:
    _, _, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)
    policy = mutation_policy()

    original = approved_publish_fingerprint(
        snapshot=snapshot,
        rendered=rendered,
        effective_policy=policy,
        push=True,
    )
    changed_policy = MutationPolicy(
        requires_approval=True,
        idempotency_required=True,
        readback=ReadbackPolicy.REQUIRED.value,
        compensation=CompensationPolicy.UNAVAILABLE.value,
        recovery=RecoveryPolicy.UNRECOVERABLE.value,
    )
    policy_changed = approved_publish_fingerprint(
        snapshot=snapshot,
        rendered=rendered,
        effective_policy=changed_policy,
        push=True,
    )
    target_changed_snapshot = snapshot.__class__(
        **{
            **snapshot.__dict__,
            "account_config": snapshot.account_config.__class__(
                **{**snapshot.account_config.__dict__, "branch": "release"}
            ),
        }
    )
    target_changed = approved_publish_fingerprint(
        snapshot=target_changed_snapshot,
        rendered=rendered,
        effective_policy=policy,
        push=True,
    )

    assert original != policy_changed
    assert original != target_changed


def test_phase54_publish_commit_carries_mutation_provenance(tmp_path: Path) -> None:
    repo, reference, snapshot = make_fixture(tmp_path)
    rendered = MarkdownRenderer().render(snapshot)

    evidence = GitPublisher().publish(
        snapshot,
        reference,
        rendered,
        identity=GitIdentity("Publisher", "publisher@example.test"),
        mutation_id="mutation_phase54",
        intent_fingerprint="f" * 64,
    )
    message = git(repo, "show", "-s", "--format=%B", evidence.publication_commit)

    assert "Mutation-ID: mutation_phase54" in message
    assert f"Intent-Fingerprint: {'f' * 64}" in message
    assert evidence.revision_binding["mutation_id"] == "mutation_phase54"
    assert evidence.revision_binding["intent_fingerprint"] == "f" * 64
