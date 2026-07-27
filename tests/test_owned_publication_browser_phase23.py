from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import dashboard


class OwnedPublicationBrowserPhase23Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "owned.sqlite3"
        self.config_path = Path(self.tmp.name) / "config.json"
        self.content_dir = Path(self.tmp.name) / "browser-content"
        self.config_path.write_text(json.dumps({"content_dir": str(self.content_dir)}), encoding="utf-8")
        self.original_service_factory = dashboard.owned_publication_service
        dashboard.owned_publication_service = lambda: __import__(
            "src.core.owned_publication.service", fromlist=["OwnedPublicationWorkspaceService"]
        ).OwnedPublicationWorkspaceService(database_path=self.db)
        self.handler_class = type("Phase23DashboardHandler", (dashboard.DashboardHandler,), {})
        self.handler_class.config_path = str(self.config_path)
        self.handler_class.config = SimpleNamespace(content_dir=self.content_dir, rss_url="https://example.test/feed")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler_class)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        dashboard.owned_publication_service = self.original_service_factory
        self.tmp.cleanup()

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict | str]:
        connection = HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        connection.close()
        try:
            return response.status, json.loads(raw)
        except json.JSONDecodeError:
            return response.status, raw

    def test_article_to_funnel_flow_survives_reload_and_server_restart(self) -> None:
        status, page = self.request("GET", "/content/new")
        self.assertEqual(status, 200, page)
        self.assertIn("Owned publication workspace", str(page))
        status, created = self.request(
            "POST",
            "/api/content",
            {"id": "browser-content", "title": "Browser Flow", "markdown_body": "# Browser Flow"},
        )
        self.assertEqual(status, 200)
        draft = created["content"]
        status, saved = self.request(
            "PATCH",
            "/api/content/browser-content",
            {"expected_version": draft["version"], "title": "Browser Flow Saved", "markdown_body": "# Saved"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(saved["draft"]["title"], "Browser Flow Saved")
        status, conflict = self.request(
            "PATCH",
            "/api/content/browser-content",
            {"expected_version": draft["version"], "title": "Stale"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error"]["code"], "workspace.conflict")
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler_class)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        status, reloaded = self.request("GET", "/api/content/browser-content")
        self.assertEqual(status, 200)
        self.assertEqual(reloaded["content"]["title"], "Browser Flow Saved")
        status, storage = self.request("GET", "/api/storage/health")
        self.assertEqual(status, 200)
        self.assertEqual(storage["production_source"], "database-backed")
        status, recon = self.request("GET", "/api/reconciliation")
        self.assertEqual(status, 200)
        self.assertIn("items", recon)
        status, funnel = self.request("GET", "/api/funnels/content-owned-1")
        self.assertEqual(status, 200)
        self.assertFalse(funnel["causality_claimed"])


if __name__ == "__main__":
    unittest.main()
