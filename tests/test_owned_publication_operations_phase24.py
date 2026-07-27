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
from src.core.owned_publication import (
    OPERATIONS_HEALTH_CONTRACT_VERSION,
    OPERATIONS_WORKER_CONTRACT_VERSION,
    OWNED_PUBLICATION_OPERATIONS_VERSION,
    PRODUCTION_READINESS_CONTRACT_VERSION,
    RETENTION_POLICY_CONTRACT_VERSION,
    STORAGE_BACKUP_CONTRACT_VERSION,
    STORAGE_RESTORE_CONTRACT_VERSION,
    SUPPORT_BUNDLE_CONTRACT_VERSION,
)
from src.core.owned_publication.service import OwnedPublicationWorkspaceService


class OperationsServer:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "owned.sqlite3"
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps({"content_dir": str(self.root / "managed")}), encoding="utf-8")
        self.original = dashboard.owned_publication_service
        dashboard.owned_publication_service = lambda: OwnedPublicationWorkspaceService(database_path=self.db)
        self.handler = type("Phase24Handler", (dashboard.DashboardHandler,), {})
        self.handler.config_path = str(self.config_path)
        self.handler.config = SimpleNamespace(content_dir=self.root / "managed", rss_url="https://example.test/feed")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.port = int(self.server.server_address[1])

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        dashboard.owned_publication_service = self.original
        self.tmp.cleanup()

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        connection = HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode()
        connection.close()
        return response.status, json.loads(raw)


class OwnedPublicationOperationsPhase24Tests(unittest.TestCase):
    def test_contract_versions_are_added_without_changing_prior_contracts(self) -> None:
        self.assertEqual(OWNED_PUBLICATION_OPERATIONS_VERSION, "0.1.0")
        self.assertEqual(OPERATIONS_WORKER_CONTRACT_VERSION, "1.0")
        self.assertEqual(OPERATIONS_HEALTH_CONTRACT_VERSION, "1.0")
        self.assertEqual(STORAGE_BACKUP_CONTRACT_VERSION, "1.0")
        self.assertEqual(STORAGE_RESTORE_CONTRACT_VERSION, "1.0")
        self.assertEqual(RETENTION_POLICY_CONTRACT_VERSION, "1.0")
        self.assertEqual(PRODUCTION_READINESS_CONTRACT_VERSION, "1.0")
        self.assertEqual(SUPPORT_BUNDLE_CONTRACT_VERSION, "1.0")

    def test_health_endpoints_operations_dashboard_and_backup_api(self) -> None:
        server = OperationsServer()
        self.addCleanup(server.close)
        status, live = server.request("GET", "/health/live")
        self.assertEqual(status, 200)
        self.assertTrue(live["liveness"])
        status, ready = server.request("GET", "/health/ready")
        self.assertEqual(status, 200)
        self.assertTrue(ready["ready"])
        status, health = server.request("GET", "/api/operations/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["workers"]["worker_execution_model"], "thread")
        status, created = server.request(
            "POST", "/api/operations/backups", {"backup_destination_reference_id": "local-managed"}
        )
        self.assertEqual(status, 201)
        backup_id = created["backup"]["id"]
        status, catalog = server.request("GET", "/api/operations/backups")
        self.assertEqual(status, 200)
        self.assertEqual(catalog["backups"][0]["id"], backup_id)
        status, validation = server.request("POST", f"/api/operations/backups/{backup_id}/validate", {})
        self.assertEqual(status, 200)
        self.assertEqual(validation["restore_validation"]["status"], "valid")
        status, release = server.request("GET", "/api/operations/release-check")
        self.assertEqual(status, 200)
        self.assertTrue(release["report"]["owned_publication_operations_ready"])
        self.assertFalse(release["report"]["external_plugin_sandbox_ready"])
        status, page = server.request("GET", "/api/operations/health")
        self.assertNotIn("private key", json.dumps(page).lower())

    def test_release_workflow_and_certification_script_are_present(self) -> None:
        workflow = Path(".github/workflows/owned-publication-operations.yml").read_text(encoding="utf-8")
        wrapper = Path("scripts/owned-publication-certify.py").read_text(encoding="utf-8")
        self.assertIn("Owned Publication Browser and Worker Certification", workflow)
        self.assertIn("Owned Publication Release Gate", workflow)
        self.assertIn("playwright install", workflow)
        self.assertIn("required_skips", wrapper)
        self.assertNotIn("cookies", workflow.lower())


if __name__ == "__main__":
    unittest.main()
