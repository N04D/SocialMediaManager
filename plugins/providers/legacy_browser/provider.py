from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from src.core.browser import (
    BrowserArtifact,
    BrowserInteractionError,
    BrowserProfileStatus,
    BrowserProviderError,
    BrowserSessionOptions,
    BrowserSnapshot,
    BrowserTarget,
    BrowserUnavailableError,
    HumanTakeoverRequest,
)


class LegacyBrowserSession:
    def __init__(
        self,
        *,
        session_id: str,
        playwright: Any,
        browser: Any,
        context: Any,
        page: Any,
        owns_session: bool,
        session_label: str,
        on_close: Callable[[str], None],
    ) -> None:
        self._session_id = session_id
        self.playwright = playwright
        self.browser = browser
        self.context = context
        self.page = page
        self.owns_session = owns_session
        self.session_label = session_label
        self._on_close = on_close
        self.closed = False

    @property
    def session_id(self) -> str:
        return self._session_id

    def navigate(self, url: str) -> BrowserSnapshot:
        self.page.goto(url, wait_until="domcontentloaded")
        return self.snapshot()

    def snapshot(self) -> BrowserSnapshot:
        title = ""
        try:
            title = str(self.page.title())
        except Exception:
            title = ""
        return BrowserSnapshot(session_id=self.session_id, url=str(getattr(self.page, "url", "")), title=title)

    def click(self, target: BrowserTarget) -> None:
        self._locator(target).click()

    def fill(self, target: BrowserTarget, value: str) -> None:
        self._locator(target).fill(value)

    def upload(self, target: BrowserTarget, path: Path) -> None:
        self._locator(target).set_input_files(str(path))

    def evaluate(self, script: str, arg: Any | None = None) -> Any:
        if arg is None:
            return self.page.evaluate(script)
        return self.page.evaluate(script, arg)

    def screenshot(self, *, full_page: bool = True) -> BrowserArtifact:
        artifact_path = Path(f"/tmp/{self.session_id}.png")
        self.page.screenshot(path=str(artifact_path), full_page=full_page)
        return BrowserArtifact(
            id=f"artifact_{uuid4().hex}",
            kind="screenshot",
            path=artifact_path,
            content_type="image/png",
            metadata={"full_page": full_page},
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if self.owns_session and self.context is not None:
                self.context.close()
        finally:
            try:
                if self.playwright is not None:
                    self.playwright.stop()
            finally:
                self._on_close(self.session_id)

    def _locator(self, target: BrowserTarget):
        if target.role:
            name = target.accessible_name or target.text or None
            return self.page.get_by_role(target.role, name=name)
        if target.label:
            return self.page.get_by_label(target.label)
        if target.text:
            return self.page.get_by_text(target.text)
        if target.test_id:
            return self.page.get_by_test_id(target.test_id)
        if target.css:
            return self.page.locator(target.css)
        if target.xpath:
            return self.page.locator(f"xpath={target.xpath}")
        raise BrowserInteractionError(
            "browser_target.unsupported",
            "Browser target does not include a supported locator strategy.",
        )


class LegacyBrowserProvider:
    def __init__(
        self,
        *,
        config: Any,
        channel_id: str = "linkedin",
        headed_default: bool = True,
        allow_remote_debugging: bool = True,
        require_remote_debugging: bool = False,
        open_session: Callable[..., tuple[Any, Any, Any, Any, bool, str]] | None = None,
    ) -> None:
        self.config = config
        self.channel_id = channel_id
        self.headed_default = headed_default
        self.allow_remote_debugging = allow_remote_debugging
        self.require_remote_debugging = require_remote_debugging
        self.open_session = open_session
        self.sessions: dict[str, LegacyBrowserSession] = {}

    def create_session(self, options: BrowserSessionOptions) -> LegacyBrowserSession:
        try:
            open_session = self.open_session
            if open_session is None:
                from channels.linkedin.worker.browser import open_local_linkedin_session as open_session

            playwright, browser, context, page, owns_session, session_label = open_session(
                self.config,
                headed_default=not options.headless,
                allow_remote_debugging=self.allow_remote_debugging,
                require_remote_debugging=self.require_remote_debugging,
            )
        except Exception as exc:
            raise BrowserUnavailableError(
                "legacy_browser.session_unavailable",
                "Could not open the configured browser session.",
                {"error": str(exc), "profile_id": options.profile_id},
            ) from exc

        session = LegacyBrowserSession(
            session_id=f"legacy_{uuid4().hex}",
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
            owns_session=owns_session,
            session_label=session_label,
            on_close=self.sessions.pop,
        )
        self.sessions[session.session_id] = session
        if options.start_url:
            session.navigate(options.start_url)
        return session

    def close_session(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is not None:
            session.close()

    def get_session(self, session_id: str) -> LegacyBrowserSession | None:
        return self.sessions.get(session_id)

    def profile_status(self, profile_id: str) -> BrowserProfileStatus:
        try:
            from channels.linkedin.worker.browser import profile_lock_state

            state = profile_lock_state(self.channel_id)
        except Exception as exc:
            return BrowserProfileStatus(
                profile_id=profile_id,
                available=False,
                message=f"Could not inspect browser profile: {exc}",
            )
        return BrowserProfileStatus(
            profile_id=profile_id,
            available=not bool(state.get("busy")),
            busy=bool(state.get("busy")),
            owner=str(state.get("owner") or ""),
            lock_path=str(state.get("lock_path") or ""),
        )

    def health_check(self) -> dict[str, Any]:
        status = self.profile_status(self.channel_id)
        return {
            "ok": status.available or status.busy,
            "provider": "legacy_browser",
            "profile": status.__dict__,
            "sessions": len(self.sessions),
        }

    def request_human_takeover(self, request: HumanTakeoverRequest) -> dict[str, Any]:
        if request.session_id not in self.sessions:
            raise BrowserProviderError(
                "legacy_browser.session_missing",
                "Browser session is no longer available for human takeover.",
                {"session_id": request.session_id},
            )
        return {"status": "requested", "session_id": request.session_id, "reason": request.reason}
