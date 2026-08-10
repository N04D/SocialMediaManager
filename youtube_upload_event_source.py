from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from channels.youtube.transport import YouTubeResponse, YouTubeTransport
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.sources import ExternalEventSource, ExternalSourceRecord, SourceBatch

YOUTUBE_UPLOADS_COMPONENT_ID = "youtube-data-api-uploads"
YOUTUBE_VIDEO_PUBLISHED_EVENT = "youtube.video.published"


@dataclass
class YouTubeUploadsEventSource(ExternalEventSource):
    transport: YouTubeTransport
    access_token_resolver: Callable[[str], str] | None = None
    api_key_resolver: Callable[[str], str] | None = None
    channel_id_resolver: Callable[[str], str] | None = None
    permission_evaluator: Callable[[str, str], bool] | None = None
    max_pages_per_poll: int = 10
    page_size: int = 50
    source_id: str = YOUTUBE_UPLOADS_COMPONENT_ID
    component_id: str = YOUTUBE_UPLOADS_COMPONENT_ID

    def poll(self, install_id: str, checkpoint: str = "", limit: int = 50) -> SourceBatch:
        # 1. Egress/Permission enforcement
        if self.permission_evaluator and not self.permission_evaluator(install_id, "www.googleapis.com:443"):
            raise PlaybookExecutionError(
                "EGRESS_DENIED",
                "Network egress to www.googleapis.com:443 is not permitted.",
                {"install_id": install_id},
            )

        # 2. Auth resolution
        access_token = self.access_token_resolver(install_id) if self.access_token_resolver else ""
        api_key = self.api_key_resolver(install_id) if self.api_key_resolver else ""
        if not access_token and not api_key:
            raise PlaybookExecutionError(
                "AUTH_FAILED",
                "YouTube upload discovery requires a valid access token or API key.",
                {"install_id": install_id},
            )

        # 3. Channel ID resolution
        channel_id = self.channel_id_resolver(install_id) if self.channel_id_resolver else install_id
        if not channel_id:
            raise PlaybookExecutionError(
                "SOURCE_CONFIGURATION_INVALID",
                "YouTube channel ID could not be resolved for install.",
                {"install_id": install_id},
            )

        # 4. Checkpoint parsing
        cp_data: dict[str, Any] = {}
        if checkpoint:
            try:
                cp_data = json.loads(checkpoint)
            except Exception:
                cp_data = {}

        uploads_playlist_id = cp_data.get("uploads_playlist_id", "")
        if not uploads_playlist_id:
            uploads_playlist_id = self._resolve_uploads_playlist(
                channel_id=channel_id, access_token=access_token, api_key=api_key
            )

        latest_published_at = cp_data.get("latest_published_at", "")
        latest_video_ids = set(cp_data.get("latest_video_ids", []))

        effective_page_size = min(limit or self.page_size, 50)

        # 5. First Poll (FROM_NOW policy)
        if not checkpoint or "latest_published_at" not in cp_data:
            resp = self.transport.list_playlist_items(
                playlist_id=uploads_playlist_id,
                max_results=effective_page_size,
                access_token=access_token,
                api_key=api_key,
            )
            items = resp.payload.get("items", [])
            newest_pub_at = ""
            newest_vid_ids = []
            if items:
                first_item = items[0]
                newest_vid_ids = [self._extract_video_id(first_item)]
                newest_pub_at = self._extract_published_at(first_item)

            bootstrap_cp = {
                "uploads_playlist_id": uploads_playlist_id,
                "latest_published_at": newest_pub_at,
                "latest_video_ids": newest_vid_ids,
            }
            new_cp_json = json.dumps(bootstrap_cp, sort_keys=True)
            self._assert_no_secrets(new_cp_json, access_token, api_key)
            return SourceBatch(records=(), next_checkpoint=new_cp_json, has_more=False)

        # 6. Subsequent Polls
        discovered_items: list[dict[str, Any]] = []
        page_token = ""
        boundary_reached = False
        pages_read = 0
        has_more_remote_pages = False

        while pages_read < self.max_pages_per_poll:
            pages_read += 1
            resp = self.transport.list_playlist_items(
                playlist_id=uploads_playlist_id,
                page_token=page_token,
                max_results=effective_page_size,
                access_token=access_token,
                api_key=api_key,
            )
            items = resp.payload.get("items", [])
            page_token = resp.payload.get("nextPageToken", "")

            for item in items:
                vid_id = self._extract_video_id(item)
                pub_at = self._extract_published_at(item)
                privacy = item.get("status", {}).get("privacyStatus", "public")

                # Filter non-public items
                if privacy != "public":
                    continue

                if vid_id in latest_video_ids or (latest_published_at and pub_at <= latest_published_at):
                    boundary_reached = True
                    break

                discovered_items.append({
                    "video_id": vid_id,
                    "published_at": pub_at,
                    "title": item.get("snippet", {}).get("title", ""),
                    "privacy_status": privacy,
                    "raw_item": item,
                })

            if boundary_reached:
                break

            if not page_token:
                break

            has_more_remote_pages = True

        # Gap detection
        if not boundary_reached and page_token and pages_read >= self.max_pages_per_poll:
            # Checkpoint unchanged, signal gap
            return SourceBatch(records=(), next_checkpoint=checkpoint, has_more=False, gap_detected=True)

        if not discovered_items:
            return SourceBatch(records=(), next_checkpoint=checkpoint, has_more=False)

        # Sort discovered items chronological ascending
        discovered_items.sort(key=lambda x: (x["published_at"], x["video_id"]))

        newest_item = discovered_items[-1]
        newest_pub_at = newest_item["published_at"]
        newest_vids = [item["video_id"] for item in discovered_items if item["published_at"] == newest_pub_at]

        updated_cp = {
            "uploads_playlist_id": uploads_playlist_id,
            "latest_published_at": newest_pub_at,
            "latest_video_ids": newest_vids,
        }
        next_cp_json = json.dumps(updated_cp, sort_keys=True)

        records: list[ExternalSourceRecord] = []
        for item in discovered_items:
            vid_id = item["video_id"]
            pub_at = item["published_at"]
            resource_ref = f"youtube:video:{vid_id}"
            rec_payload = {
                "video_id": vid_id,
                "channel_id": channel_id,
                "title": item["title"],
                "published_at": pub_at,
                "privacy_status": item["privacy_status"],
                "resource_ref": resource_ref,
            }
            rec = ExternalSourceRecord(
                external_event_id=f"yt_pub_{vid_id}",
                event_type=YOUTUBE_VIDEO_PUBLISHED_EVENT,
                occurred_at=pub_at,
                payload=rec_payload,
                resource_ref=resource_ref,
            )
            self._assert_no_secrets(json.dumps(rec_payload), access_token, api_key)
            records.append(rec)

        self._assert_no_secrets(next_cp_json, access_token, api_key)
        return SourceBatch(records=tuple(records), next_checkpoint=next_cp_json, has_more=has_more_remote_pages)

    def _resolve_uploads_playlist(self, *, channel_id: str, access_token: str, api_key: str) -> str:
        resp = self.transport.get_channel_uploads_playlist(
            channel_id=channel_id, access_token=access_token, api_key=api_key
        )
        items = resp.payload.get("items", [])
        if not items:
            raise PlaybookExecutionError(
                "SOURCE_CONFIGURATION_INVALID",
                "YouTube channel metadata was not found for uploads playlist resolution.",
                {"channel_id": channel_id},
            )
        try:
            return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        except (KeyError, IndexError) as exc:
            raise PlaybookExecutionError(
                "SOURCE_CONFIGURATION_INVALID",
                "Uploads playlist missing from YouTube channel response.",
                {"channel_id": channel_id},
            ) from exc

    def _extract_video_id(self, item: dict[str, Any]) -> str:
        if "contentDetails" in item and "videoId" in item["contentDetails"]:
            return item["contentDetails"]["videoId"]
        if "snippet" in item and "resourceId" in item["snippet"]:
            return item["snippet"]["resourceId"].get("videoId", "")
        return item.get("id", "")

    def _extract_published_at(self, item: dict[str, Any]) -> str:
        if "contentDetails" in item and "videoPublishedAt" in item["contentDetails"]:
            return item["contentDetails"]["videoPublishedAt"]
        if "snippet" in item and "publishedAt" in item["snippet"]:
            return item["snippet"]["publishedAt"]
        return ""

    def _assert_no_secrets(self, text: str, access_token: str, api_key: str) -> None:
        if access_token and len(access_token) > 5 and access_token in text:
            raise PlaybookExecutionError(
                "SECRET_LEAK_PREVENTED",
                "Access token was detected inside event output.",
            )
        if api_key and len(api_key) > 5 and api_key in text:
            raise PlaybookExecutionError(
                "SECRET_LEAK_PREVENTED",
                "API key was detected inside event output.",
            )
