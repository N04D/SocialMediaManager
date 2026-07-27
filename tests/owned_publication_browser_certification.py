from __future__ import annotations

import json
import shutil
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import dashboard
from src.core.owned_publication.persistence import DatabaseOwnedPublicationRepository


def chromium_executable() -> str:
    for candidate in (
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
        "/snap/bin/chromium",
    ):
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise AssertionError("No real Chromium browser executable available for phase 23.1 certification.")


class DashboardBrowserServer:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.database_path = self.root / "owned.sqlite3"
        self.content_dir = self.root / "managed-content"
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps({"content_dir": str(self.content_dir)}), encoding="utf-8")
        self.original_service_factory = dashboard.owned_publication_service
        self.events: list[dict[str, Any]] = []
        dashboard.owned_publication_service = lambda: __import__(
            "src.core.owned_publication.service", fromlist=["OwnedPublicationWorkspaceService"]
        ).OwnedPublicationWorkspaceService(database_path=self.database_path)
        self.handler_class = type("Phase231DashboardHandler", (dashboard.DashboardHandler,), {})
        self.handler_class.config_path = str(self.config_path)
        self.handler_class.config = SimpleNamespace(content_dir=self.content_dir, rss_url="https://example.test/feed")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler_class)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])
        self.events.append({"event": "server started", "port": self.port})

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def repository(self) -> DatabaseOwnedPublicationRepository:
        return DatabaseOwnedPublicationRepository(self.database_path)

    def restart(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler_class)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])
        self.events.append({"event": "server restart", "port": self.port})

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        dashboard.owned_publication_service = self.original_service_factory
        self.tmp.cleanup()


def expect_no_sensitive_output(value: str) -> None:
    lowered = value.lower()
    for forbidden in ("authorization", "private key", "traceback", "select *", "/home/"):
        if forbidden in lowered:
            raise AssertionError(f"Sensitive browser output leaked marker: {forbidden}")
