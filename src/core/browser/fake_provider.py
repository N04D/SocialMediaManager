from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .errors import BrowserInteractionError, BrowserNavigationError, BrowserProviderError, BrowserSessionError
from .locks import BrowserProfileLock, BrowserProfileLockManager
from .models import (
    BrowserArtifact,
    BrowserProfileStatus,
    BrowserSessionOptions,
    BrowserSessionStatus,
    BrowserSnapshot,
    BrowserTarget,
    HumanTakeoverRequest,
)


@dataclass
class RecordedBrowserAction:
    session_id: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)


class InMemoryBrowserSession:
    def __init__(
        self,
        *,
        session_id: str,
        options: BrowserSessionOptions,
        provider: InMemoryBrowserProvider,
        profile_lock: BrowserProfileLock | None,
    ) -> None:
        self._session_id = session_id
        self.options = options
        self.provider = provider
        self.profile_lock = profile_lock
        self.status = BrowserSessionStatus.READY
        self.url = options.start_url or "about:blank"
        self._title = ""

    @property
    def session_id(self) -> str:
        return self._session_id

    def navigate(self, url: str) -> BrowserSnapshot:
        self._ensure_open()
        self.provider.raise_if_configured("navigate")
        self.provider.navigation_history.append(url)
        self.url = self.provider.navigation_redirects.get(url, url)
        self.provider.record(self.session_id, "navigate", {"url": url})
        return self.snapshot()

    def snapshot(self) -> BrowserSnapshot:
        self._ensure_open()
        self.provider.record(self.session_id, "snapshot", {"url": self.url})
        return BrowserSnapshot(
            session_id=self.session_id, url=self.url, title=self._title, text="\n".join(self.provider.visible_strings)
        )

    def current_url(self) -> str:
        self._ensure_open()
        return self.url

    def title(self) -> str:
        self._ensure_open()
        return self._title

    def element_exists(self, target: BrowserTarget, *, timeout_millis: int = 0) -> bool:
        self._ensure_open()
        self.provider.record(self.session_id, "element_exists", {"target": target, "timeout_millis": timeout_millis})
        state = self.provider.element_state(target)
        return bool(state.get("exists", self.provider.element_exists_result))

    def element_visible(self, target: BrowserTarget, *, timeout_millis: int = 0) -> bool:
        self._ensure_open()
        self.provider.record(self.session_id, "element_visible", {"target": target, "timeout_millis": timeout_millis})
        state = self.provider.element_state(target)
        return bool(state.get("visible", state.get("exists", self.provider.element_exists_result)))

    def element_enabled(self, target: BrowserTarget, *, timeout_millis: int = 0) -> bool:
        self._ensure_open()
        self.provider.record(self.session_id, "element_enabled", {"target": target, "timeout_millis": timeout_millis})
        state = self.provider.element_state(target)
        return bool(state.get("enabled", state.get("exists", self.provider.element_exists_result)))

    def count(self, target: BrowserTarget) -> int:
        self._ensure_open()
        self.provider.record(self.session_id, "count", {"target": target})
        state = self.provider.element_state(target)
        return int(state.get("count", 1 if state.get("exists", self.provider.element_exists_result) else 0))

    def text_content(self, target: BrowserTarget) -> str:
        self._ensure_open()
        self.provider.record(self.session_id, "text_content", {"target": target})
        state = self.provider.element_state(target)
        return str(state.get("text", self.provider.text_content_result))

    def attribute(self, target: BrowserTarget, name: str) -> str:
        self._ensure_open()
        self.provider.record(self.session_id, "attribute", {"target": target, "name": name})
        state = self.provider.element_state(target)
        attributes = state.get("attributes", {})
        if isinstance(attributes, dict) and name in attributes:
            return str(attributes[name])
        return self.provider.attribute_result

    def wait_for(self, target: BrowserTarget, *, state: str = "visible", timeout_millis: int = 1000) -> bool:
        self._ensure_open()
        self.provider.record(
            self.session_id, "wait_for", {"target": target, "state": state, "timeout_millis": timeout_millis}
        )
        return self.element_exists(target, timeout_millis=timeout_millis)

    def wait_for_timeout(self, millis: int) -> None:
        self._ensure_open()
        self.provider.record(self.session_id, "wait_for_timeout", {"millis": millis})

    def reload(self) -> BrowserSnapshot:
        self._ensure_open()
        self.provider.record(self.session_id, "reload", {})
        return self.snapshot()

    def go_back(self) -> BrowserSnapshot:
        self._ensure_open()
        self.provider.record(self.session_id, "go_back", {})
        if len(self.provider.navigation_history) >= 2:
            self.url = self.provider.navigation_history[-2]
        return self.snapshot()

    def keyboard_press(self, key: str) -> None:
        self._ensure_open()
        self.provider.record(self.session_id, "keyboard_press", {"key": key})

    def keyboard_insert_text(self, text: str) -> None:
        self._ensure_open()
        self.provider.record(self.session_id, "keyboard_insert_text", {"text": text})

    def click(self, target: BrowserTarget) -> None:
        self._ensure_open()
        self.provider.raise_if_configured("click")
        self.provider.record(self.session_id, "click", {"target": target})
        self.provider.clicked_targets.append(target)

    def fill(self, target: BrowserTarget, value: str) -> None:
        self._ensure_open()
        self.provider.raise_if_configured("fill")
        self.provider.record(self.session_id, "fill", {"target": target, "value": value})
        self.provider.filled_targets.append((target, value))

    def clear(self, target: BrowserTarget) -> None:
        self._ensure_open()
        self.provider.raise_if_configured("clear")
        self.provider.record(self.session_id, "clear", {"target": target})

    def hover(self, target: BrowserTarget) -> None:
        self._ensure_open()
        self.provider.raise_if_configured("hover")
        self.provider.record(self.session_id, "hover", {"target": target})

    def upload(self, target: BrowserTarget, path: Path) -> None:
        self._ensure_open()
        self.provider.raise_if_configured("upload")
        self.provider.record(self.session_id, "upload", {"target": target, "path": path})
        self.provider.uploads.append((target, path))

    def evaluate(self, script: str, arg: Any | None = None) -> Any:
        self._ensure_open()
        self.provider.raise_if_configured("evaluate")
        self.provider.record(self.session_id, "evaluate", {"script": script, "arg": arg})
        if self.provider.evaluate_results:
            return self.provider.evaluate_results.pop(0)
        return self.provider.evaluate_result

    def wait_for_load_state(self, state: str = "domcontentloaded", *, timeout_millis: int = 10000) -> None:
        self._ensure_open()
        self.provider.record(self.session_id, "wait_for_load_state", {"state": state, "timeout_millis": timeout_millis})

    def screenshot(self, *, full_page: bool = True) -> BrowserArtifact:
        self._ensure_open()
        self.provider.raise_if_configured("screenshot")
        artifact = BrowserArtifact(
            id=f"artifact_{uuid4().hex}",
            kind="screenshot",
            path=Path(f"/tmp/{self.session_id}.png"),
            content_type="image/png",
            metadata={"full_page": full_page},
        )
        self.provider.artifacts.append(artifact)
        self.provider.record(self.session_id, "screenshot", {"artifact_id": artifact.id})
        return artifact

    def close(self) -> None:
        if self.status == BrowserSessionStatus.CLOSED:
            return
        self.status = BrowserSessionStatus.CLOSED
        self.provider.record(self.session_id, "close", {})
        if self.profile_lock is not None:
            self.profile_lock.release()
        self.provider.sessions.pop(self.session_id, None)

    def _ensure_open(self) -> None:
        if self.status == BrowserSessionStatus.CLOSED:
            raise BrowserSessionError(
                "browser_session.closed",
                "Browser session is already closed.",
                {"session_id": self.session_id},
            )


