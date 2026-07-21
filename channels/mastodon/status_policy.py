MASTODON_STATUSES = {
    "unconfigured",
    "discovering",
    "oauth_required",
    "connecting",
    "connected",
    "disconnected",
    "authentication_required",
    "insufficient_scope",
    "instance_unreachable",
    "instance_incompatible",
    "rate_limited",
    "degraded",
    "security_error",
}


def normalize_status(value: str) -> str:
    return value if value in MASTODON_STATUSES else "degraded"
