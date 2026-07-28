"""Read-only instrumentation verification."""

from __future__ import annotations

import re
from dataclasses import asdict

from .events import PROPERTY_RULES
from .models import InstrumentationMappingDriftReport, WebsiteInstrumentationManifest, utc_now_iso


class WebsiteInstrumentationVerifier:
    def verify_static_page(self, manifest: WebsiteInstrumentationManifest, html: str) -> dict:
        missing = []
        if f'name="smm-instrumentation-manifest" content="{manifest.checksum}"' not in html:
            missing.append("manifest_marker")
        if manifest.page_context.publication_id not in html:
            missing.append("publication_marker")
        if "smm-analytics.js" not in html:
            missing.append("runtime")
        if "plausible-bridge.js" not in html and manifest.profile_id == "plausible_generic":
            missing.append("provider_bridge")
        for cta in manifest.cta_bindings:
            if cta["id"] not in html:
                missing.append("cta_binding")
        duplicate_runtime = len(re.findall(r"data-smm-runtime", html)) > 1
        unsafe = any(marker in html.lower() for marker in ("document.cookie", "localstorage", "navigator.useragent"))
        status = "complete" if not missing and not duplicate_runtime and not unsafe else "misconfigured"
        return {
            "level": "static_page",
            "status": status,
            "missing": missing,
            "duplicate_runtime": duplicate_runtime,
            "pii_risk": unsafe,
            "verified_at": utc_now_iso(),
        }

    def mapping_drift(
        self, config_id: str, expected_events: tuple[dict, ...], analytics_mappings: tuple[dict, ...], profile_id: str
    ) -> InstrumentationMappingDriftReport:
        expected = {item["event_name"] for item in expected_events}
        mapped = {item.get("provider_event_name", "") for item in analytics_mappings if item.get("enabled", True)}
        missing = tuple(sorted(expected - mapped))
        obsolete = tuple(sorted(mapped - expected))
        property_mismatches = []
        for item in expected_events:
            for prop in item.get("required_properties", ()):
                if prop not in PROPERTY_RULES:
                    property_mismatches.append(prop)
        status = "aligned" if not missing and not obsolete and not property_mismatches else "drift"
        return InstrumentationMappingDriftReport(
            config_id=config_id,
            status=status,
            missing_mappings=missing,
            obsolete_mappings=obsolete,
            property_mismatches=tuple(property_mismatches),
            profile_mismatch=profile_id
            not in {"generic_vanilla", "plausible_generic", "astro", "hugo", "jekyll", "eleventy", "nextjs"},
            generated_at=utc_now_iso(),
        )


def provider_observed_status(expected_events: tuple[dict, ...], observed_event_names: set[str]) -> str:
    expected = {item["event_name"] for item in expected_events}
    if not observed_event_names:
        return "insufficient_data"
    if expected <= observed_event_names:
        return "observed"
    if expected & observed_event_names:
        return "partially_observed"
    return "expected_but_not_observed"


def verification_payload(value) -> dict:
    return asdict(value) if hasattr(value, "__dataclass_fields__") else dict(value)


__all__ = ["WebsiteInstrumentationVerifier", "provider_observed_status", "verification_payload"]
