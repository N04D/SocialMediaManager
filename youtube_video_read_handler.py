from __future__ import annotations

from typing import Any, Callable

from channels.youtube.transport import YouTubeTransport
from src.core.content.models import ContentCompleteness
from src.core.content.resources import ExternalResourceSnapshot, ResourceRef
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.execution_context import ExecutionContext, _assert_no_secret_values
from src.core.runtime.plans import ExecutionPlanNode
from src.core.runtime.playbooks import PlaybookNode

YOUTUBE_VIDEO_READ_CAPABILITY = "youtube.video.read"
YOUTUBE_UPLOADS_COMPONENT_ID = "youtube-data-api-uploads"


class YouTubeVideoReadHandler:
    component_id = YOUTUBE_UPLOADS_COMPONENT_ID
    capability_id = YOUTUBE_VIDEO_READ_CAPABILITY

    def __init__(
        self,
        *,
        transport: YouTubeTransport,
        access_token_resolver: Callable[[str], str],
    ):
        self.transport = transport
        self.access_token_resolver = access_token_resolver

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        _assert_no_secret_values(input_data, code="youtube.video.read")

        video_id = str(input_data.get("video_id") or "").strip()
        if not video_id:
            runtime_meta = input_data.get("_runtime")
            if isinstance(runtime_meta, dict):
                video_id = str(runtime_meta.get("video_id") or "").strip()

        if not video_id:
            raise PlaybookExecutionError(
                "MISSING_REQUIRED_INPUT",
                "youtube.video.read requires video_id input.",
                {"field": "video_id"},
            )

        install_id = resolved_node.install_id or (context.install_id if context else "install-yt-default")
        try:
            token = self.access_token_resolver(install_id)
        except Exception as exc:
            raise PlaybookExecutionError(
                "TOKEN_RESOLUTION_FAILED",
                f"Failed to resolve access token for install {install_id}.",
                {"install_id": install_id},
            ) from exc

        try:
            response = self.transport.get_video(video_id=video_id, access_token=token)
        except Exception as exc:
            raise PlaybookExecutionError(
                "YOUTUBE_READ_FAILED",
                f"Failed to fetch YouTube video metadata for {video_id}.",
                {"video_id": video_id},
            ) from exc

        items = response.payload.get("items") or []
        resource_ref = ResourceRef(
            provider="youtube",
            resource_type="video",
            external_id=video_id,
            install_id=install_id,
        )

        if not items:
            result = {
                "completeness": ContentCompleteness.METADATA_ONLY.value,
                "found": False,
                "resource_ref": resource_ref.canonical_ref,
                "status": "missing_or_unavailable",
                "video_id": video_id,
            }
            _assert_no_secret_values(result, code="youtube.video.read")
            return result

        item = items[0]
        snippet = item.get("snippet") or {}
        content_details = item.get("contentDetails") or {}
        status = item.get("status") or {}

        fields = {
            "channel_id": str(snippet.get("channelId") or ""),
            "completeness": ContentCompleteness.METADATA_ONLY.value,
            "description": str(snippet.get("description") or ""),
            "duration": str(content_details.get("duration") or ""),
            "privacy_status": str(status.get("privacyStatus") or ""),
            "published_at": str(snippet.get("publishedAt") or ""),
            "title": str(snippet.get("title") or ""),
            "video_id": video_id,
        }

        snapshot = ExternalResourceSnapshot(
            resource_ref=resource_ref,
            provider_revision=str(item.get("etag") or ""),
            fields=fields,
        )

        result = {
            "channel_id": fields["channel_id"],
            "completeness": fields["completeness"],
            "description": fields["description"],
            "duration": fields["duration"],
            "found": True,
            "privacy_status": fields["privacy_status"],
            "published_at": fields["published_at"],
            "resource_ref": resource_ref.canonical_ref,
            "snapshot": snapshot.to_dict(),
            "title": fields["title"],
            "video_id": video_id,
        }

        _assert_no_secret_values(result, code="youtube.video.read")
        return result
