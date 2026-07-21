from __future__ import annotations

from plugin_sdk import (
    ChannelAccountStatus,
    ChannelHealth,
    ChannelHealthRequest,
    ChannelPublishRequest,
    ChannelPublishResult,
    ChannelRuntimeBase,
    ChannelRuntimeContext,
)


class ExampleChannelRuntime(ChannelRuntimeBase):
    def __init__(self, plugin_id: str, context: ChannelRuntimeContext) -> None:
        self.plugin_id = plugin_id
        self.context = context

    async def get_status(self, request):
        return ChannelAccountStatus("unconfigured")

    async def health_check(self, request: ChannelHealthRequest) -> ChannelHealth:
        return ChannelHealth(
            "unconfigured", self.plugin_id, metadata={"mode": "api-first", "note": "external API transport placeholder"}
        )

    async def publish(self, request: ChannelPublishRequest) -> ChannelPublishResult:
        return ChannelPublishResult("failed", request.publication_id, safe_error_code="not_configured")
