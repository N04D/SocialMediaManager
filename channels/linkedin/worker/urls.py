from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse


ALLOWED_HOST_SUFFIX = "linkedin.com"
ALLOWED_PATH_PREFIXES = (
    "/feed/update/",
    "/posts/",
)


class LinkedInUrlError(ValueError):
    """Raised when a LinkedIn post URL is missing or untrusted."""



def _is_allowed_host(hostname: str) -> bool:
    host = hostname.lower().strip().rstrip('.')
    return host == ALLOWED_HOST_SUFFIX or host.endswith(f'.{ALLOWED_HOST_SUFFIX}')



def normalize_linkedin_post_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise LinkedInUrlError("LinkedIn post URLs must start with http or https.")
    if not _is_allowed_host(parsed.netloc):
        raise LinkedInUrlError("Only trusted linkedin.com post URLs are allowed.")
    if not any(parsed.path.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES):
        raise LinkedInUrlError("Only LinkedIn post URLs under /feed/update/ or /posts/ are supported.")
    normalized = parsed._replace(scheme="https", query="", fragment="")
    cleaned = urlunparse(normalized).rstrip('/')
    return cleaned



def extract_linkedin_external_id(url: str) -> str:
    normalized = normalize_linkedin_post_url(url)
    activity_match = re.search(r"activity-(\d+)", normalized)
    if activity_match:
        return f"activity-{activity_match.group(1)}"
    share_match = re.search(r"share:(\d+)", normalized)
    if share_match:
        return f"share:{share_match.group(1)}"
    urn_match = re.search(r"urn:li:[^/?#]+", normalized)
    return urn_match.group(0) if urn_match else ""
