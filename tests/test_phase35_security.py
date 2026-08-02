from __future__ import annotations

import unittest
from pathlib import Path

from plugins.commerce.catalog import CommerceCatalogPlugin
from plugins.sources.youtube import YouTubeSourcePlugin
from plugins.transformations.video_repurpose import VideoRepurposePlugin
from tests.phase35_support import Phase35TestMixin

ROOT = Path(__file__).resolve().parents[1]


class Phase35SecurityTests(Phase35TestMixin, unittest.TestCase):
    def test_no_external_publish_payment_fake_retrieval_or_blind_retry(self) -> None:
        source_health = YouTubeSourcePlugin().health_check()
        transform_health = VideoRepurposePlugin().health_check()
        commerce_health = CommerceCatalogPlugin().health_check()
        self.assertEqual(source_health["transcript_retrieval"], "not_configured")
        self.assertFalse(source_health["network_required"])
        self.assertEqual(transform_health["shell"], "not_used")
        self.assertFalse(commerce_health["payment_mutation"])
        self.assertFalse(commerce_health["order_creation"])
        result = self.harness.run_sabr()
        cta_relationships = [
            rel for rel in result["agent_context"]["relationships"] if rel["relationship_type"] == "promotes"
        ]
        self.assertTrue(cta_relationships[0]["metadata"]["requires_confirmation"])

    def test_plugin_sources_do_not_use_arbitrary_shell_or_network_clients(self) -> None:
        phase35_files = [
            ROOT / "plugins/sources/youtube/plugin.py",
            ROOT / "plugins/transformations/video_repurpose/plugin.py",
            ROOT / "plugins/commerce/catalog/plugin.py",
            ROOT / "plugins/playbooks/creator_commerce/playbook.py",
        ]
        joined = "\n".join(path.read_text(encoding="utf-8") for path in phase35_files)
        for needle in ["shell=True", "os.system", "subprocess", "requests.", "httpx.", "socket.socket"]:
            self.assertNotIn(needle, joined)
        for needle in [
            "Authorization",
            "token",
            "secret",
            "password",
            'payment_mutation": true',
            "order_creation = True",
        ]:
            self.assertNotIn(needle, joined)

    def test_phase20_2_remains_blocked_and_no_user_owned_paths_are_used(self) -> None:
        operations = __import__("dashboard").plugin_sandbox_health_payload()["health"]
        self.assertNotEqual(operations.get("external_plugin_sandbox_ready"), True)
        self.assertFalse(
            (self.harness.root / "content").samefile(ROOT / "content") if (ROOT / "content").exists() else False
        )
        self.assertFalse(
            (self.harness.root / "content").samefile(ROOT / "drafts") if (ROOT / "drafts").exists() else False
        )
