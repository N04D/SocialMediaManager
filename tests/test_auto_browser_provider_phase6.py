from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

from channel_models import ChannelConnection
from channel_store import get_channel_connection, save_channel_connection
from channels.linkedin.provider_state import provider_connection_status
from plugins.providers.auto_browser import AutoBrowserConfig, AutoBrowserProvider
from plugins.providers.auto_browser.errors import AutoBrowserConnectionError
from plugins.providers.auto_browser.provider import PROVIDER_ID
from src.core.browser import BrowserSessionOptions, FileBackedBrowserProfileLockManager
from tests.test_auto_browser_provider_phase5 import FakeAutoBrowserTransport
from tests.test_plugin_runtime_phase2 import Config
from tests.test_support import isolated_channel_store

_DOCTOR_PATH = Path(__file__).resolve().parents[1] / "integrations" / "auto-browser" / "doctor.py"
_DOCTOR_SPEC = importlib.util.spec_from_file_location("auto_browser_doctor", _DOCTOR_PATH)
assert _DOCTOR_SPEC is not None and _DOCTOR_SPEC.loader is not None
doctor = importlib.util.module_from_spec(_DOCTOR_SPEC)
sys.modules["auto_browser_doctor"] = doctor
_DOCTOR_SPEC.loader.exec_module(doctor)


class ReconciliationTransport(FakeAutoBrowserTransport):
    def __init__(self) -> None:
        super().__init__()
        self.remote_only: list[dict[str, Any]] = []

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = list(super().list_sessions())
        sessions.extend(self.remote_only)
        return sessions


class AutoBrowserReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.transport = ReconciliationTransport()
        self.provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(
                enabled=True,
                base_url="http://127.0.0.1:9999",
                shared_upload_host_dir=str(Path(self.tmp.name) / "uploads"),
            ),
            transport=self.transport,
            lock_manager=FileBackedBrowserProfileLockManager(Path(self.tmp.name) / "locks"),
            mapping_path=Path(self.tmp.name) / "sessions.json",
        )

    def test_reconcile_mapping_and_remote_session_exist(self) -> None:
        session = self.provider.create_session(BrowserSessionOptions(profile_id="linkedin", exclusive=True))
        summary = self.provider.reconcile_sessions()
        self.assertEqual(summary["status"], "consistent")
        self.assertEqual(summary["stale_mapping_count"], 0)
        session.close()

    def test_reconcile_mapping_exists_remote_missing(self) -> None:
        session = self.provider.create_session(BrowserSessionOptions(profile_id="linkedin", exclusive=True))
        self.transport.sessions.clear()
        summary = self.provider.reconcile_sessions()
        self.assertEqual(summary["status"], "inconsistent_state")
        self.assertEqual(summary["stale_mapping_count"], 1)
        cleanup = self.provider.cleanup_stale_mapping(session.session_id, admin_reason="remote session missing")
        self.assertTrue(cleanup["ok"])
        self.assertFalse(self.provider.profile_status("linkedin").busy)

    def test_reconcile_remote_exists_mapping_missing(self) -> None:
        self.transport.remote_only.append(
            {
                "id": "remote-owned",
                "status": "active",
                "metadata": {"application_id": "social-media-manager", "provider_id": PROVIDER_ID},
            }
        )
        self.transport.remote_only.append(
            {
                "id": "remote-other",
                "status": "active",
                "metadata": {"application_id": "other"},
            }
        )
        summary = self.provider.reconcile_sessions()
        self.assertEqual(summary["orphaned_remote_count"], 1)
        self.assertNotIn("remote-other", json.dumps(summary))

    def test_auth_profile_status_and_forget_audit(self) -> None:
        status = self.provider.auth_profile_status("linkedin")
        self.assertTrue(status["exists"])
        result = self.provider.forget_auth_profile_with_audit(
            "linkedin",
            admin_reason="rotate test login",
            previous_status="connected",
        )
        self.assertTrue(result["ok"])
        audit_path = Path(self.tmp.name) / "auto_browser_forget_login_audit.jsonl"
        self.assertFalse(audit_path.exists(), "provider should use channel_store isolated path, not temp root")

    def test_forget_remote_failure_preserves_local_state(self) -> None:
        class FailingDeleteTransport(ReconciliationTransport):
            def delete_auth_profile(self, profile_name: str) -> dict[str, Any]:
                raise AutoBrowserConnectionError("delete failed")

        provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(
                enabled=True,
                base_url="http://127.0.0.1:9999",
                shared_upload_host_dir=str(Path(self.tmp.name) / "uploads"),
                auth_profile_delete_enabled=True,
            ),
            transport=FailingDeleteTransport(),
            lock_manager=FileBackedBrowserProfileLockManager(Path(self.tmp.name) / "locks-2"),
            mapping_path=Path(self.tmp.name) / "sessions-2.json",
        )
        result = provider.forget_auth_profile_with_audit("linkedin", admin_reason="rotate test login")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "auto_browser.connection_error")


