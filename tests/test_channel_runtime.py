from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from channel_models import WorkerHeartbeat
from channel_store import now_iso, save_worker_heartbeat, worker_status_from_heartbeat
from tests.test_support import isolated_channel_store, install_pipeline_stub

install_pipeline_stub()
from channels.linkedin.worker.browser import ProfileBusyError, linkedin_profile_lock, profile_lock_state


class WorkerHeartbeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._store_ctx = isolated_channel_store(Path(self._tmp.name))
        self._store_ctx.__enter__()
        self.addCleanup(self._store_ctx.__exit__, None, None, None)

    def test_worker_appears_online_with_fresh_heartbeat(self) -> None:
        save_worker_heartbeat(
            WorkerHeartbeat(
                worker_id='linkedin:1',
                worker_type='channel_worker',
                channel_id='linkedin',
                status='idle',
                last_seen_at=now_iso(),
                current_job_type='',
                process_id=1,
            )
        )
        status, heartbeat = worker_status_from_heartbeat('linkedin', timeout_seconds=120)
        self.assertEqual(status, 'idle')
        self.assertIsNotNone(heartbeat)

    def test_stale_heartbeat_appears_offline(self) -> None:
        save_worker_heartbeat(
            WorkerHeartbeat(
                worker_id='linkedin:1',
                worker_type='channel_worker',
                channel_id='linkedin',
                status='busy',
                last_seen_at='2000-01-01T00:00:00+00:00',
                current_job_id='publish-1',
                current_job_type='publish',
                process_id=1,
            )
        )
        status, heartbeat = worker_status_from_heartbeat('linkedin', timeout_seconds=1)
        self.assertEqual(status, 'offline')
        self.assertEqual(heartbeat.current_job_type, 'publish')

    def test_profile_lock_rejects_second_owner_and_releases_cleanly(self) -> None:
        with patch('channels.linkedin.worker.browser.LOCKS_DIR', Path(self._tmp.name) / 'locks'):
            with linkedin_profile_lock('linkedin', owner='worker-a'):
                state = profile_lock_state('linkedin')
                self.assertTrue(state['busy'])
                with self.assertRaises(ProfileBusyError):
                    with linkedin_profile_lock('linkedin', owner='worker-b'):
                        pass
            state = profile_lock_state('linkedin')
            self.assertFalse(state['busy'])
