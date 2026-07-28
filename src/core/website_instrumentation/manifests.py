"""Instrumentation manifest generation."""

from __future__ import annotations

from dataclasses import asdict
from urllib.parse import urlparse

from .contracts import WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION, WEBSITE_PAGE_CONTEXT_CONTRACT_VERSION
from .identifiers import opaque_id
from .models import (
    WebsiteInstrumentationConfig,
    WebsiteInstrumentationManifest,
    WebsitePageContext,
    stable_checksum,
    utc_now_iso,
)
from .profiles import get_profile


def build_manifest(config: WebsiteInstrumentationConfig, snapshot: dict[str, str]) -> WebsiteInstrumentationManifest:
    profile = get_profile(config.profile_id)
    workspace_id = config.workspace_id
    public_url = snapshot.get("public_url", "https://example.com/articles/owned-funnel")
    parsed = urlparse(public_url)
    publication_target_id = snapshot.get("publication_target_id", "target-website-owned-1")
    publication_attempt_id = snapshot.get("publication_attempt_id", "attempt-website-owned-1")
    content_item_id = snapshot.get("content_item_id", "content-owned-1")
    content_revision_id = snapshot.get("content_revision_id", "revision-owned-1")
    campaign_id = snapshot.get("campaign_id", "campaign-owned-1")
    page_context_without_checksum = {
        "schema_version": WEBSITE_PAGE_CONTEXT_CONTRACT_VERSION,
        "page_id": opaque_id(workspace_id, "page", publication_target_id),
        "canonical_url": public_url,
        "page_path": parsed.path or "/",
        "content_id": opaque_id(workspace_id, "content", content_item_id),
        "revision_id": opaque_id(workspace_id, "revision", content_revision_id),
        "publication_id": opaque_id(workspace_id, "publication", publication_target_id),
        "campaign_id": opaque_id(workspace_id, "campaign", campaign_id),
        "language": snapshot.get("language", "en"),
        "content_type": "article",
        "published_at": snapshot.get("published_at", "2026-07-28T08:00:00Z"),
        "instrumentation_manifest_checksum": "",
    }
    manifest_seed = {
        "config_id": config.id,
        "snapshot": snapshot,
        "page_context": page_context_without_checksum,
        "version": WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION,
    }
    checksum = stable_checksum(manifest_seed)
    page_context = WebsitePageContext(
        **{**page_context_without_checksum, "instrumentation_manifest_checksum": checksum}
    )
    cta_id = opaque_id(workspace_id, "cta", snapshot.get("cta_id", "primary"))
    conversion_id = opaque_id(workspace_id, "conversion", snapshot.get("conversion_id", "signup"))
    expected_events = (
        {"event_type": "cta_click", "event_name": config.cta_event_name, "required_properties": ("page_id", "cta_id")},
        {"event_type": "outbound_click", "event_name": config.outbound_event_name, "required_properties": ("page_id",)},
        {
            "event_type": "conversion",
            "event_name": config.conversion_event_name,
            "required_properties": ("page_id", "conversion_id"),
        },
    )
    manifest = WebsiteInstrumentationManifest(
        id=opaque_id(workspace_id, "manifest", checksum),
        workspace_id=workspace_id,
        website_account_id=config.website_account_id,
        analytics_account_id=config.analytics_account_id,
        content_item_id=content_item_id,
        content_revision_id=content_revision_id,
        publication_plan_id=snapshot.get("publication_plan_id", "plan-owned-1"),
        publication_target_id=publication_target_id,
        publication_attempt_id=publication_attempt_id,
        campaign_id=campaign_id,
        public_url=public_url,
        page_path=parsed.path or "/",
        page_context=page_context,
        cta_bindings=({"id": cta_id, "type": "signup", "placement": "article-footer"},),
        conversion_bindings=({"id": conversion_id, "type": "signup", "cta_id": cta_id},),
        expected_events=expected_events,
        attribution_policy=config.attribution_policy,
        consent_mode=config.consent_mode,
        profile_id=profile.id,
        profile_version=profile.version,
        script_version=WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION,
        created_at=utc_now_iso(),
        checksum=checksum,
    )
    return manifest


def manifest_payload(manifest: WebsiteInstrumentationManifest) -> dict:
    payload = asdict(manifest)
    payload["page_context"] = asdict(manifest.page_context)
    payload["immutable"] = True
    return payload


__all__ = ["build_manifest", "manifest_payload"]
