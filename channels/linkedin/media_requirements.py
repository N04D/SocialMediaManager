from __future__ import annotations

from src.core.media import ChannelMediaRequirements

LINKEDIN_IMAGE_PUBLISH_REQUIREMENTS = ChannelMediaRequirements(
    channel_plugin_id="channel.linkedin",
    capability="linkedin.image_publish",
    requirement_id="linkedin.image.publish.v1",
    requirement_version="1.0",
    allowed_mime_types=("image/jpeg", "image/png"),
    min_width=1,
    min_height=1,
    max_width=7680,
    max_height=4320,
    max_file_size=25_000_000,
    max_assets=9,
    processor_plugin_id="media.image.processing.basic",
)


def register_linkedin_media_requirements(registry) -> None:
    registry.register(LINKEDIN_IMAGE_PUBLISH_REQUIREMENTS)
