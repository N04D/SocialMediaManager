"""Deterministic website analytics fixtures."""

from __future__ import annotations

from src.core.website_analytics.provider import SafeHttpResponse


def plausible_success_response(
    *, visitors: int = 42, pageviews: int = 77, visits: int = 44, visit_duration: int = 91
) -> SafeHttpResponse:
    return SafeHttpResponse(
        200,
        {"content-type": "application/json"},
        {
            "results": [
                {
                    "dimensions": [
                        "https://example.com/articles/owned-funnel?utm_source=linkedin&utm_medium=social&utm_campaign=campaign-owned-1&utm_content=content-owned-1&smm_attribution_id=attr-social-a-owned-1"
                    ],
                    "metrics": [visitors, pageviews, visits, visit_duration],
                }
            ],
            "meta": {"total_rows": 1},
            "query": {"site_id": "example.com"},
        },
    )


def plausible_source_response() -> SafeHttpResponse:
    return SafeHttpResponse(
        200,
        {"content-type": "application/json"},
        {
            "results": [
                {"dimensions": ["linkedin", "campaign-owned-1", "content-owned-1"], "metrics": [40, 41]},
                {"dimensions": ["mastodon", "campaign-owned-1", "content-owned-1"], "metrics": [12, 13]},
            ],
            "meta": {"total_rows": 2},
            "query": {"site_id": "example.com"},
        },
    )


def plausible_event_response(value: int = 3) -> SafeHttpResponse:
    return SafeHttpResponse(
        200,
        {"content-type": "application/json"},
        {
            "results": [
                {"dimensions": ["CTA Click", "cta-primary", "attr-social-a-owned-1"], "metrics": [value]},
                {"dimensions": ["Signup", "cta-primary", "attr-social-a-owned-1"], "metrics": [1]},
            ],
            "meta": {"total_rows": 2},
            "query": {"site_id": "example.com"},
        },
    )


def plausible_rate_limit_response() -> SafeHttpResponse:
    return SafeHttpResponse(429, {"content-type": "application/json", "retry-after": "60"}, {"error": "rate_limited"})


def plausible_invalid_token_response() -> SafeHttpResponse:
    return SafeHttpResponse(401, {"content-type": "application/json"}, {"error": "invalid_token"})


def plausible_schema_drift_response() -> SafeHttpResponse:
    return SafeHttpResponse(200, {"content-type": "application/json"}, {"unexpected": []})


def plausible_fixture_responses() -> dict[str, SafeHttpResponse]:
    from src.providers.analytics.plausible.queries import PLAUSIBLE_ENDPOINT

    return {PLAUSIBLE_ENDPOINT: plausible_success_response()}


__all__ = [
    "plausible_event_response",
    "plausible_fixture_responses",
    "plausible_invalid_token_response",
    "plausible_rate_limit_response",
    "plausible_schema_drift_response",
    "plausible_source_response",
    "plausible_success_response",
]
