from __future__ import annotations

import json
import os
import fcntl
import urllib.error
import urllib.request
from contextlib import contextmanager
from copy import copy
from dataclasses import is_dataclass, replace
from datetime import datetime
from pathlib import Path

from channel_storage import FileLock, LockTimeoutError
from channel_store import CHANNEL_SCREENSHOTS_DIR, LOCKS_DIR, ensure_channel_store_dirs
from pipeline import AppConfig, open_linkedin_session


PROFILE_LOCK_TIMEOUT_SECONDS = float(os.environ.get("CHANNEL_PROFILE_LOCK_TIMEOUT_SECONDS", "3"))


class ProfileBusyError(RuntimeError):
    """Raised when another local process currently owns the persistent LinkedIn profile."""


class RemoteBrowserUnavailableError(RuntimeError):
    """Raised when interactive Connect requires a remote-debugging browser that is not reachable."""



def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}



def linkedin_dry_run_default() -> bool:
    return env_flag("LINKEDIN_DRY_RUN", True)



def keep_browser_open_on_error() -> bool:
    return env_flag("LINKEDIN_KEEP_BROWSER_OPEN_ON_ERROR", False)



def linkedin_debug_enabled() -> bool:
    return env_flag("LINKEDIN_DEBUG", False)



def apply_worker_overrides(
    config: AppConfig,
    *,
    headed_default: bool,
    allow_remote_debugging: bool = False,
) -> AppConfig:
    headless = env_flag("LINKEDIN_HEADLESS", not headed_default)
    remote_debugging_url = config.linkedin_remote_debugging_url if allow_remote_debugging else ""
    if is_dataclass(config):
        return replace(
            config,
            linkedin_remote_debugging_url=remote_debugging_url,
            headless=headless,
        )
    worker_config = copy(config)
    worker_config.linkedin_remote_debugging_url = remote_debugging_url
    worker_config.headless = headless
    return worker_config



def persistent_profile_path(config: AppConfig) -> Path:
    return config.linkedin_user_data_dir.resolve()



def remote_debugging_is_available(remote_debugging_url: str) -> bool:
    if not remote_debugging_url:
        return False
    probe_url = remote_debugging_url.rstrip('/') + '/json/version'
    try:
        with urllib.request.urlopen(probe_url, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False



def _profile_lock_path(channel_id: str) -> Path:
    ensure_channel_store_dirs()
    return LOCKS_DIR / f"{channel_id}.profile.lock"



def profile_lock_state(channel_id: str) -> dict[str, str | bool]:
    lock_path = _profile_lock_path(channel_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    owner = ""
    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        handle.seek(0)
        owner = handle.read().strip()
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"busy": True, "owner": owner, "lock_path": str(lock_path)}
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return {"busy": False, "owner": "", "lock_path": str(lock_path)}
    finally:
        handle.close()


@contextmanager
def linkedin_profile_lock(channel_id: str, *, owner: str = ""):
    ensure_channel_store_dirs()
    lock_path = _profile_lock_path(channel_id)
    metadata = {
        "channel_id": channel_id,
        "owner": owner or f"pid:{os.getpid()}",
        "pid": os.getpid(),
        "purpose": "linkedin_profile",
    }
    lock = FileLock(lock_path, timeout_seconds=PROFILE_LOCK_TIMEOUT_SECONDS, metadata=metadata)
    try:
        lock.acquire()
    except LockTimeoutError as exc:
        raise ProfileBusyError(str(exc)) from exc
    try:
        yield lock_path
    finally:
        lock.release()



def open_local_linkedin_session(
    config: AppConfig,
    *,
    headed_default: bool = True,
    allow_remote_debugging: bool = False,
    require_remote_debugging: bool = False,
):
    worker_config = apply_worker_overrides(
        config,
        headed_default=headed_default,
        allow_remote_debugging=allow_remote_debugging,
    )
    if require_remote_debugging and not remote_debugging_is_available(worker_config.linkedin_remote_debugging_url):
        raise RemoteBrowserUnavailableError(
            'Interactive LinkedIn Connect requires the configured remote-debugging browser. '
            'Start scripts/start-linkedin-remote-browser.sh and try Connect again.'
        )
    return open_linkedin_session(worker_config)



def capture_worker_screenshot(page, *, channel_id: str, job_type: str, job_id: str, step: str) -> str:
    ensure_channel_store_dirs()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{channel_id}-{job_type}-{job_id}-{step}-{timestamp}.png"
    target = CHANNEL_SCREENSHOTS_DIR / filename
    page.screenshot(path=str(target), full_page=True)
    return str(target)
