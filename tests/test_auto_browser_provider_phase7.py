from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from channel_models import ChannelConnection
from channel_store import get_channel_connection, save_channel_connection
from channels.linkedin.provider_state import provider_connection_status, set_provider_connection_status
from channels.linkedin.targets import composer
from plugin_runtime import bootstrap_plugins
from plugins.providers.auto_browser import AutoBrowserConfig, AutoBrowserProvider
from plugins.providers.auto_browser.errors import AutoBrowserConnectionError, AutoBrowserResponseError
from plugins.providers.auto_browser.provider import PROVIDER_ID
from src.core.browser import BrowserSessionOptions, BrowserUnavailableError, HumanTakeoverRequest
from src.core.plugins import PluginCapabilityError
from tests.test_auto_browser_provider_phase5 import FakeAutoBrowserTransport
from tests.test_plugin_runtime_phase2 import Config
from tests.test_support import isolated_channel_store


class RecordingAutoBrowserTransport(FakeAutoBrowserTransport):
    def __init__(self) -> None:
        super().__init__()
        self.create_payloads: list[dict] = []
        self.delete_calls: list[str] = []

    def create_session(self, payload: dict) -> dict:
        self.create_payloads.append(dict(payload))
        return super().create_session(payload)

    def delete_auth_profile(self, profile_name: str) -> dict:
        self.delete_calls.append(profile_name)
        return super().delete_auth_profile(profile_name)


class MissingDeleteRouteTransport(RecordingAutoBrowserTransport):
    def delete_auth_profile(self, profile_name: str) -> dict:
        raise AutoBrowserResponseError("missing route", details={"status": 405})


class CloseFailureTransport(RecordingAutoBrowserTransport):
    def close_session(self, remote_session_id: str) -> dict:
        raise AutoBrowserConnectionError("close timed out")


class UnavailableListTransport(RecordingAutoBrowserTransport):
    def list_sessions(self) -> list[dict]:
        raise AutoBrowserConnectionError("controller unavailable")


