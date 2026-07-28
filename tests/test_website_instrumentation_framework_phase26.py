from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from integrations.website_instrumentation.scenarios import default_snapshot_payload, instrumentation_config_payload
from src.core.website_instrumentation import (
    PLAUSIBLE_BROWSER_BRIDGE_VERSION,
    WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION,
    WEBSITE_CONSENT_MODE_CONTRACT_VERSION,
    WEBSITE_EVENT_ENVELOPE_CONTRACT_VERSION,
    WEBSITE_INSTRUMENTATION_MANIFEST_CONTRACT_VERSION,
    WEBSITE_INSTRUMENTATION_PROFILE_CONTRACT_VERSION,
    WebsiteInstrumentationService,
)
from src.core.website_instrumentation.consent import default_consent_allowed
from src.core.website_instrumentation.errors import WebsiteInstrumentationError
from src.core.website_instrumentation.events import SMM_CONVERSION_EVENT, SMM_CTA_EVENT, allowed_provider_properties
from src.core.website_instrumentation.manifests import build_manifest
from src.core.website_instrumentation.models import (
    WebsiteInstrumentationEvent,
    normalize_attribution_from_url,
)


class WebsiteInstrumentationFrameworkPhase26Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = WebsiteInstrumentationService(database_path=Path(self.tmp.name) / "owned.sqlite3")
        self.config = self.service.create_config(instrumentation_config_payload())["config"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_contract_versions_profiles_and_config_boundaries(self) -> None:
        self.assertEqual(WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION, "0.1.0")
        self.assertEqual(WEBSITE_INSTRUMENTATION_PROFILE_CONTRACT_VERSION, "1.0")
        self.assertEqual(WEBSITE_INSTRUMENTATION_MANIFEST_CONTRACT_VERSION, "1.0")
        self.assertEqual(WEBSITE_EVENT_ENVELOPE_CONTRACT_VERSION, "1.0")
        self.assertEqual(WEBSITE_CONSENT_MODE_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLAUSIBLE_BROWSER_BRIDGE_VERSION, "0.1.0")
        profiles = {item["id"] for item in self.service.profiles_payload()["profiles"]}
        self.assertGreaterEqual(
            profiles, {"generic_vanilla", "astro", "hugo", "jekyll", "eleventy", "nextjs", "plausible_generic"}
        )
        with self.assertRaises(WebsiteInstrumentationError):
            self.service.create_config(
                instrumentation_config_payload()
                | {"id": "bad-origin", "expected_script_origin_reference": "https://evil.test/runtime.js"}
            )
        with self.assertRaises(WebsiteInstrumentationError):
            self.service.update_config(self.config["id"], {"expected_version": 99, "enabled": False})

    def test_manifest_is_deterministic_snapshot_bound_and_opaque(self) -> None:
        manifest_a = build_manifest(self.service.repository.get_config(self.config["id"]), default_snapshot_payload())
        manifest_b = build_manifest(self.service.repository.get_config(self.config["id"]), default_snapshot_payload())
        self.assertEqual(manifest_a.checksum, manifest_b.checksum)
        self.assertEqual(manifest_a.content_revision_id, "revision-owned-1")
        self.assertTrue(manifest_a.page_context.page_id.startswith("smm_page_"))
        self.assertTrue(manifest_a.page_context.publication_id.startswith("smm_publication_"))
        self.assertNotIn("Fixture article", str(asdict(manifest_a)))
        changed = default_snapshot_payload() | {"content_revision_id": "revision-owned-2"}
        manifest_c = build_manifest(self.service.repository.get_config(self.config["id"]), changed)
        self.assertNotEqual(manifest_a.checksum, manifest_c.checksum)

    def test_event_property_allowlist_attribution_and_consent(self) -> None:
        manifest = build_manifest(self.service.repository.get_config(self.config["id"]), default_snapshot_payload())
        event = WebsiteInstrumentationEvent(
            schema_version="1.0",
            event_type="cta_click",
            event_name=SMM_CTA_EVENT,
            page_context=manifest.page_context,
            event_context={"cta_id": manifest.cta_bindings[0]["id"], "cta_type": "signup", "unknown": "drop-me"},
            attribution_context=normalize_attribution_from_url(
                default_snapshot_payload()["public_url"] + "&email=a@example.test"
            ),
            consent_context={"mode": "after_external_consent"},
        )
        props = allowed_provider_properties(event)
        self.assertIn("smm_attribution_id", props)
        self.assertNotIn("unknown", props)
        self.assertNotIn("email", props)
        self.assertFalse(default_consent_allowed("after_external_consent"))
        self.assertTrue(default_consent_allowed("always_enabled"))
        bad = event.__class__(
            schema_version=event.schema_version,
            event_type=event.event_type,
            event_name=event.event_name,
            page_context=event.page_context,
            event_context={"cta_type": "invalid"},
            attribution_context=event.attribution_context,
            consent_context=event.consent_context,
        )
        with self.assertRaises(WebsiteInstrumentationError):
            allowed_provider_properties(bad)

    def test_api_cli_mcp_style_payloads(self) -> None:
        preview = self.service.preview_manifest(self.config["id"], default_snapshot_payload())
        self.assertEqual(preview["frontmatter"]["analytics"]["manifest_checksum"], preview["manifest"]["checksum"])
        self.assertIn(SMM_CONVERSION_EVENT, str(preview["manifest"]["expected_events"]))
        self.assertEqual(self.service.config(self.config["id"])["config"]["version"], 1)
        self.assertIn("templates", self.service.templates("generic_vanilla"))


if __name__ == "__main__":
    unittest.main()
