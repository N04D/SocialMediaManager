from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.browser import BrowserProfileBusyError, BrowserProviderError
from src.core.plugins import PluginCapabilityError
from src.core.plugins.manifest import PluginManifest, PluginStatus


class LinkedInChannelRuntimeError(RuntimeError):
    def __init__(self, code: str, user_message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.details = details or {}


@dataclass
class LinkedInChannelRuntime:
    manifest: PluginManifest
    app_runtime: Any
    config: Any

    service_name = "channel_runtime"

    def _ensure_ready(self) -> None:
        runtime = self.app_runtime.runtimes.get(self.manifest.id)
        if runtime is None or runtime.status != PluginStatus.READY:
            raise LinkedInChannelRuntimeError(
                "linkedin_runtime.not_ready",
                "LinkedIn plugin is not ready.",
                {"plugin_id": self.manifest.id, "status": getattr(runtime, "status", "missing")},
            )

    def browser_provider(self):
        self._ensure_ready()
        preferred_provider_id = str(getattr(self.config, "linkedin_browser_provider_id", "") or "")
        try:
            return self.app_runtime.browser_provider(preferred_provider_id=preferred_provider_id)
        except PluginCapabilityError as exc:
            raise LinkedInChannelRuntimeError(
                exc.code,
                exc.user_message,
                exc.details,
            ) from exc

    def connect(self, *, channel_id: str = "linkedin", action_id: str = "", worker_id: str = "", started_at: str = ""):
        from .worker.connect import run_connect_with_runtime

        return run_connect_with_runtime(
            self.config,
            self.app_runtime,
            channel_id=channel_id,
            action_id=action_id,
            worker_id=worker_id,
            started_at=started_at,
        )

    def disconnect(self, *, channel_id: str = "linkedin") -> None:
        from channel_store import get_channel_connection, now_iso, save_channel_connection

        connection = get_channel_connection(channel_id)
        if connection is None:
            return
        connection.status = "not_configured"
        connection.connected_at = ""
        connection.last_checked_at = now_iso()
        connection.updated_at = now_iso()
        connection.last_error = ""
        save_channel_connection(connection)

    def connection_status(self, *, channel_id: str = "linkedin") -> dict[str, Any]:
        from channel_store import get_channel_connection

        connection = get_channel_connection(channel_id)
        return connection.__dict__ if connection is not None else {"channel_id": channel_id, "status": "disconnected"}

    def check_session(self, *, channel_id: str = "linkedin", worker_id: str = "", started_at: str = ""):
        from .worker.session import run_session_check_with_runtime

        return run_session_check_with_runtime(
            self.config,
            self.app_runtime,
            channel_id=channel_id,
            worker_id=worker_id,
            started_at=started_at,
        )

    def publish(self, job_id: str, *, worker_id: str = "", started_at: str = ""):
        from .worker.publish import run_publish_job_with_runtime

        return run_publish_job_with_runtime(
            self.config,
            self.app_runtime,
            job_id,
            worker_id=worker_id,
            started_at=started_at,
        )

    def collect_metrics(self, job_id: str, *, worker_id: str = "", started_at: str = ""):
        from .worker.metrics import run_metric_job_with_runtime

        return run_metric_job_with_runtime(
            self.config,
            self.app_runtime,
            job_id,
            worker_id=worker_id,
            started_at=started_at,
        )

    def scrape_posts(
        self, *, channel_id: str = "linkedin", worker_id: str = "", started_at: str = ""
    ) -> list[dict[str, Any]]:
        provider = self.browser_provider()
        try:
            with provider.acquire_legacy_execution_session(
                profile_id=channel_id,
                purpose="linkedin.scrape_posts",
                job_id=started_at or worker_id,
                headless=True,
            ) as session:
                session.navigate(str(getattr(self.config, "linkedin_feed_url", "https://www.linkedin.com/feed/")))
                return [{"url": session.current_url(), "title": session.title()}]
        except BrowserProfileBusyError as exc:
            raise LinkedInChannelRuntimeError(exc.code, exc.user_message, exc.details) from exc
        except BrowserProviderError as exc:
            raise LinkedInChannelRuntimeError(exc.code, exc.user_message, exc.details) from exc

    def health_check(self) -> dict[str, Any]:
        provider_id = ""
        provider_available = False
        try:
            provider_runtime = self.app_runtime.resolve_provider("browser.session")
            provider_id = provider_runtime.manifest.id
            provider_available = True
        except Exception:
            provider_available = False
        config_ok = bool(str(getattr(self.config, "linkedin_feed_url", "") or ""))
        return {
            "status": "ready" if provider_available and config_ok else "degraded",
            "dependencies_resolved": provider_available,
            "browser_provider": provider_id,
            "configuration_ok": config_ok,
        }
