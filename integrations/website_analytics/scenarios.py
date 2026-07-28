"""End-to-end website analytics scenarios."""

from __future__ import annotations


def plausible_account_payload() -> dict:
    return {
        "id": "analytics-account-plausible",
        "workspace_id": "workspace-1",
        "provider_id": "analytics.plausible",
        "display_name": "Example Plausible",
        "origin_reference_id": "plausible-cloud",
        "site_identifier": "example.com",
        "secret_reference_id": "secret-plausible-fixture",
        "timezone": "UTC",
        "default_date_granularity": "day",
        "enabled": True,
    }


def event_mappings_payload() -> list[dict]:
    return [
        {
            "id": "mapping-cta",
            "provider_event_name": "CTA Click",
            "provider_property_filters": {"cta_id": "cta-primary"},
            "internal_event_type": "cta_click",
            "cta_id": "cta-primary",
        },
        {
            "id": "mapping-signup",
            "provider_event_name": "Signup",
            "provider_property_filters": {"cta_id": "cta-primary"},
            "internal_event_type": "conversion",
            "cta_id": "cta-primary",
            "conversion_type": "signup",
            "conversion_value_policy": "provider_value",
        },
    ]


__all__ = ["event_mappings_payload", "plausible_account_payload"]
