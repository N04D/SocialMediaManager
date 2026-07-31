from __future__ import annotations

import json
import re
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any
from urllib.request import Request, urlopen

import dashboard
import mvp_dashboard
from tests.phase331_support import Phase331TestCase


class Phase332TestCase(Phase331TestCase):
    def create_real_draft(self, session_id: str, *, title: str = "MVP Dogfood Publication 332") -> str:
        payload, status = self.post(
            f"/setup/{session_id}/create-draft",
            {
                "title": title,
                "slug": "mvp-dogfood-publication-332",
                "markdown_body": "# MVP Dogfood Publication 332\n\nCanonical draft identity.",
                "author": "Dogfood Operator",
                "tags": "dogfood,phase33.2",
            },
        )
        self.assertEqual(status, 303)
        return payload.split("/content/", 1)[1].split("/compose", 1)[0]

    def prepared_session_with_draft(self) -> tuple[str, str]:
        session_id = self.start_real_session()
        self.complete_foundation(session_id)
        draft_id = self.create_real_draft(session_id)
        return session_id, draft_id

    def autosave(self, draft_id: str, expected_version: int, **updates: Any) -> dict[str, Any]:
        payload = {
            "draft_id": draft_id,
            "expected_version": expected_version,
            "idempotency_key": f"phase332-autosave-{draft_id}-{expected_version}-{len(updates)}",
            **updates,
        }
        return mvp_dashboard.owned_service().autosave(draft_id, payload)

    def api_get_content(self, base_url: str, draft_id: str) -> dict[str, Any]:
        with urlopen(f"{base_url}/api/content/{draft_id}", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))["content"]

    def api_patch_content(self, base_url: str, draft_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        request = Request(
            f"{base_url}/api/content/{draft_id}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        try:
            with urlopen(request, timeout=10) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            response = getattr(exc, "fp", None)
            status = int(getattr(exc, "code", 0))
            body = json.loads(response.read().decode("utf-8")) if response else {"error": str(exc)}
            return status, body

    def live_dashboard(self):
        (self.root / "config.json").write_text(
            json.dumps({"content_dir": str(self.root / "content")}), encoding="utf-8"
        )
        handler = type("Phase332Handler", (dashboard.DashboardHandler,), {})
        handler.config_path = str(self.root / "config.json")
        handler.config = SimpleNamespace(content_dir=self.root / "content", rss_url="https://example.invalid/feed")
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, f"http://127.0.0.1:{server.server_address[1]}"

    def draft_id_from_composer_route(self, route: str) -> str:
        match = re.search(r"/content/([^/]+)/compose", route)
        self.assertIsNotNone(match, route)
        return str(match.group(1))
