from __future__ import annotations

from src.core.media import ChannelMediaRequirements

MASTODON_IMAGE_PUBLISH_REQUIREMENTS = ChannelMediaRequirements(
    channel_plugin_id="channel.mastodon",
    capability="channel.publish.image",
    requirement_id="mastodon.image.publish.dynamic.v1",
    requirement_version="mastodon.dynamic.v1",
    allowed_mime_types=("image/jpeg", "image/png"),
    min_width=1,
    min_height=1,
    max_width=7680,
    max_height=4320,
    max_file_size=8_000_000,
    max_assets=4,
    processor_plugin_id="media.image.processing.basic",
)


def register_mastodon_media_requirements(registry) -> None:
    registry.register(MASTODON_IMAGE_PUBLISH_REQUIREMENTS)
