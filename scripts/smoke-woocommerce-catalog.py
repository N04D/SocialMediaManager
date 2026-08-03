#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.commerce.woocommerce import WooCommerceCatalogPlugin, WooCommerceConfig  # noqa: E402
from plugins.commerce.woocommerce.plugin import StaticSecretReader  # noqa: E402


def main() -> int:
    store_url = os.environ.get("WOOCOMMERCE_STORE_URL", "").strip()
    consumer_key = os.environ.get("WOOCOMMERCE_CONSUMER_KEY", "")
    consumer_secret = os.environ.get("WOOCOMMERCE_CONSUMER_SECRET", "")
    if not store_url or not consumer_key or not consumer_secret:
        print("REAL WOOCOMMERCE CATALOG SMOKE: NOT CONFIGURED")
        print("Reason: WOOCOMMERCE_STORE_URL, WOOCOMMERCE_CONSUMER_KEY, and WOOCOMMERCE_CONSUMER_SECRET are required.")
        return 0
    key_ref = "secretref:woocommerce/smoke-consumer-key"
    secret_ref = "secretref:woocommerce/smoke-consumer-secret"
    config = WooCommerceConfig.from_dict(
        {
            "store_url": store_url,
            "consumer_key_secret_ref": key_ref,
            "consumer_secret_secret_ref": secret_ref,
            "timeout": float(os.environ.get("WOOCOMMERCE_TIMEOUT", "10")),
            "page_size": int(os.environ.get("WOOCOMMERCE_PAGE_SIZE", "10")),
            "verify_tls": os.environ.get("WOOCOMMERCE_VERIFY_TLS", "true").lower() != "false",
            "currency": os.environ.get("WOOCOMMERCE_CURRENCY", "EUR"),
            "store_id": os.environ.get("WOOCOMMERCE_STORE_ID", ""),
            "max_pages": int(os.environ.get("WOOCOMMERCE_MAX_PAGES", "1")),
        }
    )
    plugin = WooCommerceCatalogPlugin(
        config=config,
        secret_reader=StaticSecretReader({key_ref: consumer_key, secret_ref: consumer_secret}),
    )
    start = time.monotonic()
    connection = plugin.test_connection()
    if connection["status"] != "ready":
        print("REAL WOOCOMMERCE CATALOG SMOKE: BLOCKED")
        print(f"Reason: {connection['status']}")
        return 2
    sync = plugin.sync_products()
    elapsed = time.monotonic() - start
    if sync["status"] != "succeeded" or not plugin.list_products():
        print("REAL WOOCOMMERCE CATALOG SMOKE: BLOCKED")
        print(f"Reason: sync {sync.get('status')} {sync.get('error_code', '')}".strip())
        return 2
    first = plugin.list_products()[0]
    if not first.product_id or not first.metadata.get("woocommerce", {}).get("external_ref"):
        print("REAL WOOCOMMERCE CATALOG SMOKE: BLOCKED")
        print("Reason: product identity/provenance missing")
        return 2
    print("REAL WOOCOMMERCE CATALOG SMOKE: PASS")
    print(f"Store: {config.store_url}")
    print(f"Products: {sync['product_count']} · Pages: {sync['pages_fetched']} · Duration: {elapsed:.2f}s")
    print(f"First product: {first.title} · Availability: {first.availability}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
