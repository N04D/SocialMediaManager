from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from src.core.browser import (
    BrowserArtifact,
    BrowserInteractionError,
    BrowserNavigationError,
    BrowserProviderError,
    BrowserSessionError,
    BrowserSessionStatus,
    BrowserSnapshot,
    BrowserTarget,
)

from .artifacts import artifact_from_remote
from .errors import AutoBrowserError, AutoBrowserTargetNotFoundError
from .models import AutoBrowserSessionMapping
from .target_resolver import AutoBrowserTargetResolver
from .transport import AutoBrowserTransport


class AutoBrowserSession:
    def __init__(
        self,
        *,
        mapping: AutoBrowserSessionMapping,
        transport: AutoBrowserTransport,
        target_resolver: AutoBrowserTargetResolver,
        on_close,
    ) -> None:
        self.mapping = mapping
        self.transport = transport
        self.target_resolver = target_resolver
        self.status = BrowserSessionStatus.ACTIVE
        self._on_close = on_close
        self._closed = False

    @property
    def session_id(self) -> str:
        return self.mapping.local_session_id

    @property
    def remote_session_id(self) -> str:
        return self.mapping.remote_session_id

    def navigate(self, url: str) -> BrowserSnapshot:
        self._ensure_open()
        try:
            self.transport.navigate(self.remote_session_id, url)
            return self.snapshot()
        except AutoBrowserError as exc:
            raise BrowserNavigationError(exc.code, "Could not navigate the browser session.", exc.details) from exc

    def snapshot(self) -> BrowserSnapshot:
        self._ensure_open()
        observation = self._observe()
        return BrowserSnapshot(
            session_id=self.session_id,
            url=str(observation.get("url") or observation.get("current_url") or ""),
            title=str(observation.get("title") or ""),
            text=str(observation.get("text") or ""),
            metadata={
                "provider_id": self.mapping.provider_id,
                "remote_status": str(observation.get("status") or ""),
            },
        )

    def current_url(self) -> str:
        return self.snapshot().url

    def title(self) -> str:
        return self.snapshot().title

    def element_exists(self, target: BrowserTarget, *, timeout_millis: int = 0) -> bool:
        try:
            return self.count(target) > 0
        except BrowserInteractionError:
            return False

    def element_visible(self, target: BrowserTarget, *, timeout_millis: int = 0) -> bool:
        try:
            return self.target_resolver.resolve(self._observe(), target).visible
        except (AutoBrowserTargetNotFoundError, BrowserInteractionError):
            return False

    def element_enabled(self, target: BrowserTarget, *, timeout_millis: int = 0) -> bool:
        try:
            return self.target_resolver.resolve(self._observe(), target).enabled
        except (AutoBrowserTargetNotFoundError, BrowserInteractionError):
            return False

    def count(self, target: BrowserTarget) -> int:
        self._ensure_open()
        try:
            return len(self.target_resolver.matches(self._observe(), target))
        except AutoBrowserError as exc:
            raise BrowserInteractionError(exc.code, "Could not count browser targets.", exc.details) from exc

    def text_content(self, target: BrowserTarget) -> str:
        element = self._resolve(target)
        return element.text

    def attribute(self, target: BrowserTarget, name: str) -> str:
        element = self._resolve(target)
        return str(element.attributes.get(name, ""))

    def wait_for(self, target: BrowserTarget, *, state: str = "visible", timeout_millis: int = 1000) -> bool:
        deadline = time.monotonic() + (timeout_millis / 1000)
        while True:
            if state == "attached" and self.element_exists(target):
                return True
            if state == "visible" and self.element_visible(target):
                return True
            if state == "enabled" and self.element_enabled(target):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def wait_for_timeout(self, millis: int) -> None:
        self._ensure_open()
        self.transport.perform_action(self.remote_session_id, "wait", {"timeout_millis": int(millis)})

    def reload(self) -> BrowserSnapshot:
        self._ensure_open()
        self.transport.perform_action(self.remote_session_id, "reload")
        return self.snapshot()

    def go_back(self) -> BrowserSnapshot:
        self._ensure_open()
        self.transport.perform_action(self.remote_session_id, "go_back")
        return self.snapshot()

    def keyboard_press(self, key: str) -> None:
        self._ensure_open()
        self.transport.perform_action(self.remote_session_id, "keyboard_press", {"key": key})

    def keyboard_insert_text(self, text: str) -> None:
        self._ensure_open()
        self.transport.perform_action(
            self.remote_session_id, "keyboard_insert_text", {"text": text, "sensitive": False}
        )

    def click(self, target: BrowserTarget) -> None:
        element = self._resolve(target)
        self._action("click", {"element_id": element.element_id})

    def clear(self, target: BrowserTarget) -> None:
        element = self._resolve(target)
        self._action("clear", {"element_id": element.element_id, "text": "", "clear_first": True})

    def hover(self, target: BrowserTarget) -> None:
        element = self._resolve(target)
        self._action("hover", {"element_id": element.element_id})

    def fill(self, target: BrowserTarget, value: str) -> None:
        element = self._resolve(target)
        self._action("fill", {"element_id": element.element_id, "text": value, "clear_first": True, "sensitive": False})

    def upload(self, target: BrowserTarget, path: Path) -> None:
        self._ensure_open()
        resolved = Path(path).resolve()
        if not resolved.is_file():
            raise BrowserInteractionError(
                "browser_interaction.upload_missing_file",
                "Upload file is not available.",
                {"path": str(path)},
            )
        if resolved.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            raise BrowserInteractionError(
                "browser_interaction.upload_type_blocked", "Upload file type is not supported."
            )
        if resolved.stat().st_size > 25_000_000:
            raise BrowserInteractionError("browser_interaction.upload_too_large", "Upload file is too large.")
        element = self._resolve(target)
        self._action("upload", {"element_id": element.element_id, "file_path": str(resolved), "approved": True})

    def wait_for_load_state(self, state: str = "domcontentloaded", *, timeout_millis: int = 10000) -> None:
        self.wait_for_timeout(min(timeout_millis, 1000))

    def evaluate(self, script: str, arg: Any | None = None) -> Any:
        self._ensure_open()
        try:
            return self.transport.evaluate(self.remote_session_id, script, arg)
        except AutoBrowserError as exc:
            raise BrowserInteractionError(
                exc.code, "Could not evaluate controlled browser script.", exc.details
            ) from exc

    def screenshot(self, *, full_page: bool = True) -> BrowserArtifact:
        self._ensure_open()
        try:
            payload = self.transport.screenshot(self.remote_session_id, full_page=full_page)
            return artifact_from_remote(
                payload if isinstance(payload, dict) else {},
                provider_id=self.mapping.provider_id,
                session_id=self.session_id,
                job_id=self.mapping.job_id,
            )
        except AutoBrowserError as exc:
            raise BrowserInteractionError(exc.code, "Could not capture browser screenshot.", exc.details) from exc

    def close(self) -> None:
        if self._closed:
            return
        self.status = BrowserSessionStatus.CLOSING
        try:
            self.transport.close_session(self.remote_session_id)
        except AutoBrowserError:
            pass
        finally:
            self._closed = True
            self.status = BrowserSessionStatus.CLOSED
            self._on_close(self.session_id)

    def _observe(self) -> dict[str, Any]:
        try:
            return self.transport.observe(self.remote_session_id)
        except AutoBrowserError as exc:
            raise BrowserInteractionError(exc.code, "Could not observe browser session.", exc.details) from exc

    def _resolve(self, target: BrowserTarget):
        self._ensure_open()
        try:
            return self.target_resolver.resolve(self._observe(), target)
        except AutoBrowserTargetNotFoundError as exc:
            raise BrowserInteractionError(exc.code, "Browser target was not found.", exc.details) from exc
        except BrowserProviderError:
            raise
        except AutoBrowserError as exc:
            raise BrowserInteractionError(exc.code, "Could not resolve browser target.", exc.details) from exc

    def _action(self, action: str, payload: dict[str, Any]) -> None:
        self._ensure_open()
        try:
            self.transport.perform_action(self.remote_session_id, action, payload)
        except AutoBrowserError as exc:
            raise BrowserInteractionError(exc.code, "Could not complete browser interaction.", exc.details) from exc

    def _ensure_open(self) -> None:
        if self._closed or self.status == BrowserSessionStatus.CLOSED:
            raise BrowserSessionError(
                "browser_session.closed", "Browser session is already closed.", {"session_id": self.session_id}
            )
