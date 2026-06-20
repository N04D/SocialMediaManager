from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

pipeline_stub = types.ModuleType('pipeline')
class _AppConfig: ...
pipeline_stub.AppConfig = _AppConfig
pipeline_stub.POST_BUTTON_PATTERNS = [r'post']
pipeline_stub.run_local_ai = lambda *args, **kwargs: 'stubbed derivative'
pipeline_stub.open_linkedin_session = lambda *args, **kwargs: None
sys.modules['pipeline'] = pipeline_stub

from channel_actions import manual_attach_published_url, queue_manual_metric_refresh
from channel_models import ContentDerivative, MetricJob
from channel_store import get_published_post, list_metric_jobs, now_iso, save_derivative, save_metric_job
from tests.test_support import isolated_channel_store


class ChannelMetricsBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._store_ctx = isolated_channel_store(Path(self._tmp.name))
        self._store_ctx.__enter__()
        self.addCleanup(self._store_ctx.__exit__, None, None, None)
        derivative = ContentDerivative(
            id='derivative-1',
            source_document_id='doc-1',
            channel_id='linkedin',
            output_type='linkedin_post',
            title='Derivative',
            body='Approved text',
            status='approved',
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        save_derivative(derivative)
        self.derivative = derivative

    def test_manual_attach_normalizes_and_trusts_url(self) -> None:
        post = manual_attach_published_url(
            self.derivative.id,
            channel_id='linkedin',
            external_url='http://www.linkedin.com/feed/update/urn:li:activity-12345/?tracking=foo',
        )
        stored = get_published_post(post.id)
        self.assertEqual(stored.external_url, 'https://www.linkedin.com/feed/update/urn:li:activity-12345')
        self.assertEqual(stored.external_id, 'activity-12345')

    def test_manual_refresh_reuses_existing_active_metric_job(self) -> None:
        post = manual_attach_published_url(
            self.derivative.id,
            channel_id='linkedin',
            external_url='https://www.linkedin.com/feed/update/urn:li:activity-12345/',
        )
        before_jobs = list_metric_jobs(published_post_id=post.id)
        save_metric_job(
            MetricJob(
                id='metric-1',
                published_post_id=post.id,
                channel_id='linkedin',
                status='queued',
                scheduled_for=now_iso(),
                requested_at=now_iso(),
                created_at=now_iso(),
                updated_at=now_iso(),
            )
        )
        refreshed = queue_manual_metric_refresh(post.id)
        after_jobs = list_metric_jobs(published_post_id=post.id)
        self.assertEqual(len(after_jobs), len(before_jobs) + 1)
        self.assertIn(refreshed.id, {job.id for job in after_jobs if job.status in {'queued', 'running', 'needs_login'}})
