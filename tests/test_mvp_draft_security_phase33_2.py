from __future__ import annotations

import json

import mvp_dashboard
from tests.phase332_support import Phase332TestCase


class MVPDraftSecurityPhase332Tests(Phase332TestCase):
    def test_defaults_security_and_sandbox_boundary(self) -> None:
        session_id = self.start_real_session()
        form = self.page(f"/setup/{session_id}/publication_destination")
        self.assertNotIn("smm-dogfood-001-site", form)

        with self.assertRaises(ValueError):
            mvp_dashboard._register_destination(
                mvp_dashboard.alpha_ui_service(),
                session_id,
                {
                    "display_name": "Product",
                    "managed_root": "/home/n04d",
                    "repository": "SocialMediaManager",
                    "branch": "main",
                    "public_url_template": "http://127.0.0.1:8099/articles/{slug}.md",
                },
            )

        payload = json.dumps(mvp_dashboard.build_identity())
        self.assertNotIn("secret", payload.lower())
        self.assertNotIn("production_ready=true", payload)
