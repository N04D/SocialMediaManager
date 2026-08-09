from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from channels.youtube.channel import YouTubeChannelService
from channels.youtube.errors import YouTubeChannelError
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.execution_context import ExecutionContext, _assert_no_secret_values
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.plans import ExecutionPlanNode
from src.core.runtime.playbooks import PlaybookNode
from src.core.runtime.results import NodeResult

YOUTUBE_REMOTE_COMPONENT_ID = "youtube-upload-channel"
YOUTUBE_VIDEO_METADATA_READ_CAPABILITY = "youtube.video.metadata.read"
YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")

YOUTUBE_VIDEO_METADATA_READ_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["video_id"],
    "properties": {
        "video_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{6,32}$"},
    },
}

YOUTUBE_VIDEO_METADATA_READ_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["video_id", "title", "source"],
    "properties": {
        "video_id": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "published_at": {"type": "string"},
        "channel_id": {"type": "string"},
        "channel_title": {"type": "string"},
        "privacy_status": {"type": "string"},
        "processing_status": {"type": "string"},
        "source": {"type": "string"},
    },
}

YOUTUBE_NETWORK_POLICY: dict[str, Any] = {
    "required": True,
    "allowed_domains": ["oauth2.googleapis.com", "www.googleapis.com"],
}

AccessTokenResolver = Callable[[str], str]


@dataclass
class YouTubeVideoMetadataReadHandler:
    youtube_service: YouTubeChannelService
    access_token_resolver: AccessTokenResolver
    component_id: str = YOUTUBE_REMOTE_COMPONENT_ID
    capability_id: str = YOUTUBE_VIDEO_METADATA_READ_CAPABILITY

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> NodeResult:
        del context, node
        try:
            _assert_no_secret_values(input_data, code="youtube.input_secret_value")
            video_id = _validate_input(input_data)
            access_token = self.access_token_resolver(resolved_node.install_id)
            if not access_token:
                raise PlaybookExecutionError(
                    "YOUTUBE_AUTHENTICATION_REQUIRED",
                    "YouTube video metadata read requires a configured access token.",
                    {"install_id": resolved_node.install_id},
                )
            metadata = self.youtube_service.read_video_metadata(video_id=video_id, access_token=access_token)
        except PlaybookExecutionError as exc:
            return NodeResult.failure(exc.code, exc.user_message, exc.details)
        except YouTubeChannelError as exc:
            return NodeResult.failure(_runtime_error_code(exc.code), exc.user_message, _safe_error_details(exc))
        except Exception as exc:
            return NodeResult.failure(
                "CAPABILITY_EXECUTION_FAILED",
                "YouTube video metadata read failed.",
                {"error": type(exc).__name__},
            )
        return NodeResult.success(_normalize_output(metadata))


def register_youtube_runtime_handlers(
    handler_registry: CapabilityHandlerRegistry,
    *,
    youtube_service: YouTubeChannelService,
    access_tokens_by_install_id: dict[str, str] | None = None,
    access_token_resolver: AccessTokenResolver | None = None,
) -> YouTubeVideoMetadataReadHandler:
    resolver = access_token_resolver or (access_tokens_by_install_id or {}).get
    handler = YouTubeVideoMetadataReadHandler(
        youtube_service=youtube_service,
        access_token_resolver=resolver,
    )
    handler_registry.register(handler)
    return handler


def _validate_input(input_data: dict[str, Any]) -> str:
    allowed = {"_runtime", "video_id"}
    unknown = sorted(set(input_data) - allowed)
    if unknown:
        raise PlaybookExecutionError(
            "YOUTUBE_INPUT_INVALID",
            "YouTube video metadata read accepts only a provider video_id.",
            {"fields": unknown},
        )
    video_id = str(input_data.get("video_id") or "").strip()
    if not YOUTUBE_VIDEO_ID_RE.match(video_id):
        raise PlaybookExecutionError(
            "YOUTUBE_INPUT_INVALID",
            "YouTube video metadata read requires a valid video_id.",
            {"field": "video_id"},
        )
    return video_id


def _runtime_error_code(code: str) -> str:
    if code == "youtube.video_not_found":
        return "YOUTUBE_VIDEO_NOT_FOUND"
    if code == "youtube.rate_limited":
        return "RATE_LIMITED"
    if code == "youtube.authentication_required":
        return "YOUTUBE_AUTHENTICATION_REQUIRED"
    if code == "youtube.response_malformed":
        return "YOUTUBE_RESPONSE_MALFORMED"
    if code in {"youtube.network_error", "youtube.transport_missing"}:
        return "CAPABILITY_EXECUTION_FAILED"
    return "CAPABILITY_EXECUTION_FAILED"


def _safe_error_details(exc: YouTubeChannelError) -> dict[str, Any]:
    details = dict(exc.details or {})
    response = details.get("response")
    if isinstance(response, dict):
        error = response.get("error")
        if isinstance(error, dict) and "message" in error:
            details["provider_message"] = str(error.get("message") or "")
        details.pop("response", None)
    details["provider_error_code"] = exc.code
    return details


def _normalize_output(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "video_id": str(metadata.get("video_id") or ""),
        "title": str(metadata.get("title") or ""),
        "description": str(metadata.get("description") or ""),
        "published_at": str(metadata.get("published_at") or ""),
        "channel_id": str(metadata.get("channel_id") or ""),
        "channel_title": str(metadata.get("channel_title") or ""),
        "privacy_status": str(metadata.get("privacy_status") or ""),
        "processing_status": str(metadata.get("processing_status") or ""),
        "source": YOUTUBE_REMOTE_COMPONENT_ID,
    }
