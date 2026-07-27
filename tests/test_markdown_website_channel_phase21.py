from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from channels.markdown_website import create_plugin
from channels.markdown_website.contracts import (
    CHANNEL_FAMILY_OWNED_PUBLICATION,
    MARKDOWN_WEBSITE_PLUGIN_VERSION,
    PLUGIN_ID,
)
from channels.markdown_website.errors import (
    MarkdownWebsiteGitError,
    MarkdownWebsitePathError,
    MarkdownWebsiteRenderError,
    MarkdownWebsiteVerificationError,
)
from channels.markdown_website.git_publisher import GitIdentity, GitPublisher
from channels.markdown_website.links import build_utm_link
from channels.markdown_website.media import MaterializedMedia, copy_materialized_media, website_media_filename
from channels.markdown_website.models import (
    MarkdownWebsiteAccountConfig,
    WebsiteMediaReference,
    WebsitePublicationSnapshot,
    WebsiteRepositoryReference,
    WebsiteVariant,
)
from channels.markdown_website.paths import ensure_under, render_template
from channels.markdown_website.profiles import get_profile, list_profiles
from channels.markdown_website.reconciliation import MarkdownWebsiteReconciliationService
from channels.markdown_website.renderer import MarkdownRenderer, resolve_public_url, slugify
from channels.markdown_website.slug import validate_slug
from channels.markdown_website.verification import HttpResponse, WebsitePublicationVerifier
from plugin_sdk import ChannelHealthRequest, PluginRegistrationContext


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


