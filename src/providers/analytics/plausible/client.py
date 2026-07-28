"""Plausible client boundary.

The production adapter intentionally has no direct HTTP client here. It binds to
the host-owned SafeHttpFacade from src.core.website_analytics.provider.
"""

READ_ONLY_ENDPOINTS = ("/api/v2/query",)
FORBIDDEN_WRITE_ENDPOINTS = ("/api/event", "/api/v1/sites", "/api/v1/goals")
