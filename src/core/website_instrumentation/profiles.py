"""Versioned website instrumentation profiles."""

from __future__ import annotations

from .contracts import PLAUSIBLE_BROWSER_BRIDGE_VERSION, WEBSITE_EVENT_ENVELOPE_CONTRACT_VERSION
from .models import WebsiteInstrumentationProfile


def _profile(
    profile_id: str,
    framework: str,
    *,
    provider: str = "",
    consent_mode: str = "after_external_consent",
) -> WebsiteInstrumentationProfile:
    return WebsiteInstrumentationProfile(
        id=profile_id,
        version="1.0",
        display_name=profile_id.replace("_", " ").title(),
        website_framework=framework,
        analytics_provider_id=provider,
        event_schema_version=WEBSITE_EVENT_ENVELOPE_CONTRACT_VERSION,
        page_context_strategy="manifest_meta_and_json",
        cta_strategy="data_attributes",
        outbound_click_strategy="data_attributes",
        conversion_strategy="data_attributes",
        consent_mode=consent_mode,
        script_delivery_mode="external_reference",
        public_marker_strategy="meta_tags",
        supported_features=(
            "page_context",
            "cta_click",
            "outbound_click",
            "conversion",
            "mapping_drift",
            "browser_runtime_verification",
            PLAUSIBLE_BROWSER_BRIDGE_VERSION if provider == "analytics.plausible" else "provider_neutral",
        ),
    ).with_checksum()


PROFILES = {
    "generic_vanilla": _profile("generic_vanilla", "generic"),
    "astro": _profile("astro", "astro"),
    "hugo": _profile("hugo", "hugo"),
    "jekyll": _profile("jekyll", "jekyll"),
    "eleventy": _profile("eleventy", "eleventy"),
    "nextjs": _profile("nextjs", "nextjs"),
    "plausible_generic": _profile("plausible_generic", "generic", provider="analytics.plausible"),
}


def list_profiles() -> tuple[WebsiteInstrumentationProfile, ...]:
    return tuple(PROFILES[key] for key in sorted(PROFILES))


def get_profile(profile_id: str) -> WebsiteInstrumentationProfile:
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        from .errors import WebsiteInstrumentationError

        raise WebsiteInstrumentationError("website_instrumentation.profile_unknown", "Unknown profile.") from exc


__all__ = ["PROFILES", "get_profile", "list_profiles"]
