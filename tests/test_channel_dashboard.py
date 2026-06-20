from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from channel_models import ContentDerivative
from channel_store import now_iso, save_derivative
from studio_models import ContentItem
from tests.test_support import install_pipeline_stub, isolated_channel_store

install_pipeline_stub()

from channel_dashboard import render_derivatives_panel


class ChannelDashboardRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._store_ctx = isolated_channel_store(Path(self._tmp.name))
        self._store_ctx.__enter__()
        self.addCleanup(self._store_ctx.__exit__, None, None, None)

    def test_approved_derivative_without_publish_job_shows_ready_to_queue_state(self) -> None:
        save_derivative(
            ContentDerivative(
                id="derivative-1",
                source_document_id="doc-1",
                channel_id="linkedin",
                output_type="linkedin_post",
                title="LinkedIn draft",
                body="A ready LinkedIn post.",
                status="approved",
                created_at=now_iso(),
                updated_at=now_iso(),
            )
        )
        item = ContentItem(
            id="doc-1",
            title="Canonical draft",
            subtitle="",
            slug="canonical-draft",
            status="draft",
        )

        markup = render_derivatives_panel(item, return_to="/editor")

        self.assertIn("Ready to queue", markup)
        self.assertIn("Dry run publish", markup)
        self.assertIn("Live publish", markup)


if __name__ == "__main__":
    unittest.main()
