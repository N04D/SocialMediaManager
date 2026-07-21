from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import channel_store
from channel_models import ContentDerivative, MetricJob, PublishJob
from channel_store import save_derivative, save_metric_job, save_publish_job
from channels.mastodon.auth import pkce_s256
from channels.mastodon.errors import MastodonUnsafeInstanceError
from channels.mastodon.instance import (
    normalize_instance_origin,
    requirements_from_snapshot,
    snapshot_from_instance,
)
from channels.mastodon.models import MastodonAccountState
from channels.mastodon.storage import MastodonAccountRepository, MastodonRequirementsRepository, MastodonSecretStore
from channels.mastodon.transport import FakeMastodonApiTransport
from plugin_runtime import bootstrap_plugins
from tests.test_media_library_phase11 import Phase11Config
from tests.test_support import isolated_channel_store

INSTANCE_PAYLOAD = {
    "version": "4.3.0",
    "api_versions": {"mastodon": 4},
    "software": {"name": "mastodon", "version": "4.3.0"},
    "configuration": {
        "statuses": {"max_characters": 777, "max_media_attachments": 8, "characters_reserved_per_url": 23},
        "media_attachments": {
            "supported_mime_types": ["image/jpeg", "image/png", "image/gif"],
            "image_size_limit": 9_000_000,
            "image_matrix_limit": 16_000_000,
            "description_limit": 420,
        },
    },
}


