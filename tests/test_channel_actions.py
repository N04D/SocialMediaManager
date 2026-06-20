from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

pipeline_stub = types.ModuleType("pipeline")


class _AppConfig:
    pass


pipeline_stub.AppConfig = _AppConfig
pipeline_stub.POST_BUTTON_PATTERNS = [r"post"]
pipeline_stub.run_local_ai = lambda *args, **kwargs: "stubbed derivative"
pipeline_stub.open_linkedin_session = lambda *args, **kwargs: None
sys.modules["pipeline"] = pipeline_stub

from channel_actions import (
    ChannelActionError,
    create_publish_job_from_derivative,
    engagement_rate,
    manual_attach_published_url,
    queue_metric_job,
)
from channel_models import ApprovalRecord, ChannelConnection, ContentDerivative, PostMetricSnapshot, PublishJob
from channel_store import (
    now_iso,
    save_approval,
    save_channel_connection,
    save_derivative,
    save_publish_job,
)

from tests.test_support import isolated_channel_store


class ChannelActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._store_ctx = isolated_channel_store(Path(self._tmp.name))
        self._store_ctx.__enter__()
        self.addCleanup(self._store_ctx.__exit__, None, None, None)

    def _save_derivative(self, *, channel_id: str = "linkedin", status: str = "approved") -> ContentDerivative:
        derivative = ContentDerivative(
            id="derivative-1",
            source_document_id="doc-1",
            channel_id=channel_id,
            output_type="linkedin_post" if channel_id == "linkedin" else f"{channel_id}_post",
            title="Derivative",
            body="A short but valid LinkedIn post body.",
            status=status,
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        return save_derivative(derivative)

    def _save_connection(self, *, channel_id: str = "linkedin", status: str = "connected") -> ChannelConnection:
        connection = ChannelConnection(
            id=f"connection-{channel_id}",
            channel_id=channel_id,
            mode="playwright_local" if channel_id == "linkedin" else "placeholder",
            status=status,
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        return save_channel_connection(connection)

    def _save_approval(self, derivative_id: str, *, revoked: bool = False) -> ApprovalRecord:
        approval = ApprovalRecord(
            id="approval-1",
            derivative_id=derivative_id,
            approved_by="tester",
            approved_at=now_iso(),
            status="approved",
            revoked_at=now_iso() if revoked else "",
            created_at=now_iso(),
        )
        return save_approval(approval)

    def test_unapproved_derivative_cannot_create_publish_job(self) -> None:
        derivative = self._save_derivative(status="draft")
        self._save_connection(channel_id="linkedin", status="connected")
        with self.assertRaises(ChannelActionError):
            create_publish_job_from_derivative(derivative.id, channel_id="linkedin", run_mode="dry_run")

    def test_revoked_approval_cannot_publish(self) -> None:
        derivative = self._save_derivative(status="approved")
        self._save_connection(channel_id="linkedin", status="connected")
        self._save_approval(derivative.id, revoked=True)
        with self.assertRaises(ChannelActionError):
            create_publish_job_from_derivative(derivative.id, channel_id="linkedin", run_mode="dry_run")

    def test_wrong_channel_cannot_publish(self) -> None:
        derivative = self._save_derivative(channel_id="linkedin", status="approved")
        self._save_connection(channel_id="instagram", status="connected")
        self._save_approval(derivative.id)
        with self.assertRaises(ChannelActionError):
            create_publish_job_from_derivative(derivative.id, channel_id="instagram", run_mode="dry_run")

    def test_disconnected_channel_cannot_publish(self) -> None:
        derivative = self._save_derivative(status="approved")
        self._save_connection(channel_id="linkedin", status="needs_login")
        self._save_approval(derivative.id)
        with self.assertRaises(ChannelActionError):
            create_publish_job_from_derivative(derivative.id, channel_id="linkedin", run_mode="dry_run")

    def test_unsupported_plugin_capability_blocks_publish(self) -> None:
        derivative = self._save_derivative(channel_id="instagram", status="approved")
        derivative.output_type = "instagram_post"
        save_derivative(derivative)
        self._save_connection(channel_id="instagram", status="connected")
        self._save_approval(derivative.id)
        with self.assertRaises(ChannelActionError):
            create_publish_job_from_derivative(derivative.id, channel_id="instagram", run_mode="dry_run")

    def test_single_active_linkedin_job_is_enforced(self) -> None:
        derivative = self._save_derivative(status="approved")
        self._save_connection(channel_id="linkedin", status="connected")
        self._save_approval(derivative.id)
        save_publish_job(
            PublishJob(
                id="publish-existing",
                derivative_id="other-derivative",
                channel_id="linkedin",
                status="queued",
                requested_at=now_iso(),
                created_at=now_iso(),
                updated_at=now_iso(),
            )
        )
        with self.assertRaises(ChannelActionError):
            create_publish_job_from_derivative(derivative.id, channel_id="linkedin", run_mode="live")

    def test_manual_attach_rejects_untrusted_linkedin_url(self) -> None:
        derivative = self._save_derivative(status="approved")
        with self.assertRaises(ChannelActionError):
            manual_attach_published_url(
                derivative.id,
                channel_id="linkedin",
                external_url="https://example.com/not-linkedin",
            )

    def test_duplicate_metric_job_is_prevented(self) -> None:
        job_one = queue_metric_job(
            published_post_id="post-1",
            channel_id="linkedin",
            scheduled_for="2026-06-19T10:00:00+02:00",
        )
        job_two = queue_metric_job(
            published_post_id="post-1",
            channel_id="linkedin",
            scheduled_for="2026-06-19T10:00:00+02:00",
        )
        self.assertEqual(job_one.id, job_two.id)

    def test_engagement_rate_requires_valid_denominator(self) -> None:
        no_denominator = PostMetricSnapshot(
            id="snapshot-1",
            published_post_id="post-1",
            channel_id="linkedin",
            captured_at=now_iso(),
            reactions=5,
            comments=1,
            reposts=1,
        )
        self.assertEqual(engagement_rate(no_denominator), (None, ""))

        with_impressions = PostMetricSnapshot(
            id="snapshot-2",
            published_post_id="post-1",
            channel_id="linkedin",
            captured_at=now_iso(),
            impressions=100,
            reactions=5,
            comments=3,
            reposts=2,
        )
        rate, denominator = engagement_rate(with_impressions)
        self.assertEqual(denominator, "impressions")
        self.assertAlmostEqual(rate or 0.0, 0.10, places=4)
