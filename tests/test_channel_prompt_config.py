import unittest
import tempfile
from pathlib import Path

from channels.linkedin.server.actions import load_prompt_template, save_prompt_template, PROMPT_PATH
from channel_dashboard import _render_prompt_editor
from channel_registry import ChannelRegistryEntry


class TestChannelPromptConfig(unittest.TestCase):
    def test_load_and_save_prompt_template(self) -> None:
        original = load_prompt_template()
        try:
            test_prompt = "Test prompt template for LinkedIn {title}"
            save_prompt_template(test_prompt)
            self.assertEqual(load_prompt_template(), test_prompt)
        finally:
            save_prompt_template(original)

    def test_render_prompt_editor_ui(self) -> None:
        entry = ChannelRegistryEntry(
            id="linkedin",
            plugin_dir=Path("/tmp"),
            health="ok",
            connection_status="connected",
            mode="playwright_local",
            manifest={"name": "LinkedIn", "capabilities": {"canGenerate": True}},
        )
        html_output = _render_prompt_editor(entry, return_to="/channels")
        self.assertIn("AI Prompt Configuration", html_output)
        self.assertIn("/channels/prompt/save", html_output)
        self.assertIn("name=\"prompt_template\"", html_output)


if __name__ == "__main__":
    unittest.main()