class _DoctorController(BaseHTTPRequestHandler):
    status_mode = "healthy"

    def do_GET(self) -> None:
        if self.status_mode == "unauthorized":
            self._json({"detail": "unauthorized"}, status=401)
            return
        if self.path.startswith("/readyz") and self.status_mode == "not_ready":
            self._json({"status": "not_ready"}, status=409)
            return
        if self.path.startswith("/version"):
            self._json(
                {
                    "version": "1.4.0",
                    "features": {
                        "takeover": True,
                        "auth_profiles": True,
                        "uploads": True,
                        "evaluation": True,
                        "screenshots": True,
                    },
                }
            )
            return
        if self.path.startswith("/sessions/") and "/observe" in self.path:
            self._json(
                {
                    "url": "http://127.0.0.1:8765/",
                    "title": "Auto Browser Fixture",
                    "elements": [
                        {"id": "primary", "role": "button", "name": "Primary action", "visible": True, "enabled": True}
                    ],
                }
            )
            return
        if self.path.startswith("/sessions"):
            self._json([])
            return
        self._json({"status": "ok"})

    def do_POST(self) -> None:
        if self.path == "/sessions":
            self._json({"session_id": "remote-doctor", "status": "active"})
            return
        if self.path.endswith("/screenshot"):
            self._json({"artifact_id": "shot", "kind": "screenshot"})
            return
        if self.path.endswith("/execute"):
            self._json({"result": {"ok": True}})
            return
        self._json({"status": "ok"})

    def do_DELETE(self) -> None:
        self._json({"status": "closed"})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, payload: Any, *, status: int = 200) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class AutoBrowserDoctorTests(unittest.TestCase):
    def _server(self, mode: str = "healthy"):
        _DoctorController.status_mode = mode
        server = ThreadingHTTPServer(("127.0.0.1", 0), _DoctorController)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return server

    def _args(self, base_url: str) -> argparse.Namespace:
        return argparse.Namespace(
            base_url=base_url,
            bearer_token_env="AUTO_BROWSER_TEST_TOKEN",
            operator_id="operator-a",
            expected_version="1.4.0",
            fixture_url="http://127.0.0.1:8765/",
            json=False,
        )

    def test_doctor_healthy_check_and_redaction(self) -> None:
        server = self._server()
        with patch.dict(os.environ, {"AUTO_BROWSER_TEST_TOKEN": "super-secret"}):
            checks, exit_code = doctor.run_checks(self._args(f"http://127.0.0.1:{server.server_port}"))
        self.assertEqual(exit_code, 0)
        payload = json.dumps([check.to_dict() for check in checks])
        self.assertIn("***redacted***", payload)
        self.assertNotIn("super-secret", payload)

    def test_doctor_missing_config_fails(self) -> None:
        checks, exit_code = doctor.run_checks(self._args(""))
        self.assertNotEqual(exit_code, 0)
        self.assertEqual(checks[0].status, "FAIL")

    def test_doctor_unauthorized_fails(self) -> None:
        server = self._server("unauthorized")
        checks, exit_code = doctor.run_checks(self._args(f"http://127.0.0.1:{server.server_port}"))
        self.assertNotEqual(exit_code, 0)
        self.assertIn("FAIL", [check.status for check in checks])


class ProviderStateAndPipelineBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)

    def test_legacy_and_auto_browser_statuses_are_separate(self) -> None:
        connection = ChannelConnection(
            id="connection_linkedin",
            channel_id="linkedin",
            mode="playwright_local",
            status="connected",
            browser_provider_id="provider.browser.legacy",
            provider_connection_state_json={
                "provider.browser.legacy": {"status": "connected"},
                PROVIDER_ID: {"status": "authentication_required"},
            },
        )
        save_channel_connection(connection)
        loaded = get_channel_connection("linkedin")
        assert loaded is not None
        self.assertEqual(provider_connection_status(loaded, "provider.browser.legacy"), "connected")
        self.assertEqual(provider_connection_status(loaded, PROVIDER_ID), "authentication_required")

    def test_pipeline_boundary_rejects_auto_browser_account(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "phase6_pipeline", Path(__file__).resolve().parents[1] / "pipeline.py"
        )
        assert spec is not None and spec.loader is not None
        pipeline_module = importlib.util.module_from_spec(spec)
        sys.modules["phase6_pipeline"] = pipeline_module
        spec.loader.exec_module(pipeline_module)
        ensure_legacy_pipeline_linkedin_allowed = pipeline_module.ensure_legacy_pipeline_linkedin_allowed

        config = Config()
        config.linkedin_browser_provider_id = ""
        save_channel_connection(
            ChannelConnection(
                id="connection_linkedin",
                channel_id="linkedin",
                mode="playwright_local",
                status="connected",
                browser_provider_id=PROVIDER_ID,
            )
        )
        with self.assertRaises(RuntimeError):
            ensure_legacy_pipeline_linkedin_allowed(config)
