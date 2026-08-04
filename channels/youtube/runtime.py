from __future__ import annotations

from typing import Any

import channel_store
from src.core.plugins.manifest import PluginManifest

from .channel import YouTubeChannelService
from .transport import HttpYouTubeTransport


class YouTubeChannelRuntime:
    service_name = "channel_runtime"

    def __init__(self, *, manifest: PluginManifest, app_runtime: Any, config: Any, transport: Any | None = None):
        self.manifest = manifest
        self.app_runtime = app_runtime
        self.config = config
        self.transport = transport or HttpYouTubeTransport()
        self.service = YouTubeChannelService(
            config=config,
            transport=self.transport,
            session_store_path=channel_store.STUDIO_DATA_DIR / "youtube_upload_sessions.json",
            secret_reader=getattr(config, "youtube_secret_reader", None),
        )

    def health_check(self, *, channel_account_id: str = ""):
        return self.service.health_check(channel_account_id=channel_account_id)

    def start_connect(self, **kwargs):
        return self.service.start_connect(**kwargs)

    def complete_connect(self, **kwargs):
        return self.service.complete_connect(**kwargs)

    def connection_status(self, channel_account_id: str = ""):
        return self.service.connection_status(channel_account_id)

    def publish(self, plan, *, confirmation: str = "", access_token: str = ""):
        return self.service.publish(plan, confirmation=confirmation, access_token=access_token)
