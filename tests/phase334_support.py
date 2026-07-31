from __future__ import annotations

from pathlib import Path

import mvp_dashboard
from tests.phase333_support import Phase333TestCase


class Phase334TestCase(Phase333TestCase):
    custom_seo = "Custom dogfood SEO description for closed alpha publication."

    def prepare_publication_with_custom_seo(self, repo: Path, port: int) -> tuple[str, str]:
        payload, status = self.post(
            "/setup/start",
            {"workspace_id": "MVP Dogfood 334", "idempotency_key": "phase334-real"},
        )
        self.assertEqual(status, 303)
        session_id = payload.split("/setup/", 1)[1].split('"', 1)[0]
        self.complete_foundation(session_id)
        self.register_destination(session_id, repo, port)
        payload, status = self.post(
            f"/setup/{session_id}/create-draft",
            {
                "title": "MVP Dogfood Publication 334",
                "slug": "mvp-dogfood-publication-334",
                "markdown_body": "# MVP Dogfood Publication 334\n\nClosed alpha SEO proof.",
                "author": "Dogfood Operator",
                "tags": "dogfood,phase33.4",
                "seo_description": self.custom_seo,
            },
        )
        self.assertEqual(status, 303)
        draft_id = payload.split("/content/", 1)[1].split("/compose", 1)[0]
        saved = self.autosave(
            draft_id,
            1,
            slug="mvp-dogfood-publication-334",
            summary="Default summary that must not replace custom SEO.",
            seo_description=self.custom_seo,
            markdown_body="# MVP Dogfood Publication 334\n\nClosed alpha SEO proof.",
        )
        self.assertEqual(saved["draft"]["seo_description"], self.custom_seo)
        mvp_dashboard._ensure_real_plan(mvp_dashboard.alpha_ui_service(), session_id)
        return session_id, draft_id

    def publish_custom_seo(self) -> tuple[str, Path, dict[str, object]]:
        repo = self.init_empty_site_repo()
        with self.static_server(repo) as port:
            session_id, _draft_id = self.prepare_publication_with_custom_seo(repo, port)
            publication = self.publish_session(session_id)
        return session_id, repo, publication
