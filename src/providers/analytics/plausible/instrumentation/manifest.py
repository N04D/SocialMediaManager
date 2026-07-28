"""Plausible browser bridge manifest."""

PLAUSIBLE_BROWSER_INSTRUMENTATION_MANIFEST = {
    "provider_id": "analytics.plausible",
    "bridge_id": "plausible_browser",
    "bridge_version": "0.1.0",
    "data_access": "browser_side_public_tracking_only",
    "contains_secret": False,
    "backend_provider_write": False,
}
