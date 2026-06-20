from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys
from types import ModuleType

from studio_models import ContentItem
from tests.test_support import install_pipeline_stub

install_pipeline_stub()
bs4_stub = ModuleType("bs4")
bs4_stub.BeautifulSoup = object
sys.modules["bs4"] = bs4_stub
markdown_stub = ModuleType("markdown")
markdown_stub.markdown = lambda value, *args, **kwargs: value
sys.modules["markdown"] = markdown_stub
pipeline_stub = sys.modules["pipeline"]
pipeline_stub.CONFIG_PATH = Path("config.json")
pipeline_stub.Article = object
pipeline_stub.build_prompt = lambda *args, **kwargs: ""
pipeline_stub.ensure_runtime_dirs = lambda *args, **kwargs: None
pipeline_stub.fetch_article = lambda *args, **kwargs: None
pipeline_stub.load_config = lambda *args, **kwargs: pipeline_stub.AppConfig()

from dashboard import ROUTE_DRAFTS, ROUTE_EDITOR, select_content_item_for_route


class DashboardContentSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.content_dir = Path(self._tmp.name) / "content"

    def test_editor_without_content_starts_new_item(self) -> None:
        latest = ContentItem(
            id="latest",
            title="Latest draft",
            subtitle="",
            slug="latest-draft",
            status="draft",
            updated_at="2026-06-20T12:00:00+02:00",
        )
        older = ContentItem(
            id="older",
            title="Older draft",
            subtitle="",
            slug="older-draft",
            status="draft",
            updated_at="2026-06-19T12:00:00+02:00",
        )

        selected = select_content_item_for_route(self.content_dir, [latest, older], None, ROUTE_EDITOR)

        self.assertEqual(selected.id, "")

    def test_non_editor_without_content_still_uses_empty_item(self) -> None:
        latest = ContentItem(
            id="latest",
            title="Latest draft",
            subtitle="",
            slug="latest-draft",
            status="draft",
        )

        selected = select_content_item_for_route(self.content_dir, [latest], None, ROUTE_DRAFTS)

        self.assertEqual(selected.id, "")


if __name__ == "__main__":
    unittest.main()
