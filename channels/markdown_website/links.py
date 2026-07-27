"""UTM and attribution link helpers."""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def build_attribution_id(
    *,
    source_target_id: str,
    website_target_id: str,
    content_revision_id: str,
    campaign: str,
    link_variant: str,
) -> str:
    seed = "|".join([source_target_id, website_target_id, content_revision_id, campaign, link_variant])
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def build_utm_link(
    public_url: str,
    *,
    source: str,
    source_target_id: str,
    website_target_id: str,
    content_revision_id: str,
    campaign: str,
    link_variant: str = "primary",
) -> str:
    if source not in {"linkedin", "mastodon"}:
        raise ValueError("unsupported attribution source")
    parsed = urlparse(public_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(
        {
            "utm_source": source,
            "utm_medium": "social",
            "utm_campaign": campaign,
            "utm_content": source_target_id,
            "smm_attribution_id": build_attribution_id(
                source_target_id=source_target_id,
                website_target_id=website_target_id,
                content_revision_id=content_revision_id,
                campaign=campaign,
                link_variant=link_variant,
            ),
        }
    )
    return urlunparse(parsed._replace(query=urlencode(query)))
