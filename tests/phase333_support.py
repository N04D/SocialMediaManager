from __future__ import annotations

import subprocess
from pathlib import Path

import mvp_dashboard
from tests.phase332_support import Phase332TestCase


class Phase333TestCase(Phase332TestCase):
    def init_empty_site_repo(self) -> Path:
        repo = self.root / "managed-root" / "empty-site"
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
        return repo

    def publish_session(self, session_id: str) -> dict[str, object]:
        _, status = self.post(
            f"/setup/{session_id}/confirm",
            {"confirmation": mvp_dashboard.CONFIRMATION_TEXT, "idempotency_key": "phase333-confirm-" + session_id},
        )
        self.assertEqual(status, 303)
        return mvp_dashboard._real_publication_status(mvp_dashboard.alpha_ui_service(), session_id)["publication"]

    def prepare_publication(
        self,
        repo: Path,
        port: int,
        *,
        title: str = "MVP Dogfood Publication 333",
        slug: str = "mvp-dogfood-publication-333",
    ) -> str:
        payload, status = self.post(
            "/setup/start",
            {"workspace_id": f"MVP Dogfood 333 {slug}", "idempotency_key": f"phase333-real-{slug}"},
        )
        self.assertEqual(status, 303)
        session_id = payload.split("/setup/", 1)[1].split('"', 1)[0]
        self.complete_foundation(session_id)
        self.register_destination(session_id, repo, port)
        draft_id = self.create_real_draft(session_id, title=title)
        self.autosave(
            draft_id,
            1,
            slug=slug,
            markdown_body="# MVP Dogfood Publication 333\n\nFirst commit proof.",
        )
        mvp_dashboard._ensure_real_plan(mvp_dashboard.alpha_ui_service(), session_id)
        return session_id
