"""Deterministic fake application services for Plugin SDK tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..analytics import AnalyticsIngestionResult, ChannelMetricIngestionContext, ChannelMetricObservationInput
from ..assets import MediaMaterialization
from ..auth import SecretReference
from ..channel import ChannelAccountStatus, ChannelConnectResult, ChannelHealth, ChannelPublishResult
from ..errors import PluginSDKError
from ..execution import ExecutionReport


@dataclass
class FakeClock:
    now_value: datetime = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=UTC))

    def now(self) -> datetime:
        return self.now_value


@dataclass
class FakeSecretService:
    secrets: dict[str, str] = field(default_factory=dict)
    history: list[tuple[str, str]] = field(default_factory=list)
    counter: int = 0

    async def put_secret(
        self, plugin_id: str, workspace_id: str, account_id: str, purpose: str, value: str
    ) -> SecretReference:
        self.counter += 1
        ref = f"secret://{plugin_id}/{workspace_id}/{account_id}/{purpose}/{self.counter}"
        self.secrets[ref] = value
        self.history.append(("put", ref))
        return SecretReference(ref, self.counter)

    async def get_secret(self, reference: SecretReference) -> str:
        self.history.append(("get", reference.reference))
        return self.secrets[reference.reference]

    async def revoke_secret(self, reference: SecretReference) -> None:
        self.history.append(("revoke", reference.reference))
        self.secrets.pop(reference.reference, None)

    async def has_secret(self, reference: SecretReference) -> bool:
        self.history.append(("has", reference.reference))
        return reference.reference in self.secrets


@dataclass
class FakeEventPublisher:
    events: list[dict[str, Any]] = field(default_factory=list)

    async def publish(self, event_type: str, metadata: dict[str, Any] | None = None) -> None:
        self.events.append({"type": event_type, "metadata": metadata or {}})


@dataclass
class FakeAuditWriter:
    entries: list[dict[str, Any]] = field(default_factory=list)

    async def write(self, action: str, metadata: dict[str, Any] | None = None) -> None:
        self.entries.append({"action": action, "metadata": metadata or {}})


@dataclass
class FakeContentService:
    history: list[str] = field(default_factory=list)

    async def validate_requirements(self, content: Any, requirements: Any) -> list[str]:
        self.history.append("validate")
        return []

    async def preview(self, content: Any) -> str:
        self.history.append("preview")
        return str(getattr(content, "body", ""))[:120]

    async def revision_identity(self, content: Any) -> dict[str, str]:
        self.history.append("identity")
        return {"revision_id": content.revision_id, "revision_checksum": content.revision_checksum}


@dataclass
class FakeMaterialization:
    materialization: MediaMaterialization
    history: list[str]

    async def __aenter__(self) -> MediaMaterialization:
        self.history.append("enter")
        return self.materialization

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.history.append("cleanup")


@dataclass
class FakeMediaLibrary:
    root: Path = Path("/tmp/plugin-sdk-media")
    history: list[str] = field(default_factory=list)
    fail: str = ""

    def materialize(self, selected_media: Any, purpose: str) -> FakeMaterialization:
        if not purpose:
            raise PluginSDKError("plugin_sdk.media_purpose_required", "Media materialization purpose is required.")
        if self.fail:
            raise PluginSDKError("plugin_sdk.media_failed", "Fake media failure.")
        self.history.append(f"materialize:{purpose}:{selected_media.asset_id}")
        return FakeMaterialization(
            MediaMaterialization(
                path=self.root / f"{selected_media.asset_id}.bin",
                mime_type=selected_media.mime_type,
                checksum=selected_media.checksum,
                size_bytes=10,
                width=selected_media.width,
                height=selected_media.height,
            ),
            self.history,
        )


@dataclass
class FakeAnalyticsIngestion:
    history: list[tuple[tuple[ChannelMetricObservationInput, ...], ChannelMetricIngestionContext]] = field(
        default_factory=list
    )

    async def ingest(
        self,
        observations: Sequence[ChannelMetricObservationInput],
        context: ChannelMetricIngestionContext,
    ) -> AnalyticsIngestionResult:
        self.history.append((tuple(observations), context))
        return AnalyticsIngestionResult("accepted", len(observations))


@dataclass
class FakeExecutionReporter:
    reports: list[ExecutionReport] = field(default_factory=list)
    phase_order: tuple[str, ...] = (
        "preflight",
        "payload_prepared",
        "mutation_started",
        "acknowledged",
        "verified",
        "cleanup",
    )

    async def report_phase(self, phase: str, metadata: dict[str, Any] | None = None) -> None:
        if self.reports and self.reports[-1].kind == "phase":
            previous = self.reports[-1].value
            if (
                previous in self.phase_order
                and phase in self.phase_order
                and self.phase_order.index(phase) < self.phase_order.index(previous)
            ):
                raise PluginSDKError("plugin_sdk.phase_regression", "Execution phase regression rejected.")
        self.reports.append(ExecutionReport("phase", phase, metadata=metadata or {}))

    async def report_mutation_state(self, state: str, metadata: dict[str, Any] | None = None) -> None:
        self.reports.append(ExecutionReport("mutation", state, metadata=metadata or {}))

    async def report_remote_acknowledged(self, remote_id: str, metadata: dict[str, Any] | None = None) -> None:
        self.reports.append(ExecutionReport("ack", remote_id, metadata=metadata or {}))

    async def report_verification(self, state: str, metadata: dict[str, Any] | None = None) -> None:
        self.reports.append(ExecutionReport("verification", state, metadata=metadata or {}))

    async def report_cleanup(self, state: str, metadata: dict[str, Any] | None = None) -> None:
        self.reports.append(ExecutionReport("cleanup", state, metadata=metadata or {}))


@dataclass
class FakeHttpResponse:
    status_code: int
    json_body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class FakeHttpTransport:
    responses: list[FakeHttpResponse] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)

    async def request(self, method: str, url: str, **kwargs: Any) -> FakeHttpResponse:
        self.requests.append({"method": method, "url": url, "kwargs": kwargs})
        if not self.responses:
            return FakeHttpResponse(200, {"ok": True})
        return self.responses.pop(0)


@dataclass
class FakeBrowserSession:
    history: list[str] = field(default_factory=list)

    async def open(self, url: str) -> None:
        self.history.append(f"open:{url}")

    async def takeover(self, reason: str) -> str:
        self.history.append(f"takeover:{reason}")
        return "takeover-fixture"


@dataclass
class FakeChannelRuntime:
    plugin_id: str = "channel.fake"
    mode: str = "ready"
    history: list[str] = field(default_factory=list)

    async def start_connect(self, request: Any) -> ChannelConnectResult:
        self.history.append("start_connect")
        return ChannelConnectResult("started", next_action="none")

    async def complete_connect(self, request: Any) -> ChannelConnectResult:
        self.history.append("complete_connect")
        return ChannelConnectResult("connected")

    async def disconnect(self, request: Any) -> Any:
        self.history.append("disconnect")
        return type("Disconnect", (), {"status": "disconnected", "warnings": (), "safe_error_code": ""})()

    async def get_status(self, request: Any) -> ChannelAccountStatus:
        self.history.append("status")
        return ChannelAccountStatus("connected" if self.mode == "ready" else self.mode)

    async def check_session(self, request: Any) -> Any:
        self.history.append("check_session")
        return type("Session", (), {"status": "connected", "warnings": (), "safe_error_code": ""})()

    async def publish(self, request: Any) -> ChannelPublishResult:
        self.history.append(f"publish:{request.capability}")
        if self.mode == "uncertain":
            return ChannelPublishResult("uncertain", request.publication_id, mutation_state="mutation_uncertain")
        if self.mode != "ready":
            return ChannelPublishResult("failed", request.publication_id, safe_error_code=self.mode)
        now = datetime.now(UTC)
        return ChannelPublishResult(
            "published",
            request.publication_id,
            remote_publication_id="remote-1",
            remote_uri=f"urn:{self.plugin_id}:remote-1",
            remote_url="https://example.invalid/remote-1",
            published_at=now,
            verified_at=now,
            mutation_state="completed",
            verification_state="verified",
            evidence={"publication_id": request.publication_id, "snapshot_checksum": request.snapshot_checksum},
        )

    async def collect_metrics(self, request: Any) -> Any:
        self.history.append("metrics")
        return type("Metrics", (), {"status": "collected", "observations": (), "warnings": (), "safe_error_code": ""})()

    async def health_check(self, request: Any) -> ChannelHealth:
        self.history.append("health")
        return ChannelHealth("ready" if self.mode == "ready" else self.mode, self.plugin_id)


@asynccontextmanager
async def cancellable_delay(seconds: float):
    task = asyncio.create_task(asyncio.sleep(seconds))
    try:
        yield task
    finally:
        task.cancel()


__all__ = [
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
]
