from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from plugin_runtime import bootstrap_plugins
from plugins.playbooks.creator_commerce import CreatorCommerceRepurposePlaybook
from tests.test_media_library_phase11 import Phase11Config
from tests.test_support import isolated_channel_store


class Phase35Harness:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = isolated_channel_store(self.root)
        self.store.__enter__()
        self.config = Phase11Config()
        self.config.media_dir = self.root / "tmp_media"
        self.config.content_dir = self.root / "content"
        self.config.media_storage_root = self.root / "media-root"
        self.config.linkedin_user_data_dir = self.root / "profile"
        self.config.linkedin_remote_debugging_url = ""
        self.config.browser_provider_default_id = "provider.browser.legacy"
        self.config.headless = True
        for path in [
            self.config.media_dir,
            self.config.content_dir,
            self.config.media_storage_root,
            self.config.linkedin_user_data_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)
        self.runtime = bootstrap_plugins(self.config, strict=False)
        self.content = self.runtime.content_service(self.config)

    def close(self) -> None:
        self.store.__exit__(None, None, None)
        self.tmp.cleanup()

    def playbook(self) -> CreatorCommerceRepurposePlaybook:
        return CreatorCommerceRepurposePlaybook(runtime=self.runtime, content_service=self.content)

    def run_sabr(self) -> dict[str, Any]:
        return self.playbook().run_sabr_scenario()


class Phase35TestMixin:
    harness: Phase35Harness

    def setUp(self) -> None:
        self.harness = Phase35Harness()
        self.addCleanup(self.harness.close)
