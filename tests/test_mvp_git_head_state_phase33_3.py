from __future__ import annotations

import subprocess

from channels.markdown_website.git_publisher import GitPublisher
from tests.phase333_support import Phase333TestCase


class MVPGitHeadStatePhase333Tests(Phase333TestCase):
    def test_unborn_existing_and_invalid_head_states(self) -> None:
        publisher = GitPublisher()
        empty = self.init_empty_site_repo()
        self.assertEqual(publisher.head_state(empty).state, "unborn")

        (empty / "README.md").write_text("baseline\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=empty, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "-c", "user.name=Dogfood", "-c", "user.email=dogfood@example.invalid", "commit", "-m", "init"],
            cwd=empty,
            check=True,
            capture_output=True,
            text=True,
        )
        existing = publisher.head_state(empty)
        self.assertEqual(existing.state, "existing")
        self.assertTrue(existing.commit_sha)

        invalid = self.root / "not-a-repo"
        invalid.mkdir()
        self.assertEqual(publisher.head_state(invalid).state, "invalid")
