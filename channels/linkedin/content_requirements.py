from __future__ import annotations

from src.core.content import ChannelContentRequirements

LINKEDIN_TEXT_PUBLISH_REQUIREMENTS = ChannelContentRequirements(
    channel_plugin_id="channel.linkedin",
    capability="channel.publish.text",
    version="1.0",
    title_supported=False,
    title_required=False,
    body_required=True,
    min_body_length=1,
    max_body_length=3000,
    supported_languages=(),
    hashtags_supported=True,
    max_hashtags=30,
    mentions_supported=False,
    links_supported=True,
    line_breaks_supported=True,
    media_required=False,
    maximum_media_items=9,
    variant_required=False,
    notes={
        "supported_application_limits": [
            "current composer flow sends body text only",
            "title is retained as canonical metadata and is not sent as a separate LinkedIn field",
            "media count follows the registered LinkedIn media requirement set",
        ]
    },
)


def register_linkedin_content_requirements(registry) -> None:
    registry.register(LINKEDIN_TEXT_PUBLISH_REQUIREMENTS)
