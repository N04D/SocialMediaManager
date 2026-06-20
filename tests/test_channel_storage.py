from __future__ import annotations

import json
import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path

from channel_storage import FileLock, LockTimeoutError, locked_json_store



def _append_value(path_str: str, lock_dir_str: str, value: str, pause: float = 0.0) -> None:
    path = Path(path_str)
    lock_dir = Path(lock_dir_str)
    with locked_json_store(path, default_factory=list, expect_type=list, lock_dir=lock_dir) as store:
        data = store.read()
        data.append(value)
        if pause:
            time.sleep(pause)
        store.write(data)


class ChannelStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.path = self.base / 'records.json'
        self.lock_dir = self.base / 'locks'
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    def test_missing_store_initializes_safely(self) -> None:
        with locked_json_store(self.path, default_factory=list, expect_type=list, lock_dir=self.lock_dir) as store:
            self.assertEqual(store.read(), [])

    def test_atomic_write_creates_valid_json(self) -> None:
        with locked_json_store(self.path, default_factory=list, expect_type=list, lock_dir=self.lock_dir) as store:
            store.write([{'id': 'one'}])
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), [{'id': 'one'}])

    def test_corrupted_json_recovery_creates_backup(self) -> None:
        self.path.write_text('{not json', encoding='utf-8')
        with locked_json_store(self.path, default_factory=list, expect_type=list, lock_dir=self.lock_dir) as store:
            self.assertEqual(store.read(), [])
        backups = list(self.base.glob('records.json.corrupt-*.bak'))
        self.assertTrue(backups)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), [])

    def test_lock_timeout_returns_controlled_error(self) -> None:
        first = FileLock(self.lock_dir / 'shared.lock', timeout_seconds=1)
        second = FileLock(self.lock_dir / 'shared.lock', timeout_seconds=0.1, poll_seconds=0.02)
        first.acquire()
        self.addCleanup(first.release)
        with self.assertRaises(LockTimeoutError):
            second.acquire()

    def test_concurrent_writers_do_not_corrupt_json(self) -> None:
        ctx = multiprocessing.get_context('fork')
        processes = [
            ctx.Process(target=_append_value, args=(str(self.path), str(self.lock_dir), 'a', 0.1)),
            ctx.Process(target=_append_value, args=(str(self.path), str(self.lock_dir), 'b', 0.1)),
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(5)
            self.assertEqual(process.exitcode, 0)
        payload = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(sorted(payload), ['a', 'b'])

    def test_stale_temp_file_does_not_replace_valid_state(self) -> None:
        self.path.write_text(json.dumps([{'id': 'stable'}]), encoding='utf-8')
        (self.base / '.records.json.random.tmp').write_text('broken', encoding='utf-8')
        with locked_json_store(self.path, default_factory=list, expect_type=list, lock_dir=self.lock_dir) as store:
            self.assertEqual(store.read(), [{'id': 'stable'}])