class InMemoryBrowserProvider:
    def __init__(self, *, lock_manager: BrowserProfileLockManager | None = None) -> None:
        self.lock_manager = lock_manager or BrowserProfileLockManager()
        self.sessions: dict[str, InMemoryBrowserSession] = {}
        self.actions: list[RecordedBrowserAction] = []
        self.artifacts: list[BrowserArtifact] = []
        self.failures: dict[str, BrowserProviderError] = {}
        self.evaluate_result: Any = None
        self.evaluate_results: list[Any] = []
        self.element_exists_result = True
        self.text_content_result = ""
        self.attribute_result = ""
        self.element_states: dict[str, dict[str, Any]] = {}
        self.visible_strings: list[str] = []
        self.navigation_history: list[str] = []
        self.navigation_redirects: dict[str, str] = {}
        self.clicked_targets: list[BrowserTarget] = []
        self.filled_targets: list[tuple[BrowserTarget, str]] = []
        self.uploads: list[tuple[BrowserTarget, Path]] = []
        self.takeovers: list[HumanTakeoverRequest] = []

    def configure_element(self, target: BrowserTarget, **state: Any) -> None:
        self.element_states[self.target_key(target)] = dict(state)

    def element_state(self, target: BrowserTarget) -> dict[str, Any]:
        return dict(self.element_states.get(self.target_key(target), {}))

    def target_key(self, target: BrowserTarget) -> str:
        return "|".join(
            [
                target.role,
                target.accessible_name,
                target.text,
                target.label,
                target.test_id,
                target.placeholder,
                target.title,
                target.alt_text,
                target.stable_attribute,
                target.stable_attribute_value,
                target.css,
                target.xpath,
                str(target.index),
            ]
        )

    def create_session(self, options: BrowserSessionOptions) -> InMemoryBrowserSession:
        profile_lock = None
        if options.exclusive:
            profile_lock = self.lock_manager.acquire(options.profile_id, owner=f"session:{uuid4().hex}")
        try:
            self.raise_if_configured("create_session")
            session = InMemoryBrowserSession(
                session_id=f"session_{uuid4().hex}",
                options=options,
                provider=self,
                profile_lock=profile_lock,
            )
            self.sessions[session.session_id] = session
            self.record(session.session_id, "create_session", {"profile_id": options.profile_id})
            if options.start_url:
                session.navigate(options.start_url)
            return session
        except Exception:
            if profile_lock is not None:
                profile_lock.release()
            raise

    def close_session(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is not None:
            session.close()

    def get_session(self, session_id: str) -> InMemoryBrowserSession | None:
        return self.sessions.get(session_id)

    def profile_status(self, profile_id: str) -> BrowserProfileStatus:
        status = self.lock_manager.status(profile_id)
        return BrowserProfileStatus(
            profile_id=profile_id,
            available=not bool(status["busy"]),
            busy=bool(status["busy"]),
            stale=bool(status["stale"]),
            owner=str(status["owner"]),
            lock_path=str(status["lock_path"]),
        )

    def health_check(self) -> dict[str, Any]:
        return {"ok": "health_check" not in self.failures, "sessions": len(self.sessions)}

    def request_human_takeover(self, request: HumanTakeoverRequest) -> dict[str, Any]:
        self.raise_if_configured("human_takeover")
        self.takeovers.append(request)
        session = self.sessions.get(request.session_id)
        if session is not None:
            session.status = BrowserSessionStatus.HUMAN_TAKEOVER
        return {"status": "requested", "session_id": request.session_id, "reason": request.reason}

    def simulate_failure(self, action: str, error: BrowserProviderError | None = None) -> None:
        default_error = BrowserProviderError(
            "browser_provider.simulated_failure",
            "Browser provider simulated a failure.",
            {"action": action},
        )
        self.failures[action] = error or default_error

    def clear_failure(self, action: str) -> None:
        self.failures.pop(action, None)

    def raise_if_configured(self, action: str) -> None:
        error = self.failures.get(action)
        if error is not None:
            if action == "navigate" and type(error) is BrowserProviderError:
                raise BrowserNavigationError(error.code, error.user_message, error.details)
            if action in {"click", "fill", "upload"} and type(error) is BrowserProviderError:
                raise BrowserInteractionError(error.code, error.user_message, error.details)
            raise error

    def record(self, session_id: str, action: str, payload: dict[str, Any]) -> None:
        self.actions.append(RecordedBrowserAction(session_id=session_id, action=action, payload=payload))
