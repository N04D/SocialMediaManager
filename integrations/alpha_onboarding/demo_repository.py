"""Fake Markdown Website repository for deterministic demo mode."""

from __future__ import annotations

from pathlib import Path


class FakeMarkdownWebsiteRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".git").mkdir(exist_ok=True)

    def doctor(self) -> dict[str, object]:
        return {
            "repository": str(self.root.name),
            "branch": "main",
            "output_root": "site/content",
            "git_status": "clean_fixture",
            "renderer": "markdown_website_fixture",
            "public_url": "https://example.invalid/demo-alpha-article",
            "write_permissions": "PASS",
            "media_materialization": "PASS",
            "instrumentation_support": "PASS",
            "verification_support": "PASS",
            "push_policy": "commit-only",
            "test_commit_created": False,
        }
