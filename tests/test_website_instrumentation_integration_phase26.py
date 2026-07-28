from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from channels.markdown_website.instrumentation import (
    instrumentation_frontmatter,
    instrumentation_sidecar_bytes,
    instrumentation_sidecar_path,
)
from integrations.website_analytics.scenarios import plausible_account_payload
from integrations.website_instrumentation.scenarios import default_snapshot_payload, instrumentation_config_payload
from src.core.website_analytics.service import WebsiteAnalyticsService
from src.core.website_instrumentation.mcp import WebsiteInstrumentationMCP
from src.core.website_instrumentation.service import WebsiteInstrumentationService
from src.core.website_instrumentation.worker import WebsiteInstrumentationVerificationWorker


class WebsiteInstrumentationIntegrationPhase26Tests(unittest.TestCase):
    def test_markdown_website_sidecar_worker_mcp_and_phase25_funnel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "owned.sqlite3"
            analytics = WebsiteAnalyticsService(database_path=database)
            analytics.create_account(plausible_account_payload())
            analytics.put_mappings(
                "analytics-account-plausible",
                [
                    {"provider_event_name": "SMM CTA Click", "internal_event_type": "cta_click"},
                    {"provider_event_name": "SMM Outbound Click", "internal_event_type": "outbound_click"},
                    {"provider_event_name": "SMM Conversion", "internal_event_type": "conversion"},
                ],
            )
            service = WebsiteInstrumentationService(database_path=database)
            config = service.create_config(instrumentation_config_payload())["config"]
            preview = service.preview_manifest(config["id"], default_snapshot_payload())
            manifest = service.repository.get_manifest(preview["manifest"]["id"])
            typed_manifest = __import__(
                "src.core.website_instrumentation.manifests", fromlist=["build_manifest"]
            ).build_manifest(service.repository.get_config(config["id"]), default_snapshot_payload())
            self.assertIn("analytics", instrumentation_frontmatter(typed_manifest))
            self.assertEqual(instrumentation_sidecar_path("articles/demo.md"), "articles/demo.md.analytics.json")
            self.assertIn(b'"checksum"', instrumentation_sidecar_bytes(typed_manifest))
            worker_result = WebsiteInstrumentationVerificationWorker(service).run_once()
            self.assertEqual(worker_result["backend_provider_writes"], 0)
            self.assertGreaterEqual(worker_result["processed"], 1)
            mcp = WebsiteInstrumentationMCP(service)
            self.assertEqual(mcp.get_website_instrumentation_config(config["id"])["config"]["id"], config["id"])
            self.assertEqual(
                mcp.get_publication_instrumentation_manifest(config["id"])["manifest"]["content_revision_id"],
                manifest["content_revision_id"],
            )
            sync = analytics.sync("analytics-account-plausible")
            self.assertEqual(sync["provider_writes"], 0)
            self.assertTrue(sync["observations"][0]["id"].startswith("web-obs-"))


if __name__ == "__main__":
    unittest.main()
