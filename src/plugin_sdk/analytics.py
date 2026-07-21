"""Analytics facade contracts for channel plugins."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class ChannelMetricObservationInput:
    """Generic metric observation submitted by a channel plugin."""

    plugin_id: str
    metric_key: str
    value: int | float
    observed_at: datetime
    publication_id: str
    remote_publication_id: str = ""
    remote_uri: str = ""
    measurement_window: str = "lifetime"
    source_version: str = "1"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelMetricIngestionContext:
    workspace_id: str
    channel_account_id: str
    collection_run_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalyticsIngestionResult:
    status: str
    accepted: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)


class ChannelAnalyticsFacade(Protocol):
    """Ingestion-only analytics surface."""

    async def ingest(
        self,
        observations: Sequence[ChannelMetricObservationInput],
        context: ChannelMetricIngestionContext,
    ) -> AnalyticsIngestionResult:
        """Ingest channel observations without repository access."""


__all__ = [
    "AnalyticsIngestionResult",
    "ChannelAnalyticsFacade",
    "ChannelMetricIngestionContext",
    "ChannelMetricObservationInput",
]
