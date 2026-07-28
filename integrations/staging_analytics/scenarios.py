"""Scenario payloads for staging analytics certification."""


def staging_profile_payload() -> dict:
    return {
        "id": "staging-cert-profile-1",
        "workspace_id": "workspace-1",
        "staging_origin_reference_id": "staging-origin-deterministic",
        "analytics_account_id": "analytics-account-plausible",
        "synthetic_page_profile_id": "synthetic-page-plausible-smoke",
        "expected_event_mapping_ids": ("mapping-cta", "mapping-outbound", "mapping-conversion"),
        "browser_name": "chromium",
        "browser_mode": "headless",
        "maximum_wait_seconds": 30,
        "initial_poll_delay_seconds": 1,
        "maximum_poll_delay_seconds": 8,
        "polling_multiplier": 2.0,
        "maximum_poll_attempts": 4,
        "correction_window": "recent_completed_periods",
        "enabled": True,
    }


def staging_account_payload() -> dict:
    return {
        "id": "analytics-account-plausible",
        "workspace_id": "workspace-1",
        "provider_id": "analytics.plausible",
        "display_name": "Synthetic staging Plausible",
        "origin_reference_id": "plausible-cloud",
        "site_identifier": "staging.example.test",
        "secret_reference_id": "secret-plausible-fixture",
        "timezone": "UTC",
        "default_date_granularity": "day",
        "enabled": True,
        "environment": "staging",
        "synthetic_testing_allowed": True,
    }


__all__ = ["staging_account_payload", "staging_profile_payload"]
