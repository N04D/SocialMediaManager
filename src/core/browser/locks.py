from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .errors import BrowserProfileBusyError


@dataclass(frozen=True)
class BrowserProfileLease:
    profile_id: str
    owner: str
    acquired_at: float
    heartbeat_at: float
    lease_seconds: float

    @property
    def stale(self) -> bool:
        return (time.time() - self.heartbeat_at) > self.lease_seconds


@dataclass
class BrowserProfileLock:
    manager: "BrowserProfileLockManager"
    profile_id: str
    lease: BrowserProfileLease
    released: bool = False

    def heartbeat(self) -> None:
        self.manager.heartbeat(self.profile_id, self.lease.owner)

    def release(self) -> None:
        if self.released:
            return
        self.manager.release(self.profile_id, self.lease.owner)
        self.released = True

    def __enter__(self) -> "BrowserProfileLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class BrowserProfileLockManager:
    def __init__(self, *, lease_seconds: float = 300.0) -> None:
        self.lease_seconds = lease_seconds
        self._leases: dict[str, BrowserProfileLease] = {}

    def acquire(self, profile_id: str, *, owner: str = "") -> BrowserProfileLock:
        lease = self._leases.get(profile_id)
        if lease and not lease.stale:
            raise BrowserProfileBusyError(
                "browser_profile.busy",
                "Browser profile is already in use.",
                {"profile_id": profile_id, "owner": lease.owner},
            )
        now = time.time()
        resolved_owner = owner or f"pid:{os.getpid()}:{uuid4().hex}"
        new_lease = BrowserProfileLease(
            profile_id=profile_id,
            owner=resolved_owner,
            acquired_at=now,
            heartbeat_at=now,
            lease_seconds=self.lease_seconds,
        )
        self._leases[profile_id] = new_lease
        return BrowserProfileLock(self, profile_id, new_lease)

    def heartbeat(self, profile_id: str, owner: str) -> None:
        lease = self._leases.get(profile_id)
        if not lease or lease.owner != owner:
            return
        self._leases[profile_id] = BrowserProfileLease(
            profile_id=lease.profile_id,
            owner=lease.owner,
            acquired_at=lease.acquired_at,
            heartbeat_at=time.time(),
            lease_seconds=lease.lease_seconds,
        )

    def status(self, profile_id: str, *, lock_path: Path | None = None) -> dict[str, object]:
        lease = self._leases.get(profile_id)
        if not lease:
            return {"busy": False, "owner": "", "stale": False, "lock_path": str(lock_path or "")}
        return {
            "busy": not lease.stale,
            "owner": lease.owner,
            "stale": lease.stale,
            "lock_path": str(lock_path or ""),
        }

    def release(self, profile_id: str, owner: str) -> None:
        lease = self._leases.get(profile_id)
        if lease and lease.owner == owner:
            self._leases.pop(profile_id, None)

    def force_unlock(self, profile_id: str, *, admin_reason: str) -> None:
        if not admin_reason.strip():
            raise ValueError("force_unlock requires an explicit administrative reason.")
        self._leases.pop(profile_id, None)
