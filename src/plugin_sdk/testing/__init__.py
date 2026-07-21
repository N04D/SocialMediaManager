"""Public Plugin SDK testkit."""

from .assertions import assert_no_secrets, assert_no_storage_references
from .channel_contract import ChannelPluginContractSuite
from .fakes import (
    FakeAnalyticsIngestion,
    FakeAuditWriter,
    FakeBrowserSession,
    FakeChannelRuntime,
    FakeClock,
    FakeContentService,
    FakeEventPublisher,
    FakeExecutionReporter,
    FakeHttpResponse,
    FakeHttpTransport,
    FakeMaterialization,
    FakeMediaLibrary,
    FakeSecretService,
)

__all__ = [
    "ChannelPluginContractSuite",
    "FakeAnalyticsIngestion",
    "FakeAuditWriter",
    "FakeBrowserSession",
    "FakeChannelRuntime",
    "FakeClock",
    "FakeContentService",
    "FakeEventPublisher",
    "FakeExecutionReporter",
    "FakeHttpResponse",
    "FakeHttpTransport",
    "FakeMaterialization",
    "FakeMediaLibrary",
    "FakeSecretService",
    "assert_no_secrets",
    "assert_no_storage_references",
]
