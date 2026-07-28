"""Host-owned staging origins and synthetic page profiles."""

from __future__ import annotations

from .models import StagingSiteOriginReference, SyntheticAnalyticsPageProfile, utc_now_iso


def deterministic_staging_origin() -> StagingSiteOriginReference:
    now = "2026-07-29T08:00:00Z"
    return StagingSiteOriginReference(
        id="staging-origin-deterministic",
        workspace_id="workspace-1",
        display_name="Deterministic synthetic staging site",
        scheme="http",
        host="smm-staging.test",
        optional_base_path="",
        environment="staging",
        synthetic_only=True,
        allowed_page_paths=("/synthetic/analytics-smoke",),
        allowed_redirect_origins=("http://smm-staging.test",),
        enabled=True,
        created_at=now,
        updated_at=now,
    )


def blocked_production_origin() -> StagingSiteOriginReference:
    now = utc_now_iso()
    return StagingSiteOriginReference(
        id="prod-origin-blocked",
        workspace_id="workspace-1",
        display_name="Blocked production origin",
        scheme="https",
        host="www.example.com",
        optional_base_path="",
        environment="production",
        synthetic_only=False,
        allowed_page_paths=("/articles/real",),
        enabled=True,
        created_at=now,
        updated_at=now,
    )


def synthetic_page_profile() -> SyntheticAnalyticsPageProfile:
    return SyntheticAnalyticsPageProfile(
        id="synthetic-page-plausible-smoke",
        version="1.0",
        display_name="Synthetic Plausible smoke page",
        page_path="/synthetic/analytics-smoke",
        instrumentation_profile_id="plausible_generic",
        expected_page_context={"content_type": "synthetic_certification"},
        expected_cta={"type": "signup", "placement": "synthetic-fixture"},
        expected_conversion={"type": "signup", "outcome": "completed"},
        consent_mode="after_external_consent",
        noindex_required=True,
        synthetic_marker="true",
    ).with_checksum()


def list_staging_origins() -> tuple[StagingSiteOriginReference, ...]:
    return (deterministic_staging_origin(), blocked_production_origin())


def list_synthetic_page_profiles() -> tuple[SyntheticAnalyticsPageProfile, ...]:
    return (synthetic_page_profile(),)


def get_staging_origin(origin_id: str) -> StagingSiteOriginReference:
    for origin in list_staging_origins():
        if origin.id == origin_id:
            return origin
    raise KeyError(origin_id)


def get_synthetic_page_profile(profile_id: str) -> SyntheticAnalyticsPageProfile:
    for profile in list_synthetic_page_profiles():
        if profile.id == profile_id:
            return profile
    raise KeyError(profile_id)


__all__ = [
    "deterministic_staging_origin",
    "get_staging_origin",
    "get_synthetic_page_profile",
    "list_staging_origins",
    "list_synthetic_page_profiles",
    "synthetic_page_profile",
]