class MarkdownWebsitePhase21Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "site-repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        (self.repo / "README.md").write_text("fixture site\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "init")
        self.account = MarkdownWebsiteAccountConfig(
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
        self.reference = WebsiteRepositoryReference(
            id="repo-1",
            workspace_id="workspace-1",
            display_name="Fixture repo",
            managed_checkout_root=self.repo,
            allowed_content_roots=("articles",),
            allowed_media_roots=("static/media",),
            allowed_branches=("main",),
        )
        self.snapshot = WebsitePublicationSnapshot(
            content_item_id="content-1",
            content_revision_id="revision-1",
            channel_variant_id="variant-website",
            publication_plan_id="plan-1",
            publication_target_id="target-website",
            publication_attempt_id="attempt-1",
            publication_snapshot_checksum="snapshotabc",
            website_profile_id="generic_yaml",
            website_profile_version="1.0",
            account_config=self.account,
            variant=WebsiteVariant(
                title="A Deterministic Article",
                markdown_body="# Intro\n\nBody with a [CTA](https://example.test/signup).",
                summary="Short summary",
                description="SEO description",
                tags=("analytics", "owned"),
                published_at=datetime(2026, 7, 27, 8, 0, tzinfo=UTC),
                updated_at=datetime(2026, 7, 27, 8, 0, tzinfo=UTC),
            ),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_plugin_identity_registration_and_health(self) -> None:
        plugin = create_plugin()
        self.assertEqual(plugin.manifest.id, PLUGIN_ID)
        self.assertEqual(plugin.manifest.version, MARKDOWN_WEBSITE_PLUGIN_VERSION)
        context = PluginRegistrationContext(PLUGIN_ID)
        plugin.register(context)
        self.assertIn(PLUGIN_ID, context.runtime_factories)
        health = asyncio.run(plugin.create_runtime(None).health_check(ChannelHealthRequest()))  # type: ignore[arg-type]
        self.assertEqual(health.capabilities["channel_family"], CHANNEL_FAMILY_OWNED_PUBLICATION)

    def test_frontmatter_profiles_are_versioned(self) -> None:
        ids = {profile.id for profile in list_profiles()}
        self.assertGreaterEqual(ids, {"generic_yaml", "hugo", "jekyll", "astro", "eleventy", "next_mdx"})
        self.assertEqual(get_profile("hugo").version, "1.0")

    def test_deterministic_rendering_and_revision_binding(self) -> None:
        rendered_a = MarkdownRenderer().render(self.snapshot)
        rendered_b = MarkdownRenderer().render(self.snapshot)
        self.assertEqual(rendered_a.markdown_bytes, rendered_b.markdown_bytes)
        self.assertEqual(rendered_a.checksum, hashlib.sha256(rendered_a.markdown_bytes).hexdigest())
        self.assertIn('content_revision_id: "revision-1"', rendered_a.markdown)
        self.assertTrue(rendered_a.markdown.endswith("\n"))
        self.assertEqual(rendered_a.relative_path, "articles/a-deterministic-article.md")

    def test_markdown_safety_blocks_dangerous_constructs(self) -> None:
        bad = self.snapshot.__class__(
            **{
                **self.snapshot.__dict__,
                "variant": WebsiteVariant(
                    title="Bad",
                    markdown_body="<script>alert(1)</script>",
                    published_at=self.snapshot.variant.published_at,
                    updated_at=self.snapshot.variant.updated_at,
                ),
            }
        )
        with self.assertRaises(MarkdownWebsiteRenderError):
            MarkdownRenderer().render(bad)

    def test_slug_policy(self) -> None:
        self.assertEqual(slugify("Één Artikel!"), "een-artikel")
        with self.assertRaises(MarkdownWebsitePathError):
            validate_slug("../escape")
        with self.assertRaises(MarkdownWebsitePathError):
            slugify("admin")

    def test_path_template_and_repository_boundaries(self) -> None:
        self.assertEqual(
            render_template("{content_root}/{slug}.md", {"content_root": "articles", "slug": "a"}), "articles/a.md"
        )
        with self.assertRaises(MarkdownWebsitePathError):
            render_template("{content_root}/{slug.__class__}.md", {"content_root": "articles", "slug": "a"})
        with self.assertRaises(MarkdownWebsitePathError):
            ensure_under(self.repo, "../escape.md")
        with self.assertRaises(MarkdownWebsitePathError):
            ensure_under(self.repo, ".git/config")

    def test_git_publish_commits_exact_path_and_preserves_unrelated_dirty_file(self) -> None:
        rendered = MarkdownRenderer().render(self.snapshot)
        (self.repo / "unrelated.txt").write_text("user owned unrelated\n", encoding="utf-8")
        evidence = GitPublisher().publish(
            self.snapshot,
            self.reference,
            rendered,
            identity=GitIdentity("Publisher", "publisher@example.test"),
        )
        self.assertEqual(evidence.verification_status, "mutation_verified")
        self.assertTrue((self.repo / rendered.relative_path).exists())
        self.assertTrue((self.repo / "unrelated.txt").exists())
        show = git(self.repo, "show", "--name-only", "--format=", "HEAD")
        self.assertIn(rendered.relative_path, show)
        self.assertNotIn("unrelated.txt", show)

    def test_dirty_overlap_blocks_publication(self) -> None:
        rendered = MarkdownRenderer().render(self.snapshot)
        target = self.repo / rendered.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("user change\n", encoding="utf-8")
        with self.assertRaises(MarkdownWebsiteGitError):
            GitPublisher().publish(
                self.snapshot,
                self.reference,
                rendered,
                identity=GitIdentity("Publisher", "publisher@example.test"),
            )

    def test_push_to_allowlisted_remote_and_reconcile(self) -> None:
        bare = self.root / "remote.git"
        git(self.root, "init", "--bare", str(bare))
        git(self.repo, "remote", "add", "origin", str(bare))
        rendered = MarkdownRenderer().render(self.snapshot)
        account = self.account.__class__(**{**self.account.__dict__, "push_policy": "commit_and_push"})
        snapshot = self.snapshot.__class__(**{**self.snapshot.__dict__, "account_config": account})
        evidence = GitPublisher().publish(
            snapshot,
            self.reference,
            rendered,
            identity=GitIdentity("Publisher", "publisher@example.test"),
            push=True,
        )
        self.assertEqual(evidence.verification_status, "remote_acknowledged")
        self.assertEqual(
            MarkdownWebsiteReconciliationService().reconcile(evidence, self.reference).status, "reconciled"
        )

    def test_url_verification_requires_markers_and_same_origin(self) -> None:
        rendered = MarkdownRenderer().render(self.snapshot)
        evidence = GitPublisher().publish(
            self.snapshot,
            self.reference,
            rendered,
            identity=GitIdentity("Publisher", "publisher@example.test"),
        )
        html = (
            f"<meta name='smm-content-revision' content='{self.snapshot.content_revision_id}'>"
            f"<meta name='smm-publication-target' content='{self.snapshot.publication_target_id}'>"
            f"<meta name='smm-snapshot-checksum' content='{self.snapshot.publication_snapshot_checksum}'>"
        )
        verifier = WebsitePublicationVerifier(lambda url: HttpResponse(200, url, {"content-type": "text/html"}, html))
        self.assertEqual(verifier.verify(evidence).status, "publication_verified")
        bad = WebsitePublicationVerifier(
            lambda url: HttpResponse(200, "https://evil.test/a", {"content-type": "text/html"}, html)
        )
        with self.assertRaises(MarkdownWebsiteVerificationError):
            bad.verify(evidence)

    def test_media_filename_and_copy_are_checksum_bound(self) -> None:
        data = b"image"
        source = self.root / "hero.webp"
        source.write_bytes(data)
        checksum = hashlib.sha256(data).hexdigest()
        ref = WebsiteMediaReference("asset-1", "variant-1", "Hero Image", "image/webp", checksum, alt_text="Hero")
        self.assertEqual(website_media_filename(ref), "asset-1-variant-1-Hero-Image.webp")
        relative, copied_checksum = copy_materialized_media(
            self.repo, "static/media", MaterializedMedia(ref, source, checksum, "image/webp")
        )
        self.assertEqual(copied_checksum, checksum)
        self.assertTrue((self.repo / relative).exists())

    def test_utm_link_has_no_pii_and_stays_on_public_url(self) -> None:
        url = build_utm_link(
            resolve_public_url(self.snapshot, "a-deterministic-article"),
            source="linkedin",
            source_target_id="target-linkedin",
            website_target_id="target-website",
            content_revision_id="revision-1",
            campaign="campaign-1",
        )
        self.assertIn("utm_source=linkedin", url)
        self.assertIn("smm_attribution_id=", url)
        self.assertNotIn("@", url)

    def test_manifest_schema_valid(self) -> None:
        manifest = json.loads(Path("channels/markdown_website/plugin.manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], PLUGIN_ID)
        self.assertEqual(manifest["channel_family"], "owned_publication")


if __name__ == "__main__":
    unittest.main()