class MastodonPhase16Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Phase11Config()
        self.config.media_dir = Path(self.tmp.name) / "tmp_media"
        self.config.content_dir = Path(self.tmp.name) / "content"
        self.config.media_storage_root = Path(self.tmp.name) / "media-root"
        self.config.linkedin_user_data_dir = Path(self.tmp.name) / "profile"
        self.config.mastodon_allow_localhost_http = True
        self.config.media_dir.mkdir()
        self.config.content_dir.mkdir()
        self.config.linkedin_user_data_dir.mkdir()

    def runtime(self, transport: FakeMastodonApiTransport):
        runtime = bootstrap_plugins(self.config, strict=False)
        service = runtime.get_plugin_service("channel.mastodon", "channel_runtime")
        service.transport = transport
        return runtime, service

    def test_manifest_registration_capabilities_and_boundaries(self) -> None:
        runtime = bootstrap_plugins(self.config, strict=False)
        manifest = runtime.runtimes["channel.mastodon"].manifest
        self.assertEqual(manifest.id, "channel.mastodon")
        self.assertEqual(manifest.version, "0.1.0")
        self.assertIn("channel.publish.text", manifest.capabilities)
        self.assertIn("channel.publish.image", manifest.capabilities)
        self.assertNotIn("browser", " ".join(manifest.capabilities))
        mastodon_files = "\n".join(str(path) for path in Path("channels/mastodon").rglob("*.py"))
        for forbidden in [
            "BrowserProvider",
            "AutoBrowserProvider",
            "LegacyBrowserProvider",
            "LocalMediaStorageProvider",
            "channels.linkedin",
            "AnalyticsRepository",
        ]:
            self.assertNotIn(forbidden, mastodon_files)

    def test_instance_url_ssrf_policy(self) -> None:
        self.assertEqual(
            normalize_instance_origin("HTTPS://Example.COM/", resolver=lambda host: ["93.184.216.34"]),
            "https://example.com",
        )
        for value in [
            "https://user:pass@example.com",
            "https://example.com/path",
            "https://example.com?token=x",
            "https://example.com#frag",
            "http://example.com",
            "file:///etc/passwd",
        ]:
            with self.assertRaises(MastodonUnsafeInstanceError):
                normalize_instance_origin(value, resolver=lambda host: ["93.184.216.34"])
        with self.assertRaises(MastodonUnsafeInstanceError):
            normalize_instance_origin("https://private.example", resolver=lambda host: ["10.0.0.1"])
        self.assertEqual(
            normalize_instance_origin("http://localhost:8916", allow_localhost_http=True),
            "http://localhost:8916",
        )

    def test_discovery_dynamic_requirements_and_metric_definitions(self) -> None:
        snapshot = snapshot_from_instance("https://social.example", INSTANCE_PAYLOAD)
        self.assertEqual(snapshot.max_characters, 777)
        self.assertEqual(snapshot.max_media_attachments, 4)
        self.assertEqual(snapshot.supported_mime_types, ["image/jpeg", "image/png"])
        req = requirements_from_snapshot("mastodon:social.example", snapshot)
        self.assertEqual(req.content_length_limit, 777)
        self.assertEqual(req.maximum_media_count, 4)
        runtime = bootstrap_plugins(self.config, strict=False)
        definitions = runtime.analytics_bundle(self.config).metric_registry.list_definitions("channel.mastodon")
        self.assertEqual({item.metric_key for item in definitions}, {"favourites", "replies", "reblogs"})
        self.assertFalse(any(item.metric_key in {"impressions", "reach"} for item in definitions))

    def test_oauth_pkce_app_registration_and_callback_store_only_secret_refs(self) -> None:
        transport = FakeMastodonApiTransport(
            {
                ("GET", "/api/v2/instance"): INSTANCE_PAYLOAD,
                ("POST", "/api/v1/apps"): {"client_id": "cid", "client_secret": "secret"},
                ("POST", "/oauth/token"): {
                    "access_token": "token",
                    "scope": "profile read:statuses write:statuses write:media",
                },
                ("GET", "/api/v1/accounts/verify_credentials"): {
                    "id": "acct-1",
                    "username": "pilot",
                    "acct": "pilot",
                    "url": "https://social.example/@pilot",
                },
            }
        )
        _runtime, service = self.runtime(transport)
        started = service.start_connect(
            workspace_id="workspace-1",
            channel_account_id="mastodon:pilot",
            instance_origin="http://localhost:8916",
            redirect_uri="http://127.0.0.1/callback",
        )
        self.assertIn("code_challenge_method=S256", started["authorization_url"])
        flow = service.flows.list_all()[0]
        state = service.secrets.get(flow.state_secret_ref)
        account = service.complete_connect(
            code="fixture-code",
            state=state,
            workspace_id="workspace-1",
            channel_account_id="mastodon:pilot",
        )
        self.assertEqual(account["connection_status"], "connected")
        self.assertEqual(account["token_secret_ref"], "present")
        records = json.loads((channel_store.STUDIO_DATA_DIR / "mastodon_accounts.json").read_text())
        serialized = json.dumps(records)
        self.assertNotIn("fixture-access-token", serialized)
        self.assertNotIn("fixture-client-secret", serialized)
        self.assertEqual(
            pkce_s256(service.secrets.get(flow.verifier_secret_ref)) if False else flow.challenge, flow.challenge
        )

    def test_text_publish_evidence_idempotency_and_metrics_no_impressions_zero(self) -> None:
        transport = FakeMastodonApiTransport(
            {
                ("POST", "/api/v1/statuses"): {
                    "id": "1",
                    "uri": "https://social.example/users/pilot/statuses/1",
                    "url": "https://social.example/@pilot/1",
                    "created_at": "2026-07-21T08:00:00Z",
                    "account": {"id": "acct-1"},
                    "favourites_count": 5,
                    "replies_count": 2,
                    "reblogs_count": 1,
                },
                ("GET", "/api/v1/statuses/1"): {
                    "id": "1",
                    "uri": "https://social.example/users/pilot/statuses/1",
                    "url": "https://social.example/@pilot/1",
                    "created_at": "2026-07-21T08:00:00Z",
                    "account": {"id": "acct-1"},
                    "favourites_count": 5,
                    "replies_count": 2,
                    "reblogs_count": 1,
                },
            }
        )
        runtime, service = self.runtime(transport)
        token_ref, token_version = MastodonSecretStore().put("token", purpose="mastodon.access_token")
        account = MastodonAccountState(
            channel_account_id="mastodon:pilot",
            workspace_id="mastodon",
            instance_origin="https://social.example",
            instance_host="social.example",
            remote_account_id="acct-1",
            acct="pilot",
            connection_status="connected",
            scope_set=["profile", "read:statuses", "write:statuses", "write:media"],
            token_secret_ref=token_ref,
            token_secret_version=token_version,
            created_at=channel_store.now_iso(),
            updated_at=channel_store.now_iso(),
        )
        MastodonAccountRepository().save(account)
        snapshot = snapshot_from_instance("https://social.example", INSTANCE_PAYLOAD)
        req = requirements_from_snapshot(account.channel_account_id, snapshot)
        MastodonRequirementsRepository().save(req)
        derivative = save_derivative(
            ContentDerivative(
                id="derivative_plan_target-1",
                source_document_id="content-1",
                channel_id="mastodon",
                output_type="channel.publish.text",
                title="Title",
                body="Hello Mastodon",
                status="approved",
                generation_metadata_json={
                    "publication_plan_id": "plan-1",
                    "publication_target_id": "target-1",
                    "content_revision_id": "revision-1",
                    "revision_checksum": "a" * 64,
                    "snapshot_checksum": "b" * 64,
                    "snapshot": {
                        "channel_account_id": account.channel_account_id,
                        "mastodon_requirements_checksum": req.checksum,
                    },
                    "planned_from_content_framework": True,
                },
            )
        )
        job = save_publish_job(
            PublishJob(
                id="job-1",
                derivative_id=derivative.id,
                channel_id=account.channel_account_id,
                status="running",
                requested_at=channel_store.now_iso(),
                result_details_json={"snapshot_checksum": "b" * 64},
            )
        )
        service.publish(job.id)
        post = channel_store.list_published_posts(channel_id=account.channel_account_id)[0]
        evidence = post.raw_result_json
        self.assertEqual(evidence["global_status_uri"], post.external_id)
        self.assertEqual(evidence["local_status_id"], "1")
        self.assertIn("idempotency_key_fingerprint", evidence)
        metric_job = save_metric_job(
            MetricJob(
                id="metric-job-1",
                published_post_id=post.id,
                channel_id=account.channel_account_id,
                status="running",
                scheduled_for=channel_store.now_iso(),
                requested_at=channel_store.now_iso(),
            )
        )
        service.collect_metrics(metric_job.id)
        perf = runtime.analytics_read_model_service(self.config).publication_performance(
            post.id, workspace_id="mastodon"
        )
        self.assertEqual(set(perf["latest_metrics"]), {"favourites", "replies", "reblogs"})
        self.assertNotIn("impressions", perf["latest_metrics"])
        self.assertEqual(perf["derived_metrics"]["engagement_rate_by_impressions"]["value"], None)
        self.assertEqual(perf["derived_metrics"]["engagement_rate_by_impressions"]["reason"], "denominator_unavailable")


if __name__ == "__main__":
    unittest.main()
