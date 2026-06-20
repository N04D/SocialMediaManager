from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

import fcntl


class ChannelStorageError(RuntimeError):
    """Base error for shared file-backed channel storage."""


class LockTimeoutError(ChannelStorageError):
    """Raised when a shared storage lock cannot be acquired in time."""


class CorruptStoreRecovered(ChannelStorageError):
    """Raised internally when a corrupt JSON file was backed up and reset."""


@dataclass
class FileLock:
    path: Path
    timeout_seconds: float = 10.0
    poll_seconds: float = 0.1
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(self.timeout_seconds, 0.0)
        handle = open(self.path, "a+", encoding="utf-8")
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                handle.seek(0)
                handle.truncate()
                payload = dict(self.metadata or {})
                payload.setdefault("pid", os.getpid())
                payload.setdefault("acquired_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
                handle.write(json.dumps(payload, sort_keys=True))
                handle.flush()
                os.fsync(handle.fileno())
                self._handle = handle
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.seek(0)
                    owner = handle.read().strip()
                    handle.close()
                    raise LockTimeoutError(
                        f"Timed out acquiring lock {self.path}. Current owner metadata: {owner or 'unknown'}"
                    )
                time.sleep(self.poll_seconds)
            except Exception:
                handle.close()
                raise

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class LockedJsonStore:
    def __init__(
        self,
        path: Path,
        *,
        default_factory: Callable[[], Any],
        expect_type: type,
        lock_dir: Path,
        timeout_seconds: float = 10.0,
        poll_seconds: float = 0.1,
    ) -> None:
        self.path = Path(path)
        self.default_factory = default_factory
        self.expect_type = expect_type
        self.lock = FileLock(
            lock_dir / f"{self.path.name}.lock",
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
            metadata={"store": self.path.name},
        )
        self._data: Any | None = None

    def __enter__(self) -> LockedJsonStore:
        self.lock.acquire()
        self._data = self._read_unlocked()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._data = None
        self.lock.release()

    def read(self) -> Any:
        if self._data is None:
            self._data = self._read_unlocked()
        return json.loads(json.dumps(self._data, sort_keys=True))

    def write(self, data: Any) -> None:
        if not isinstance(data, self.expect_type):
            raise ChannelStorageError(
                f"{self.path.name} must contain {self.expect_type.__name__}, received {type(data).__name__}."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, indent=2, ensure_ascii=True, sort_keys=True) + "\n"
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(self.path.parent),
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, self.path)
        try:
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        self._data = json.loads(payload)

    def _backup_corrupt_file(self, raw_text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_path = self.path.with_suffix(self.path.suffix + f".corrupt-{suffix}.bak")
        backup_path.write_text(raw_text, encoding="utf-8")
        self.write(self.default_factory())

    def _read_unlocked(self) -> Any:
        if not self.path.exists():
            return self.default_factory()
        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self.default_factory()
        if not raw_text.strip():
            return self.default_factory()
        try:
            loaded = json.loads(raw_text)
        except json.JSONDecodeError:
            self._backup_corrupt_file(raw_text)
            return self.default_factory()
        if not isinstance(loaded, self.expect_type):
            self._backup_corrupt_file(raw_text)
            return self.default_factory()
        return loaded


@contextmanager
def locked_json_store(
    path: Path,
    *,
    default_factory: Callable[[], Any],
    expect_type: type,
    lock_dir: Path,
    timeout_seconds: float = 10.0,
    poll_seconds: float = 0.1,
) -> Iterator[LockedJsonStore]:
    store = LockedJsonStore(
        path,
        default_factory=default_factory,
        expect_type=expect_type,
        lock_dir=lock_dir,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
    )
    with store:
        yield store
