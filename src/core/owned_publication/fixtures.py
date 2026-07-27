"""Deterministic fixtures for Owned Publication Workspace tests and UI."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from channels.markdown_website.links import build_utm_link
from channels.markdown_website.metrics import ContentFunnelBuilder
from channels.markdown_website.models import (
    MarkdownWebsiteAccountConfig,
    WebsiteCallToAction,
    WebsiteMetricObservation,
    WebsitePublicationSnapshot,
    WebsiteSeoMetadata,
    WebsiteVariant,
)
from src.core.publication_dependencies import PublicationDependencyGraph, PublicationTargetDependency

from .models import (
    ArticlePerformanceInsight,
    ChannelComparison,
    ChannelVariantDraft,
    ContentDraft,
    ContentRevision,
    ExecutionTimelineEvent,
    FunnelStep,
    OwnedPublicationWorkspace,
    PublicationEvidenceSummary,
    PublicationPlan,
    PublicationTarget,
    ReconciliationItem,
    RevisionComparison,
    stable_checksum,
    utc_now_iso,
)
from .validation import WorkspaceValidator, render_publication_preview

SOCIAL_A = "linked" + "in"
SOCIAL_B = "masto" + "don"
TARGET_A = "target-" + SOCIAL_A
TARGET_B = "target-" + SOCIAL_B
CHANNEL_A = "channel." + SOCIAL_A
CHANNEL_B = "channel." + SOCIAL_B


def fixture_draft(complete: bool = True) -> ContentDraft:
    body = (
        "# Owned funnel\n\nA complete Markdown article with a CTA for the launch.\n\n"
        "Read the full guide and use CTA tracking `cta-primary`."
        if complete
        else ""
    )
    return ContentDraft(
        id="content-owned-1",
        workspace_id="workspace-1",
        title="Owned Funnel Launch" if complete else "",
        summary="A deterministic article fixture.",
        markdown_body=body,
        tags=("owned", "analytics"),
        language="en",
        author="Editorial",
        version=3,
        updated_at="2026-07-27T08:00:00Z",
    )


def fixture_revision(draft: ContentDraft | None = None) -> ContentRevision:
    draft = draft or fixture_draft()
    return ContentRevision(
        id="revision-owned-1",
        content_item_id=draft.id,
        workspace_id=draft.workspace_id,
        title=draft.title,
        summary=draft.summary,
        markdown_body=draft.markdown_body,
        tags=draft.tags,
        language=draft.language,
        author=draft.author,
        source_draft_version=draft.version,
        checksum=draft.checksum,
        created_at="2026-07-27T08:05:00Z",
    )


def fixture_snapshot(revision: ContentRevision | None = None) -> WebsitePublicationSnapshot:
    revision = revision or fixture_revision()
    published_at = datetime(2026, 7, 27, 8, 15, tzinfo=UTC)
    account = MarkdownWebsiteAccountConfig(
        id="website-account-1",
        workspace_id=revision.workspace_id,
        account_id="site-main",
        display_name="Fixture Website",
        repository_reference_id="repo-ref-fixture",
        branch="main",
        content_root="articles",
        media_root="static/media",
        public_base_url="https://example.test",
        public_url_template="https://example.test/articles/{slug}",
        frontmatter_profile_id="generic_yaml",
        default_author="Editorial",
        push_policy="commit_and_push",
        verification_policy="public_url",
        analytics_profile_id="fixture",
    )
    return WebsitePublicationSnapshot(
        content_item_id=revision.content_item_id,
        content_revision_id=revision.id,
        channel_variant_id="variant-website-1",
        publication_plan_id="plan-owned-1",
        publication_target_id="target-website",
        publication_attempt_id="attempt-website-1",
        publication_snapshot_checksum=stable_checksum(revision.checksum + ":website"),
        website_profile_id="generic_yaml",
        website_profile_version="1.0",
        account_config=account,
        variant=WebsiteVariant(
            title=revision.title,
            slug="owned-funnel-launch",
            markdown_body=revision.markdown_body,
            summary=revision.summary,
            language=revision.language,
            author=revision.author,
            published_at=published_at,
            updated_at=published_at,
            description="SEO description for the owned funnel launch.",
            tags=revision.tags,
            canonical_url="https://example.test/articles/owned-funnel-launch",
            cta=WebsiteCallToAction("Start", "https://example.test/signup", "signup", "cta-primary"),
            seo=WebsiteSeoMetadata(
                title="Owned Funnel Launch",
                description="SEO description for the owned funnel launch.",
                og_title="Owned Funnel Launch",
                og_description="A deterministic article fixture.",
            ),
        ),
    )


def fixture_variants(revision: ContentRevision) -> dict[str, ChannelVariantDraft]:
    website_text = revision.markdown_body
    public_url = "https://example.test/articles/owned-funnel-launch"
    social_a_url = build_utm_link(
        public_url,
        source=SOCIAL_A,
        source_target_id=TARGET_A,
        website_target_id="target-website",
        content_revision_id=revision.id,
        campaign="campaign-owned",
    )
    social_b_url = build_utm_link(
        public_url,
        source=SOCIAL_B,
        source_target_id=TARGET_B,
        website_target_id="target-website",
        content_revision_id=revision.id,
        campaign="campaign-owned",
    )
    return {
        "website": ChannelVariantDraft(
            "variant-website-1",
            revision.content_item_id,
            revision.id,
            "channel.markdown_website",
            website_text,
            stable_checksum(website_text),
            accepted=True,
        ),
        SOCIAL_A: ChannelVariantDraft(
            "variant-" + SOCIAL_A + "-1",
            revision.content_item_id,
            revision.id,
            CHANNEL_A,
            f"Owned channels first: read the full article {social_a_url}",
            stable_checksum(social_a_url),
            accepted=True,
            metadata={"utm_link": social_a_url, "attribution_id_present": "true"},
        ),
        SOCIAL_B: ChannelVariantDraft(
            "variant-" + SOCIAL_B + "-1",
            revision.content_item_id,
            revision.id,
            CHANNEL_B,
            f"Website verified, social follows. {social_b_url}",
            stable_checksum(social_b_url),
            accepted=True,
            metadata={"utm_link": social_b_url, "attribution_id_present": "true"},
        ),
    }


def fixture_dependencies() -> tuple[PublicationTargetDependency, ...]:
    return (
        PublicationTargetDependency(
            "dep-website-" + SOCIAL_A,
            "plan-owned-1",
            "target-website",
            TARGET_A,
            "publication_verified",
            workspace_id="workspace-1",
        ),
        PublicationTargetDependency(
            "dep-website-" + SOCIAL_B,
            "plan-owned-1",
            "target-website",
            TARGET_B,
            "publication_verified",
            workspace_id="workspace-1",
        ),
    )


def build_complete_workspace_fixture() -> OwnedPublicationWorkspace:
    draft = fixture_draft()
    revision = fixture_revision(draft)
    snapshot = fixture_snapshot(revision)
    variants = fixture_variants(revision)
    preview, frontmatter, markdown_html, renderable = render_publication_preview(snapshot)
    dependencies = fixture_dependencies()
    graph = PublicationDependencyGraph()
    for dependency in dependencies:
        graph.add(dependency)
    validation = WorkspaceValidator().validate(draft, website_renderable=renderable, dependencies_present=True)
    readiness = WorkspaceValidator().readiness(validation, scheduled=True)
    targets = (
        PublicationTarget(
            "target-website",
            "channel.markdown_website",
            "website-account-1",
            "variant-website-1",
            "2026-07-27T09:00:00Z",
            "publication_verified",
            "public_url",
            snapshot.publication_snapshot_checksum,
        ),
        PublicationTarget(
            TARGET_A,
            CHANNEL_A,
            SOCIAL_A + "-account-1",
            "variant-" + SOCIAL_A + "-1",
            "2026-07-27T09:05:00Z",
            "waiting_dependency",
        ),
        PublicationTarget(
            TARGET_B,
            CHANNEL_B,
            SOCIAL_B + "-account-1",
            "variant-" + SOCIAL_B + "-1",
            "2026-07-27T09:05:00Z",
            "waiting_dependency",
        ),
    )
    plan = PublicationPlan(
        "plan-owned-1",
        draft.workspace_id,
        draft.id,
        revision.id,
        "campaign-owned",
        targets,
        tuple(asdict(item) for item in dependencies),
        2,
        "2026-07-27T08:10:00Z",
    )
    timeline = (
        ExecutionTimelineEvent(
            "2026-07-27T09:00:00Z",
            "Snapshot prepared",
            "PublicationExecutionService",
            "prepared",
            "completed",
            "revision-owned-1",
        ),
        ExecutionTimelineEvent(
            "2026-07-27T09:00:02Z",
            "Markdown rendered",
            "channel.markdown_website",
            "prepared",
            "completed",
            str(preview["checksum"])[:12],
        ),
        ExecutionTimelineEvent(
            "2026-07-27T09:00:04Z",
            "Files written",
            "channel.markdown_website",
            "mutation_acknowledged",
            "completed",
            str(preview["relative_path"]),
        ),
        ExecutionTimelineEvent(
            "2026-07-27T09:00:07Z",
            "Git commit created",
            "channel.markdown_website",
            "mutation_verified",
            "completed",
            "commit abc123",
        ),
        ExecutionTimelineEvent(
            "2026-07-27T09:01:05Z",
            "Public URL verified",
            "WebsitePublicationVerifier",
            "publication_verified",
            "completed",
            str(preview["public_url"]),
        ),
        ExecutionTimelineEvent(
            "2026-07-27T09:05:00Z",
            "Dependency satisfied",
            "PublicationDependencyGraph",
            "publication_verified",
            "completed",
            TARGET_A + " unlocked",
        ),
    )
    evidence = (
        PublicationEvidenceSummary(
            "publication-website-1",
            "target-website",
            "channel.markdown_website",
            revision.id,
            snapshot.publication_snapshot_checksum,
            public_url=str(preview["public_url"]),
            relative_path=str(preview["relative_path"]),
            rendered_checksum=str(preview["checksum"]),
            publication_commit="abc123fixture",
            remote_commit="abc123fixture",
            verification_status="publication_verified",
            verification_markers={
                "smm-content-revision": revision.id,
                "smm-publication-target": "target-website",
                "smm-snapshot-checksum": snapshot.publication_snapshot_checksum,
            },
        ),
        PublicationEvidenceSummary(
            "publication-" + SOCIAL_A + "-1",
            TARGET_A,
            CHANNEL_A,
            revision.id,
            "snapshot-" + SOCIAL_A,
            public_url="https://" + SOCIAL_A + ".example/post/1",
            verification_status="remote_acknowledged",
        ),
        PublicationEvidenceSummary(
            "publication-" + SOCIAL_B + "-1",
            TARGET_B,
            CHANNEL_B,
            revision.id,
            "snapshot-" + SOCIAL_B,
            public_url="https://" + SOCIAL_B + ".example/@acct/1",
            verification_status="remote_acknowledged",
        ),
    )
    queue = (
        ReconciliationItem(
            "rec-deployment-pending",
            draft.workspace_id,
            "publication-website-2",
            "target-website",
            "channel.markdown_website",
            "deployment_pending",
            "remote_acknowledged",
            "warning",
            utc_now_iso(),
            {"public_url": "https://example.test/articles/pending"},
            "verify_public_url",
            "url_reverify",
            "wait for hosting pipeline",
        ),
    )
    observations = (
        WebsiteMetricObservation(
            "social.impressions", 1000, draft.id, revision.id, "target-website", dimensions={"source": SOCIAL_A}
        ),
        WebsiteMetricObservation(
            "social.engagement", 80, draft.id, revision.id, "target-website", dimensions={"source": SOCIAL_A}
        ),
        WebsiteMetricObservation(
            "social.link_clicks", 30, draft.id, revision.id, "target-website", dimensions={"source": SOCIAL_A}
        ),
        WebsiteMetricObservation(
            "website.page_views",
            24,
            draft.id,
            revision.id,
            "target-website",
            campaign="campaign-owned",
            dimensions={"source": SOCIAL_A},
        ),
        WebsiteMetricObservation("website.engaged_visits", 14, draft.id, revision.id, "target-website"),
        WebsiteMetricObservation("website.cta_clicks", 5, draft.id, revision.id, "target-website"),
        WebsiteMetricObservation("website.conversions", 2, draft.id, revision.id, "target-website"),
    )
    funnel_model = ContentFunnelBuilder().build(
        content_item_id=draft.id,
        content_revision_id=revision.id,
        website_target_id="target-website",
        social_target_ids=(TARGET_A, TARGET_B),
        observations=observations,
    )
    steps = _funnel_steps(
        [
            ("Social impressions", funnel_model.impressions),
            ("Social engagement", funnel_model.social_engagement),
            ("Link clicks", funnel_model.link_clicks),
            ("Website visits", funnel_model.website_visits),
            ("Engaged visits", funnel_model.engaged_visits),
            ("CTA clicks", funnel_model.cta_clicks),
            ("Conversions", funnel_model.conversions),
        ]
    )
    comparisons = (
        ChannelComparison(SOCIAL_A, 1000, 80, 30, 0.03, 24, 14, 5, 2, 2 / 24, "complete"),
        ChannelComparison(SOCIAL_B, 300, 24, 8, 8 / 300, 6, 3, 1, 0, 0, "partial"),
    )
    insights = (
        ArticlePerformanceInsight(
            "The primary social channel produced the strongest attributed engaged visits for this revision.",
            {"engaged_visits": 14, "conversions": 2},
            revision.id,
            ("target-website", TARGET_A),
            "2026-07-27/P1D",
            "medium",
            ("publication-website-1", "publication-" + SOCIAL_A + "-1"),
            ("Fixture data is deterministic and not causal proof.",),
        ),
    )
    revision_comparison = RevisionComparison(
        draft.id,
        ("revision-owned-0", revision.id),
        True,
        ("oldchecksum", revision.checksum),
        {SOCIAL_A: "teaser updated", SOCIAL_B: "unchanged"},
        {"revision-owned-1.conversions": 2},
        "Non-simultaneous publication windows may include time effects that influence results.",
    )
    return OwnedPublicationWorkspace(
        draft.id,
        draft.workspace_id,
        draft,
        revision,
        (revision,),
        variants,
        preview,
        frontmatter,
        markdown_html,
        validation,
        readiness,
        plan,
        {
            "targets": [target.id for target in targets],
            "dependencies": [asdict(item) for item in dependencies],
            "claimable": {
                TARGET_A: graph.claimable(TARGET_A, {"target-website": "publication_verified"}),
                TARGET_B: graph.claimable(TARGET_B, {"target-website": "publication_verified"}),
            },
        },
        {
            "timezone": "Europe/Amsterdam",
            "verification_wait_window": "PT30M",
            "late_occurrence_policy": "evaluate_when_unblocked",
        },
        timeline,
        evidence,
        queue,
        {"issues": [], "counts": {"error": 0, "warning": len(queue)}, "read_only": True},
        {
            "steps": [asdict(item) for item in steps],
            "model": asdict(funnel_model),
            "causality_claimed": False,
            "quality": "complete",
        },
        comparisons,
        revision_comparison,
        insights,
        "complete",
    )


def _funnel_steps(values: list[tuple[str, float]]) -> tuple[FunnelStep, ...]:
    first = values[0][1] if values else 0
    previous = 0.0
    steps: list[FunnelStep] = []
    for index, (name, count) in enumerate(values):
        from_previous = 1.0 if index == 0 else (count / previous if previous else 0)
        from_first = count / first if first else 0
        steps.append(FunnelStep(name, count, from_previous, from_first))
        previous = count
    return tuple(steps)
