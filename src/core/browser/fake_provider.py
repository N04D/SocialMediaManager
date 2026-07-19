from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .errors import BrowserInteractionError, BrowserNavigationError, BrowserProviderError
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
        self.provider.raise_if_configured("navigate")
        self.url = url
        self.provider.record(self.session_id, "navigate", {"url": url})
        return self.snapshot()

    def snapshot(self) -> BrowserSnapshot:
        self.provider.record(self.session_id, "snapshot", {"url": self.url})
        return BrowserSnapshot(session_id=self.session_id, url=self.url, title=self._title)

    def current_url(self) -> str:
        return self.url

    def title(self) -> str:
        return self._title

    def element_exists(self, target: BrowserTarget, *, timeout_millis: int = 0) -> bool:
        self.provider.record(self.session_id, "element_exists", {"target": target, "timeout_millis": timeout_millis})
        return self.provider.element_exists_result

    def text_content(self, target: BrowserTarget) -> str:
        self.provider.record(self.session_id, "text_content", {"target": target})
        return self.provider.text_content_result

    def attribute(self, target: BrowserTarget, name: str) -> str:
        self.provider.record(self.session_id, "attribute", {"target": target, "name": name})
        return self.provider.attribute_result

    def wait_for(self, target: BrowserTarget, *, state: str = "visible", timeout_millis: int = 1000) -> bool:
        self.provider.record(
            self.session_id, "wait_for", {"target": target, "state": state, "timeout_millis": timeout_millis}
        )
        return self.element_exists(target, timeout_millis=timeout_millis)

    def wait_for_timeout(self, millis: int) -> None:
        self.provider.record(self.session_id, "wait_for_timeout", {"millis": millis})

    def reload(self) -> BrowserSnapshot:
        self.provider.record(self.session_id, "reload", {})
        return self.snapshot()

    def go_back(self) -> BrowserSnapshot:
        self.provider.record(self.session_id, "go_back", {})
        return self.snapshot()

    def keyboard_press(self, key: str) -> None:
        self.provider.record(self.session_id, "keyboard_press", {"key": key})

    def keyboard_insert_text(self, text: str) -> None:
        self.provider.record(self.session_id, "keyboard_insert_text", {"text": text})

    def click(self, target: BrowserTarget) -> None:
        self.provider.raise_if_configured("click")
        self.provider.record(self.session_id, "click", {"target": target})

    def fill(self, target: BrowserTarget, value: str) -> None:
        self.provider.raise_if_configured("fill")
        self.provider.record(self.session_id, "fill", {"target": target, "value": value})

    def upload(self, target: BrowserTarget, path: Path) -> None:
        self.provider.raise_if_configured("upload")
        self.provider.record(self.session_id, "upload", {"target": target, "path": path})

    def evaluate(self, script: str, arg: Any | None = None) -> Any:
        self.provider.raise_if_configured("evaluate")
        self.provider.record(self.session_id, "evaluate", {"script": script, "arg": arg})
        return self.provider.evaluate_result

    def screenshot(self, *, full_page: bool = True) -> BrowserArtifact:
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


class InMemoryBrowserProvider:
    def __init__(self, *, lock_manager: BrowserProfileLockManager | None = None) -> None:
        self.lock_manager = lock_manager or BrowserProfileLockManager()
        self.sessions: dict[str, InMemoryBrowserSession] = {}
        self.actions: list[RecordedBrowserAction] = []
        self.artifacts: list[BrowserArtifact] = []
        self.failures: dict[str, BrowserProviderError] = {}
        self.evaluate_result: Any = None
        self.element_exists_result = True
        self.text_content_result = ""
        self.attribute_result = ""
        self.takeovers: list[HumanTakeoverRequest] = []

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
