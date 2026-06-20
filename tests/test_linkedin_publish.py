from __future__ import annotations

import sys
import types
import unittest

pipeline_stub = types.ModuleType('pipeline')
class _AppConfig: ...
pipeline_stub.AppConfig = _AppConfig
pipeline_stub.dismiss_linkedin_cookie_banner = lambda *args, **kwargs: None
pipeline_stub.find_composer_editor = lambda *args, **kwargs: None
pipeline_stub.open_linkedin_post_composer = lambda *args, **kwargs: None
pipeline_stub.type_into_contenteditable = lambda *args, **kwargs: None
pipeline_stub.open_linkedin_session = lambda *args, **kwargs: None
pipeline_stub.POST_BUTTON_PATTERNS = [r'post']
pipeline_stub.run_local_ai = lambda *args, **kwargs: 'stubbed derivative'
sys.modules['pipeline'] = pipeline_stub

from channel_models import PublishJob
from channels.linkedin.worker.publish import _assert_live_submit_allowed


class LinkedInPublishDryRunTests(unittest.TestCase):
    def test_final_submit_cannot_execute_in_dry_run(self) -> None:
        job = PublishJob(
            id='publish-1',
            derivative_id='derivative-1',
            channel_id='linkedin',
            status='running',
            requested_at='2026-06-19T10:00:00+00:00',
            run_mode='dry_run',
        )
        with self.assertRaises(RuntimeError):
            _assert_live_submit_allowed(job)
