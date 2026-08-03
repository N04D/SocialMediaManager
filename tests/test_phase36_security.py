from __future__ import annotations

import unittest
from pathlib import Path

from dashboard import plugin_sandbox_health_payload
from plugins.commerce.catalog import CommerceCatalogPlugin
from tests.phase36_support import Phase36Harness

ROOT = Path(__file__).resolve().parents[1]


class Phase36SecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Phase36Harness()
        self.addCleanup(self.harness.close)

    def test_no_external_publication_no_commerce_mutation_no_blind_retry(self) -> None:
        result = self.harness.render_candidate()["result"]
        self.assertEqual(result.status, "succeeded")
        commerce_health = CommerceCatalogPlugin().health_check()
        self.assertFalse(commerce_health["payment_mutation"])
        self.assertFalse(commerce_health["order_creation"])
        sandbox = plugin_sandbox_health_payload()["health"]
        self.assertFalse(bool(sandbox.get("production_ready")))
        self.assertEqual(sandbox.get("controller_status"), "sandbox_incomplete")

    def test_new_code_uses_only_ffmpeg_boundary_for_process_execution(self) -> None:
        plugin_text = (ROOT / "plugins/transformations/video_repurpose/plugin.py").read_text(encoding="utf-8")
        self.assertNotIn("subprocess", plugin_text)
        self.assertNotIn("shell=True", plugin_text)
        boundary = (ROOT / "plugins/transformations/video_repurpose/ffmpeg_boundary.py").read_text(encoding="utf-8")
        self.assertIn("subprocess.run", boundary)
        self.assertIn("check=False", boundary)
        self.assertNotIn("shell=True", boundary)

    def test_user_owned_content_paths_are_not_used(self) -> None:
        self.assertNotEqual(self.harness.config.content_dir.resolve(), (ROOT / "content").resolve())
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                ROOT / "plugins/transformations/video_repurpose/plugin.py",
                ROOT / "plugins/transformations/video_repurpose/ffmpeg_boundary.py",
            ]
        )
        self.assertNotIn("content/", text)
        self.assertNotIn("drafts/", text)
