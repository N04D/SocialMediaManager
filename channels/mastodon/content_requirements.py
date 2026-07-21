from __future__ import annotations

from src.core.content import ChannelContentRequirements

MASTODON_TEXT_PUBLISH_REQUIREMENTS = ChannelContentRequirements(
    channel_plugin_id="channel.mastodon",
    capability="channel.publish.text",
    version="mastodon.dynamic.v1",
    title_supported=False,
    title_required=False,
    body_required=True,
    min_body_length=1,
    max_body_length=100000,
    supported_languages=(),
    hashtags_supported=True,
    max_hashtags=50,
    mentions_supported=False,
    links_supported=True,
    line_breaks_supported=True,
    media_required=False,
    maximum_media_items=4,
    variant_required=False,
    notes={
        "dynamic": True,
        "account_specific_limits": "Resolved by MastodonRequirementsResolver before preparation and execution.",
    },
)


def register_mastodon_content_requirements(registry) -> None:
    registry.register(MASTODON_TEXT_PUBLISH_REQUIREMENTS)
