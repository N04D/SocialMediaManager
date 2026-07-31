from __future__ import annotations

import contextlib
import functools
import http.server
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

import mvp_dashboard


class Phase331TestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.database_path = self.root / "mvp.sqlite3"
        self.old_database = mvp_dashboard.MVP_DATABASE
        mvp_dashboard.MVP_DATABASE = self.database_path

    def tearDown(self) -> None:
        mvp_dashboard.MVP_DATABASE = self.old_database
        self.tmp.cleanup()

    def post(self, path: str, data: dict[str, str]) -> tuple[str, int]:
        payload, status = mvp_dashboard.handle_mvp_post(path, {key: [value] for key, value in data.items()})
        return payload, int(status.value)

    def page(self, path: str) -> str:
        route, _, query = path.partition("?")
        body, status = mvp_dashboard.render_mvp_page(route, query)
        self.assertEqual(status.value, 200, body[:400])
        return body

    def start_real_session(self) -> str:
        payload, status = self.post(
            "/setup/start", {"workspace_id": "MVP Dogfood 001", "idempotency_key": "phase331-real"}
        )
        self.assertEqual(status, 303)
        return payload.split("/setup/", 1)[1].split('"', 1)[0]

    def complete_foundation(self, session_id: str) -> None:
        for step_id in ("welcome", "host_preflight", "workspace", "operator_identity"):
            _, status = self.post(f"/setup/{session_id}/complete", {"step_id": step_id})
            self.assertEqual(status, 303)

    def init_site_repo(self) -> Path:
        repo = self.root / "managed-root" / "site"
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
        (repo / "README.md").write_text("dogfood site\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "-c", "user.name=Dogfood", "-c", "user.email=dogfood@example.invalid", "commit", "-m", "init"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return repo

    def register_destination(self, session_id: str, repo: Path, port: int) -> None:
        _, status = self.post(
            f"/setup/{session_id}/complete",
            {
                "step_id": "publication_destination",
                "display_name": "Dogfood Site",
                "managed_root": str(repo.parent),
                "repository": repo.name,
                "branch": "main",
                "rendering_profile": "generic_yaml",
                "publication_root": "articles",
                "public_url_template": f"http://127.0.0.1:{port}/articles/{{slug}}.md",
            },
        )
        self.assertEqual(status, 303)
        _, status = self.post(f"/setup/{session_id}/complete", {"step_id": "website_account"})
        self.assertEqual(status, 303)

    def create_draft_and_plan(self, session_id: str) -> dict[str, Any]:
        _, status = self.post(
            f"/setup/{session_id}/create-draft",
            {
                "title": "MVP Dogfood Publication 001",
                "markdown_body": "# MVP Dogfood Publication 001\n\nCTA: Open the project overview.",
                "author": "Dogfood Operator",
                "tags": "dogfood,mvp",
            },
        )
        self.assertEqual(status, 303)
        _, status = self.post(f"/setup/{session_id}/complete", {"step_id": "first_content"})
        self.assertEqual(status, 303)
        _, status = self.post(f"/setup/{session_id}/create-plan", {})
        self.assertEqual(status, 303)
        return mvp_dashboard._real_review_payload(mvp_dashboard.alpha_ui_service(), session_id)["publication"]

    @contextlib.contextmanager
    def static_server(self, root: Path):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield int(server.server_address[1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def run_real_publication_flow(self) -> tuple[str, Path, dict[str, Any]]:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        repo = self.init_site_repo()
        with self.static_server(repo) as port:
            self.register_destination(session_id, repo, port)
            self.create_draft_and_plan(session_id)
            _, status = self.post(
                f"/setup/{session_id}/confirm",
                {"confirmation": mvp_dashboard.CONFIRMATION_TEXT, "idempotency_key": "phase331-confirm"},
            )
            self.assertEqual(status, 303)
            result = mvp_dashboard._real_publication_status(mvp_dashboard.alpha_ui_service(), session_id)["publication"]
        return session_id, repo, result


def chromium_available() -> bool:
    return bool(shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome"))
