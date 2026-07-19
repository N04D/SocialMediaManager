from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import channel_store
from src.core.browser import (
    BrowserArtifact,
    BrowserInteractionError,
    BrowserProfileBusyError,
    BrowserProfileLock,
    BrowserProfileStatus,
    BrowserProviderError,
    BrowserSessionOptions,
    BrowserSessionStatus,
    BrowserSnapshot,
    BrowserTarget,
    BrowserUnavailableError,
    FileBackedBrowserProfileLockManager,
    HumanTakeoverRequest,
    HumanTakeoverStatus,
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
        profile_lock: BrowserProfileLock | None,
        on_close: Callable[[str], None],
    ) -> None:
        self._session_id = session_id
        self.playwright = playwright
        self.browser = browser
        self.context = context
        self.page = page
        self.owns_session = owns_session
        self.session_label = session_label
        self.profile_lock = profile_lock
        self.status = BrowserSessionStatus.ACTIVE
        self.takeover_status = HumanTakeoverStatus.NOT_REQUIRED
        self._on_close = on_close
        self.closed = False

    @property
    def session_id(self) -> str:
        return self._session_id

    def navigate(self, url: str) -> BrowserSnapshot:
        try:
            self.page.goto(url, wait_until="domcontentloaded")
            return self.snapshot()
        except Exception as exc:
            raise BrowserUnavailableError(
                "browser_navigation.failed",
                "Could not navigate the browser session.",
                {"error": str(exc), "url": url},
            ) from exc

    def snapshot(self) -> BrowserSnapshot:
        return BrowserSnapshot(
            session_id=self.session_id,
            url=self.current_url(),
            title=self.title(),
            metadata={"browser_session_status": self.status.value, "human_takeover_status": self.takeover_status.value},
        )

    def current_url(self) -> str:
        try:
            return str(getattr(self.page, "url", "") or "")
        except Exception:
            return ""

    def title(self) -> str:
        try:
            return str(self.page.title())
        except Exception:
            return ""

    def element_exists(self, target: BrowserTarget, *, timeout_millis: int = 0) -> bool:
        try:
            locator = self._locator(target)
            if timeout_millis > 0:
                try:
                    locator.first.wait_for(state="visible", timeout=timeout_millis)
                    return True
                except Exception:
                    return False
            return bool(locator.count())
        except Exception:
            return False

    def text_content(self, target: BrowserTarget) -> str:
        try:
            return str(self._locator(target).first.inner_text())
        except Exception as exc:
            raise BrowserInteractionError(
                "browser_interaction.text_content_failed",
                "Could not read browser text content.",
                {"error": str(exc)},
            ) from exc

    def attribute(self, target: BrowserTarget, name: str) -> str:
        try:
            return str(self._locator(target).first.get_attribute(name) or "")
        except Exception as exc:
            raise BrowserInteractionError(
                "browser_interaction.attribute_failed",
                "Could not read browser element attribute.",
                {"error": str(exc), "attribute": name},
            ) from exc

    def wait_for(self, target: BrowserTarget, *, state: str = "visible", timeout_millis: int = 1000) -> bool:
        try:
            self._locator(target).first.wait_for(state=state, timeout=timeout_millis)
            return True
        except Exception:
            return False

    def wait_for_timeout(self, millis: int) -> None:
        self.page.wait_for_timeout(millis)

    def reload(self) -> BrowserSnapshot:
        self.page.reload()
        return self.snapshot()

    def go_back(self) -> BrowserSnapshot:
        self.page.go_back()
        return self.snapshot()

    def keyboard_press(self, key: str) -> None:
        self.page.keyboard.press(key)

    def keyboard_insert_text(self, text: str) -> None:
        self.page.keyboard.insert_text(text)

    def click(self, target: BrowserTarget) -> None:
        try:
            self._locator(target).click()
        except Exception as exc:
            raise BrowserInteractionError(
                "browser_interaction.click_failed",
                "Could not click the requested browser target.",
                {"error": str(exc)},
            ) from exc

    def fill(self, target: BrowserTarget, value: str) -> None:
        try:
            self._locator(target).fill(value)
        except Exception as exc:
            raise BrowserInteractionError(
                "browser_interaction.fill_failed",
                "Could not fill the requested browser target.",
                {"error": str(exc)},
            ) from exc

    def upload(self, target: BrowserTarget, path: Path) -> None:
        try:
            self._locator(target).set_input_files(str(path))
        except Exception as exc:
            raise BrowserInteractionError(
                "browser_interaction.upload_failed",
                "Could not upload to the requested browser target.",
                {"error": str(exc)},
            ) from exc

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
        self.status = BrowserSessionStatus.CLOSING
        self.closed = True
        try:
            if self.owns_session and self.context is not None:
                self.context.close()
        finally:
            try:
                if self.playwright is not None:
                    self.playwright.stop()
            finally:
                if self.profile_lock is not None:
                    self.profile_lock.release()
                self.status = BrowserSessionStatus.CLOSED
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
    provider_id = "provider.browser.legacy"

    def __init__(
        self,
        *,
        config: Any,
        channel_id: str = "linkedin",
        headed_default: bool = True,
        allow_remote_debugging: bool = True,
        require_remote_debugging: bool = False,
        open_session: Callable[..., tuple[Any, Any, Any, Any, bool, str]] | None = None,
        lock_manager: FileBackedBrowserProfileLockManager | None = None,
    ) -> None:
        self.config = config
        self.channel_id = channel_id
        self.headed_default = headed_default
        self.allow_remote_debugging = allow_remote_debugging
        self.require_remote_debugging = require_remote_debugging
        self.open_session = open_session
        self.lock_manager = lock_manager or FileBackedBrowserProfileLockManager(channel_store.LOCKS_DIR)
        self.sessions: dict[str, LegacyBrowserSession] = {}

    def create_session(self, options: BrowserSessionOptions) -> LegacyBrowserSession:
        session_id = f"legacy_{uuid4().hex}"
        profile_lock = None
        if options.exclusive:
            profile_lock = self.lock_manager.acquire(
                options.profile_id,
                owner=str(options.metadata.get("owner") or f"{self.provider_id}:{session_id}"),
                session_id=session_id,
                provider_id=self.provider_id,
                metadata={
                    "purpose": str(options.metadata.get("purpose") or "browser.session"),
                    "job_id": str(options.metadata.get("job_id") or ""),
                    "channel_id": str(options.metadata.get("channel_id") or self.channel_id),
                },
            )
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
        except BrowserProfileBusyError:
            if profile_lock is not None:
                profile_lock.release()
            raise
        except Exception as exc:
            if profile_lock is not None:
                profile_lock.release()
            raise BrowserUnavailableError(
                "legacy_browser.session_unavailable",
                "Could not open the configured browser session.",
                {"error": str(exc), "profile_id": options.profile_id},
            ) from exc

        session = LegacyBrowserSession(
            session_id=session_id,
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
            owns_session=owns_session,
            session_label=session_label,
            profile_lock=profile_lock,
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
        state = self.lock_manager.status(profile_id)
        return BrowserProfileStatus(
            profile_id=profile_id,
            available=not bool(state.get("busy")),
            busy=bool(state.get("busy")),
            stale=bool(state.get("stale")),
            owner=str(state.get("owner") or ""),
            lock_path=str(state.get("lock_path") or ""),
        )

    def health_check(self) -> dict[str, Any]:
        messages: list[str] = []
        try:
            import playwright.sync_api  # noqa: F401
        except Exception as exc:
            messages.append(f"Playwright dependency unavailable: {exc}")
        if importlib.util.find_spec("playwright") is None:
            messages.append("Playwright package is not importable.")
        profile_dir = Path(getattr(self.config, "linkedin_user_data_dir", ""))
        if not profile_dir:
            messages.append("LinkedIn profile directory is not configured.")
        else:
            try:
                profile_dir.mkdir(parents=True, exist_ok=True)
                if not os.access(profile_dir, os.W_OK):
                    messages.append("LinkedIn profile directory is not writable.")
            except OSError as exc:
                messages.append(f"LinkedIn profile directory is not accessible: {exc}")
        try:
            channel_store.LOCKS_DIR.mkdir(parents=True, exist_ok=True)
            if not os.access(channel_store.LOCKS_DIR, os.W_OK):
                messages.append("Browser lock directory is not writable.")
        except OSError as exc:
            messages.append(f"Browser lock directory is not accessible: {exc}")
        status = "ready" if not messages else "degraded"
        return {
            "ok": not messages,
            "status": status,
            "provider": self.provider_id,
            "messages": messages,
            "sessions": len(self.sessions),
        }

    def request_human_takeover(self, request: HumanTakeoverRequest) -> dict[str, Any]:
        session = self.sessions.get(request.session_id)
        if session is None:
            raise BrowserProviderError(
                "legacy_browser.session_missing",
                "Browser session is no longer available for human takeover.",
                {"session_id": request.session_id},
            )
        session.takeover_status = HumanTakeoverStatus.REQUESTED
        session.status = BrowserSessionStatus.HUMAN_TAKEOVER
        return {
            "status": HumanTakeoverStatus.REQUESTED.value,
            "takeover_reference": f"takeover:{request.session_id}",
            "session_id": request.session_id,
            "reason": request.reason,
        }

    @contextmanager
    def acquire_legacy_execution_session(
        self,
        *,
        profile_id: str,
        purpose: str,
        job_id: str = "",
        headless: bool = True,
    ):
        session = self.create_session(
            BrowserSessionOptions(
                profile_id=profile_id,
                headless=headless,
                exclusive=True,
                metadata={"purpose": purpose, "job_id": job_id},
            )
        )
        try:
            yield session
        finally:
            session.close()

    def force_unlock_profile(
        self, profile_id: str, *, admin_reason: str, actor: str = "local-dashboard"
    ) -> dict[str, Any]:
        return self.lock_manager.force_unlock(profile_id, admin_reason=admin_reason, actor=actor)
