from __future__ import annotations

import multiprocessing
import tempfile
import unittest
from pathlib import Path

from channel_models import PublishJob
from channel_store import claim_next_publish_job, list_publish_jobs, now_iso, save_publish_job
from tests.test_support import isolated_channel_store



def _claim_publish(base_dir: str, worker_id: str, output) -> None:
    with isolated_channel_store(Path(base_dir)):
        job = claim_next_publish_job('linkedin', worker_id=worker_id, lease_seconds=60)
        output.put(job.id if job else '')


class ChannelJobClaimingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._store_ctx = isolated_channel_store(Path(self._tmp.name))
        self._store_ctx.__enter__()
        self.addCleanup(self._store_ctx.__exit__, None, None, None)

    def _save_job(self, **overrides) -> PublishJob:
        current_time = now_iso()
        job = PublishJob(
            id=overrides.pop('id', 'publish-1'),
            derivative_id=overrides.pop('derivative_id', 'derivative-1'),
            channel_id=overrides.pop('channel_id', 'linkedin'),
            status=overrides.pop('status', 'queued'),
            requested_at=overrides.pop('requested_at', current_time),
            created_at=overrides.pop('created_at', current_time),
            updated_at=overrides.pop('updated_at', current_time),
            run_mode=overrides.pop('run_mode', 'dry_run'),
            **overrides,
        )
        return save_publish_job(job)

    def test_two_workers_cannot_claim_same_job(self) -> None:
        self._save_job()
        ctx = multiprocessing.get_context('fork')
        output = ctx.Queue()
        processes = [
            ctx.Process(target=_claim_publish, args=(self._tmp.name, 'worker-a', output)),
            ctx.Process(target=_claim_publish, args=(self._tmp.name, 'worker-b', output)),
        ]
        for process in processes:
            process.start()
        results = []
        for process in processes:
            process.join(5)
            self.assertEqual(process.exitcode, 0)
            results.append(output.get(timeout=1))
        claimed = [item for item in results if item]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0], 'publish-1')

    def test_one_active_linkedin_publish_job_blocks_second_claim(self) -> None:
        self._save_job(id='publish-1')
        self._save_job(id='publish-2', derivative_id='derivative-2')
        first = claim_next_publish_job('linkedin', worker_id='worker-a', lease_seconds=60)
        second = claim_next_publish_job('linkedin', worker_id='worker-b', lease_seconds=60)
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_claimed_job_records_worker_id_and_timestamps(self) -> None:
        self._save_job()
        claimed = claim_next_publish_job('linkedin', worker_id='worker-a', lease_seconds=90)
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed.claimed_by, 'worker-a')
        self.assertTrue(claimed.claimed_at)
        self.assertTrue(claimed.lease_expires_at)
        self.assertEqual(claimed.status, 'running')
        self.assertEqual(claimed.attempt_count, 1)

    def test_expired_safe_job_is_recovered_and_reclaimed(self) -> None:
        self._save_job(
            status='running',
            claimed_by='worker-old',
            claimed_at='2026-06-19T10:00:00+00:00',
            lease_expires_at='2000-01-01T00:00:00+00:00',
            heartbeat_at='2000-01-01T00:00:00+00:00',
            started_at='2026-06-19T10:00:00+00:00',
            attempt_count=1,
            run_mode='dry_run',
            last_step='filled_composer',
        )
        claimed = claim_next_publish_job('linkedin', worker_id='worker-new', lease_seconds=90)
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed.id, 'publish-1')
        self.assertEqual(claimed.claimed_by, 'worker-new')
        self.assertEqual(claimed.attempt_count, 2)

    def test_uncertain_live_publish_is_never_auto_requeued(self) -> None:
        self._save_job(
            status='running',
            claimed_by='worker-old',
            claimed_at='2026-06-19T10:00:00+00:00',
            lease_expires_at='2000-01-01T00:00:00+00:00',
            heartbeat_at='2000-01-01T00:00:00+00:00',
            started_at='2026-06-19T10:00:00+00:00',
            run_mode='live',
            submitted_at='2026-06-19T10:05:00+00:00',
            attempt_count=1,
        )
        claimed = claim_next_publish_job('linkedin', worker_id='worker-new', lease_seconds=90)
        self.assertIsNone(claimed)
        stored = list_publish_jobs(channel_id='linkedin')[0]
        self.assertEqual(stored.status, 'manual_verification_required')
        self.assertTrue(stored.unknown_result)
        self.assertTrue(stored.manual_verification_required)
