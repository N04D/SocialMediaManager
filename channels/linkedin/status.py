from __future__ import annotations

from dataclasses import dataclass

from src.core.browser import (
    BrowserAuthenticationRequiredError,
    BrowserProfileBusyError,
    BrowserProviderError,
    BrowserUnavailableError,
)


@dataclass(frozen=True)
class LinkedInStatusMapping:
    job_status: str
    connection_status: str
    error_code: str
    retryable: bool = False


def map_browser_error(error: BrowserProviderError) -> LinkedInStatusMapping:
    if isinstance(error, BrowserProfileBusyError):
        return LinkedInStatusMapping("queued", "preserve", "profile_busy", retryable=True)
    if isinstance(error, BrowserAuthenticationRequiredError):
        return LinkedInStatusMapping("needs_login", "needs_login", "authentication_required")
    if isinstance(error, BrowserUnavailableError):
        return LinkedInStatusMapping("failed", "preserve", error.code or "provider_unavailable", retryable=True)
    return LinkedInStatusMapping("failed", "preserve", error.code or "browser_error")


LINKEDIN_ERROR_POLICY = {
    "profile_busy": "operation retryable; account connection status is preserved",
    "provider_unavailable": "operation failed; account connection status is preserved",
    "authentication_required": "operation failed; account moves to authentication_required/needs_login",
    "rate_limited": "operation retryable; account remains connected",
    "layout_changed": "plugin degraded; account remains connected unless authentication also fails",
    "post_not_found": "operation-specific failure; account remains connected",
    "publish_verification_failed": "publish result unknown; no automatic duplicate retry",
}
