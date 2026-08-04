import os
import subprocess
import sys
import unittest


class Phase401SmokeContractTests(unittest.TestCase):
    def test_smoke_without_operator_config_is_not_configured(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith("YOUTUBE_")}
        result = subprocess.run(
            [
                sys.executable,
                "scripts/smoke-youtube-short-upload.py",
                "--privacy",
                "private",
                "--notify-subscribers",
                "false",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("REAL YOUTUBE SHORT UPLOAD SMOKE: NOT CONFIGURED", result.stdout)
