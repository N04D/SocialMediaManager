"""Scenario payloads for website instrumentation."""


def instrumentation_config_payload() -> dict:
    return {
        "id": "instrumentation-config-owned-1",
        "workspace_id": "workspace-1",
        "website_account_id": "mw-account-owned-1",
        "analytics_account_id": "analytics-account-plausible",
        "profile_id": "plausible_generic",
        "consent_mode": "after_external_consent",
        "expected_script_origin_reference": "smm-managed-assets",
    }


def default_snapshot_payload() -> dict[str, str]:
    return {
        "content_item_id": "content-owned-1",
        "content_revision_id": "revision-owned-1",
        "publication_plan_id": "plan-owned-1",
        "publication_target_id": "target-website-owned-1",
        "publication_attempt_id": "attempt-website-owned-1",
        "publication_snapshot_checksum": "snapshot-owned-1",
        "campaign_id": "campaign-owned-1",
        "public_url": "https://example.com/articles/owned-funnel?utm_source=linkedin&utm_medium=social&utm_campaign=campaign-owned-1&utm_content=content-owned-1&smm_attribution_id=attr-social-a-owned-1",
        "language": "en",
        "published_at": "2026-07-28T08:00:00Z",
        "cta_id": "primary-signup",
        "conversion_id": "signup-complete",
    }


__all__ = ["default_snapshot_payload", "instrumentation_config_payload"]
