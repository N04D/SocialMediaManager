from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
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
    manager: BrowserProfileLockManager
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

    def __enter__(self) -> BrowserProfileLock:
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


Clock = Callable[[], float]


class FileBackedBrowserProfileLockManager:
    def __init__(
        self,
        lock_dir: Path,
        *,
        lease_seconds: float = 300.0,
        clock: Clock | None = None,
        audit_path: Path | None = None,
    ) -> None:
        self.lock_dir = Path(lock_dir)
        self.lease_seconds = lease_seconds
        self.clock = clock or time.time
        self.audit_path = audit_path or (self.lock_dir / "browser_profile_force_unlock_audit.jsonl")

    def acquire(
        self,
        profile_id: str,
        *,
        owner: str = "",
        session_id: str = "",
        provider_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> BrowserProfileLock:
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.lock_path(profile_id)
        resolved_owner = owner or f"pid:{os.getpid()}:{uuid4().hex}"
        resolved_session_id = session_id or f"session:{uuid4().hex}"
        metadata_payload = self._metadata(profile_id, resolved_owner, resolved_session_id, provider_id)
        metadata_payload.update(metadata or {})
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                existing = self._read_lock(lock_path)
                if not self._is_expired(existing):
                    raise BrowserProfileBusyError(
                        "browser_profile.busy",
                        "Browser profile is already in use.",
                        {
                            "profile_id": profile_id,
                            "owner": str(existing.get("owner") or "unknown"),
                            "lock_path": str(lock_path),
                            "stale": False,
                        },
                    ) from None
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    continue
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(metadata_payload, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            lease = BrowserProfileLease(
                profile_id=profile_id,
                owner=resolved_owner,
                acquired_at=float(metadata_payload["created_at_epoch"]),
                heartbeat_at=float(metadata_payload["heartbeat_at_epoch"]),
                lease_seconds=self.lease_seconds,
            )
            return BrowserProfileLock(self, profile_id, lease)

    def heartbeat(self, profile_id: str, owner: str) -> None:
        lock_path = self.lock_path(profile_id)
        metadata = self._read_lock(lock_path)
        if metadata.get("owner") != owner:
            return
        now = self.clock()
        metadata["heartbeat_at_epoch"] = now
        metadata["heartbeat_at"] = self._iso(now)
        self._write_lock(lock_path, metadata)

    def release(self, profile_id: str, owner: str) -> None:
        lock_path = self.lock_path(profile_id)
        metadata = self._read_lock(lock_path)
        if metadata.get("owner") == owner:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    def force_unlock(self, profile_id: str, *, admin_reason: str, actor: str = "local-dashboard") -> dict[str, Any]:
        if not admin_reason.strip():
            raise ValueError("force_unlock requires an explicit administrative reason.")
        lock_path = self.lock_path(profile_id)
        old_metadata = self._read_lock(lock_path)
        lease_status = self.status(profile_id)
        audit = {
            "profile_id": profile_id,
            "provider_id": str(old_metadata.get("provider_id") or ""),
            "old_owner": str(old_metadata.get("owner") or ""),
            "old_session_id": str(old_metadata.get("session_id") or ""),
            "lease_status": "stale"
            if lease_status.get("stale")
            else ("active" if lease_status.get("busy") else "missing"),
            "actor": actor,
            "timestamp": self._iso(self.clock()),
            "reason": admin_reason,
            "result": "lock_removed",
            "warning": "Force unlock only removes the coordination lock; verify active browser processes manually.",
        }
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(audit, sort_keys=True) + "\n")
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        return audit

    def status(self, profile_id: str, *, lock_path: Path | None = None) -> dict[str, object]:
        resolved_lock_path = lock_path or self.lock_path(profile_id)
        metadata = self._read_lock(resolved_lock_path)
        if not metadata:
            return {"busy": False, "owner": "", "stale": False, "lock_path": str(resolved_lock_path)}
        stale = self._is_expired(metadata)
        return {
            "busy": not stale,
            "owner": str(metadata.get("owner") or "unknown"),
            "stale": stale,
            "lock_path": str(resolved_lock_path),
            "session_id": str(metadata.get("session_id") or ""),
            "provider_id": str(metadata.get("provider_id") or ""),
        }

    def lock_path(self, profile_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in profile_id)
        return self.lock_dir / f"{safe}.profile.lock"

    def _metadata(self, profile_id: str, owner: str, session_id: str, provider_id: str) -> dict[str, Any]:
        now = self.clock()
        return {
            "profile_id": profile_id,
            "owner": owner,
            "pid": os.getpid(),
            "provider_id": provider_id,
            "session_id": session_id,
            "created_at_epoch": now,
            "created_at": self._iso(now),
            "heartbeat_at_epoch": now,
            "heartbeat_at": self._iso(now),
            "lease_seconds": self.lease_seconds,
            "lock_version": 1,
        }

    def _is_expired(self, metadata: dict[str, Any]) -> bool:
        if not metadata:
            return False
        heartbeat = metadata.get("heartbeat_at_epoch")
        if heartbeat is None:
            heartbeat = metadata.get("acquired_at_epoch")
        if heartbeat is None:
            heartbeat = metadata.get("created_at_epoch")
        lease = float(metadata.get("lease_seconds") or self.lease_seconds)
        try:
            return (self.clock() - float(heartbeat)) > lease
        except (TypeError, ValueError):
            return self._legacy_file_is_releasable(metadata)

    def _legacy_file_is_releasable(self, metadata: dict[str, Any]) -> bool:
        return not bool(metadata.get("owner"))

    def _read_lock(self, lock_path: Path) -> dict[str, Any]:
        try:
            raw = lock_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        if not raw.strip():
            return {"owner": "legacy", "heartbeat_at_epoch": 0, "lease_seconds": 0}
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return {"owner": "legacy", "heartbeat_at_epoch": 0, "lease_seconds": 0}
        return loaded if isinstance(loaded, dict) else {}

    def _write_lock(self, lock_path: Path, metadata: dict[str, Any]) -> None:
        temp_path = lock_path.with_suffix(lock_path.suffix + f".{uuid4().hex}.tmp")
        temp_path.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp_path, lock_path)

    def _iso(self, epoch: float) -> str:
        return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")
