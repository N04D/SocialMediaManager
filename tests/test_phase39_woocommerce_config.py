from __future__ import annotations

import json
import unittest

from plugins.commerce.woocommerce.plugin import WooCommerceConfig, WooCommerceError
from tests.phase39_support import KEY_REF, SECRET_REF, WooFixtureServer, woo_config


class Phase39WooCommerceConfigTests(unittest.TestCase):
    def test_config_requires_secret_refs_and_redacts_them(self) -> None:
        with WooFixtureServer() as server:
            config = woo_config(server.url)
        redacted = json.dumps(config.redacted())
        self.assertIn("secretref:***", redacted)
        self.assertNotIn(KEY_REF, redacted)
        self.assertNotIn(SECRET_REF, redacted)
        self.assertEqual(config.store_id, "fixture-store")

    def test_url_validation_rejects_credentials_and_nonlocal_http(self) -> None:
        with self.assertRaises(WooCommerceError):
            WooCommerceConfig.from_dict(
                {
                    "store_url": "https://user:pass@example.test",
                    "consumer_key_secret_ref": KEY_REF,
                    "consumer_secret_secret_ref": SECRET_REF,
                }
            )
        with self.assertRaises(WooCommerceError):
            WooCommerceConfig.from_dict(
                {
                    "store_url": "http://example.test",
                    "consumer_key_secret_ref": KEY_REF,
                    "consumer_secret_secret_ref": SECRET_REF,
                }
            )
