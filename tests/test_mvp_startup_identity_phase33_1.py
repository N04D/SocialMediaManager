from __future__ import annotations

import json
import socket
import subprocess
import sys

import mvp_dashboard
from tests.phase331_support import Phase331TestCase


class MVPStartupIdentityPhase331Tests(Phase331TestCase):
    def test_build_identity_health_payload_is_safe(self) -> None:
        payload = json.loads(self.page("/health"))
        self.assertIn("commit_sha", payload)
        self.assertEqual(payload["application_version"], "phase33.1")
        self.assertEqual(payload["dashboard_contract_version"], "mvp-dashboard-dogfood-0.1")
        self.assertNotIn("content/drafts", json.dumps(payload).lower())

    def test_port_conflict_reports_active_build_hint(self) -> None:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        (self.root / "config.json").write_text('{"content_dir": "managed-content"}', encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, "dashboard.py", "--port", str(port), "--config", str(self.root / "config.json")],
                cwd=mvp_dashboard.PRODUCT_ROOT,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
        finally:
            sock.close()
        self.assertEqual(result.returncode, 2)
        self.assertIn("not available", result.stderr)
        self.assertIn("/health", result.stderr)
