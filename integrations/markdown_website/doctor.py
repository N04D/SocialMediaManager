"""Read-only doctor for Markdown Website fixtures."""

from integrations.markdown_website.fixtures import SCENARIOS


def run() -> dict[str, object]:
    return {"status": "pass", "scenarios": list(SCENARIOS), "uses_project_content_or_drafts": False}
