"""Quality classification helpers for staging analytics certification."""


def staging_quality_status(*, browser_verified: bool, provider_status: str) -> str:
    if provider_status == "observed" and browser_verified:
        return "complete"
    if browser_verified and provider_status in {"not_observed", "partially_observed"}:
        return "browser_verified_provider_pending"
    if provider_status == "conflicting":
        return "conflicting"
    return "not_configured"


__all__ = ["staging_quality_status"]