class AutoBrowserPhase7Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.transport = RecordingAutoBrowserTransport()
        self.upload_dir = Path(self.tmp.name) / "shared-uploads"
        self.provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(
                enabled=True,
                base_url="http://127.0.0.1:9999",
                shared_upload_host_dir=str(self.upload_dir),
                shared_upload_controller_dir="/data/uploads/incoming",
            ),
            transport=self.transport,
            mapping_path=Path(self.tmp.name) / "sessions.json",
        )

    def test_shared_volume_upload_copies_safe_file_and_hides_original_path(self) -> None:
        image = Path(self.tmp.name) / "fixture.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n")
        session = self.provider.create_session(BrowserSessionOptions(profile_id="linkedin", exclusive=True))
        session.upload(composer.MEDIA_INPUT, image)
        upload_action = self.transport.actions[-1]
        self.assertEqual(upload_action[1], "upload")
        payload = upload_action[2]
        self.assertTrue(str(payload["file_path"]).startswith("/data/uploads/incoming/"))
        self.assertNotIn(str(image), json.dumps(payload))
        self.assertFalse(any(self.upload_dir.rglob("*.png")))

    def test_upload_without_shared_volume_is_explicitly_unsupported(self) -> None:
        provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(enabled=True, base_url="http://127.0.0.1:9999"),
            transport=RecordingAutoBrowserTransport(),
            mapping_path=Path(self.tmp.name) / "sessions-unconfigured.json",
        )
        self.assertEqual(provider.health_check()["upload_capability"], "missing")
        with self.assertRaises(BrowserUnavailableError):
            provider.create_session(BrowserSessionOptions(profile_id="linkedin", exclusive=True))

    def test_auth_profile_delete_is_optional_and_revoked_locally_blocks_reuse(self) -> None:
        result = self.provider.forget_auth_profile_with_audit("linkedin", admin_reason="pilot revoke test")
        self.assertTrue(result["ok"])
        self.assertEqual(result["delete_result"], "revoked_locally")
        status = self.provider.auth_profile_status("linkedin")
        self.assertEqual(status["status"], "revoked_locally")
        self.provider.create_session(BrowserSessionOptions(profile_id="linkedin", exclusive=True))
        self.assertNotIn("auth_profile", self.transport.create_payloads[-1])

    def test_auth_profile_delete_capability_calls_remote_when_enabled(self) -> None:
        provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(
                enabled=True,
                base_url="http://127.0.0.1:9999",
                shared_upload_host_dir=str(self.upload_dir),
                auth_profile_delete_enabled=True,
            ),
            transport=self.transport,
            mapping_path=Path(self.tmp.name) / "sessions-delete.json",
        )
        result = provider.forget_auth_profile_with_audit("linkedin", admin_reason="delete pilot auth")
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.transport.delete_calls), 1)
        self.assertEqual(provider.health_check()["auth_profile_delete_capability"], "available")

    def test_missing_delete_route_falls_back_to_revoked_locally(self) -> None:
        provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(
                enabled=True,
                base_url="http://127.0.0.1:9999",
                shared_upload_host_dir=str(self.upload_dir),
                auth_profile_delete_enabled=True,
            ),
            transport=MissingDeleteRouteTransport(),
            mapping_path=Path(self.tmp.name) / "sessions-missing-delete.json",
        )
        result = provider.forget_auth_profile_with_audit("linkedin", admin_reason="route unavailable")
        self.assertTrue(result["ok"])
        self.assertTrue(result["revoked_locally"])
        self.assertEqual(provider.auth_profile_status("linkedin")["status"], "revoked_locally")

    def test_takeover_reference_is_generic_and_secret_free(self) -> None:
        session = self.provider.create_session(BrowserSessionOptions(profile_id="linkedin", exclusive=True))
        takeover = self.provider.request_human_takeover(
            HumanTakeoverRequest(session_id=session.session_id, reason="fixture login")
        )
        payload = json.dumps(takeover)
        self.assertEqual(takeover["status"], "requested")
        self.assertTrue(takeover["takeover_reference"].startswith("/channels/takeover/"))
        self.assertNotIn("token=secret", payload)
        self.assertNotIn("remote-takeover", payload)
        session.close()

    def test_global_and_account_kill_switches_block_selection_or_session(self) -> None:
        config = Config()
        config.auto_browser_enabled = True
        config.auto_browser_base_url = "http://127.0.0.1:9999"
        config.auto_browser_global_kill_switch = True
        config.browser_provider_default_id = PROVIDER_ID
        runtime = bootstrap_plugins(config, strict=False)
        self.assertEqual(runtime.runtimes[PROVIDER_ID].status.value, "disabled")
        with self.assertRaises(PluginCapabilityError):
            runtime.resolve_provider("browser.session", preferred_provider_id=PROVIDER_ID)

        provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(
                enabled=True,
                base_url="http://127.0.0.1:9999",
                account_kill_switches=("linkedin",),
                shared_upload_host_dir=str(self.upload_dir),
            ),
            transport=RecordingAutoBrowserTransport(),
            mapping_path=Path(self.tmp.name) / "sessions-kill.json",
        )
        with self.assertRaises(BrowserUnavailableError) as raised:
            provider.create_session(BrowserSessionOptions(profile_id="linkedin", exclusive=True))
        self.assertEqual(raised.exception.code, "auto_browser.account_kill_switch")

    def test_close_timeout_releases_local_lock_and_mapping(self) -> None:
        provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(
                enabled=True,
                base_url="http://127.0.0.1:9999",
                shared_upload_host_dir=str(self.upload_dir),
            ),
            transport=CloseFailureTransport(),
            mapping_path=Path(self.tmp.name) / "sessions-close.json",
        )
        session = provider.create_session(BrowserSessionOptions(profile_id="linkedin", exclusive=True))
        session.close()
        self.assertFalse(provider.profile_status("linkedin").busy)
        self.assertEqual(provider.reconcile_sessions()["stale_mapping_count"], 0)

    def test_network_reconciliation_chaos_is_reported_without_cleanup(self) -> None:
        provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(
                enabled=True,
                base_url="http://127.0.0.1:9999",
                shared_upload_host_dir=str(self.upload_dir),
            ),
            transport=UnavailableListTransport(),
            mapping_path=Path(self.tmp.name) / "sessions-network.json",
        )
        summary = provider.reconcile_sessions()
        self.assertEqual(summary["status"], "unavailable")
        self.assertEqual(summary["error_code"], "auto_browser.connection_error")

    def test_rollback_to_legacy_preserves_provider_bound_status(self) -> None:
        connection = ChannelConnection(
            id="connection_linkedin",
            channel_id="linkedin",
            mode="playwright_local",
            status="connected",
            browser_provider_id=PROVIDER_ID,
            provider_connection_state_json={
                PROVIDER_ID: {"status": "authentication_required"},
                "provider.browser.legacy": {"status": "connected"},
            },
        )
        set_provider_connection_status(
            connection,
            provider_id=PROVIDER_ID,
            status="authentication_required",
        )
        connection.browser_provider_id = "provider.browser.legacy"
        save_channel_connection(connection)
        loaded = get_channel_connection("linkedin")
        assert loaded is not None
        self.assertEqual(loaded.browser_provider_id, "provider.browser.legacy")
        self.assertEqual(provider_connection_status(loaded, "provider.browser.legacy"), "connected")
        self.assertEqual(provider_connection_status(loaded, PROVIDER_ID), "authentication_required")

    def test_pilot_readiness_is_machine_readable(self) -> None:
        readiness = self.provider.pilot_readiness()
        self.assertTrue(readiness["machine_readable"])
        self.assertEqual(readiness["status"], "ready")
        provider = AutoBrowserProvider(
            auto_browser_config=AutoBrowserConfig(enabled=True, base_url="http://127.0.0.1:9999"),
            transport=RecordingAutoBrowserTransport(),
            mapping_path=Path(self.tmp.name) / "sessions-not-ready.json",
        )
        self.assertEqual(provider.pilot_readiness()["status"], "not_ready")
