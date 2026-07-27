"""Runtime facade for the built-in Markdown Website channel."""

from __future__ import annotations

from plugin_sdk import (
    ChannelAccountStatus,
    ChannelConnectRequest,
    ChannelConnectResult,
    ChannelDisconnectRequest,
    ChannelDisconnectResult,
    ChannelHealth,
    ChannelHealthRequest,
    ChannelRuntimeBase,
)

from .contracts import MARKDOWN_WEBSITE_PLUGIN_VERSION, PLUGIN_ID
from .profiles import list_profiles


class MarkdownWebsiteChannelRuntime(ChannelRuntimeBase):
    def __init__(self) -> None:
        self.accounts: dict[str, dict[str, object]] = {}

    async def start_connect(self, request: ChannelConnectRequest) -> ChannelConnectResult:
        return ChannelConnectResult(
            "needs_configuration",
            next_action="validate_repository_reference",
            warnings=("configuration_flow_no_oauth",),
        )

    async def complete_connect(self, request) -> ChannelConnectResult:
        self.accounts[request.channel_account_id] = dict(request.metadata)
        return ChannelConnectResult("connected", next_action="none")

    async def disconnect(self, request: ChannelDisconnectRequest) -> ChannelDisconnectResult:
        self.accounts.pop(request.channel_account_id, None)
        return ChannelDisconnectResult("disconnected")

    async def get_status(self, request) -> ChannelAccountStatus:
        configured = request.channel_account_id in self.accounts
        return ChannelAccountStatus("ready" if configured else "unconfigured")

    async def check_session(self, request) -> object:
        return await self.get_status(request)

    async def health_check(self, request: ChannelHealthRequest) -> ChannelHealth:
        return ChannelHealth(
            "ready",
            PLUGIN_ID,
            capabilities={
                "channel_family": "owned_publication",
                "publication_format": "markdown",
                "execution_mode": "built_in_in_process",
            },
            contract_versions={"markdown_website": MARKDOWN_WEBSITE_PLUGIN_VERSION},
            metadata={"profiles": [profile.id for profile in list_profiles()]},
        )
