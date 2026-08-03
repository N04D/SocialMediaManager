#!/usr/bin/env python3
"""Read-only WooCommerce order/outcome smoke; never prints order payloads or PII."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugins.commerce.woocommerce import WooCommerceCatalogPlugin, WooCommerceConfig  # noqa: E402
from plugins.commerce.woocommerce.plugin import StaticSecretReader  # noqa: E402


def main() -> int:
    store_url = os.environ.get("WOOCOMMERCE_STORE_URL", "")
    consumer_key = os.environ.get("WOOCOMMERCE_CONSUMER_KEY", "")
    consumer_secret = os.environ.get("WOOCOMMERCE_CONSUMER_SECRET", "")
    if not store_url or not consumer_key or not consumer_secret:
        print("REAL WOOCOMMERCE OUTCOMES SMOKE: NOT CONFIGURED")
        print("Reason: WOOCOMMERCE_STORE_URL, WOOCOMMERCE_CONSUMER_KEY, and WOOCOMMERCE_CONSUMER_SECRET are required.")
        return 0
    config = WooCommerceConfig.from_dict(
        {
            "store_url": store_url,
            "consumer_key_secret_ref": "secretref:runtime/woocommerce-key",
            "consumer_secret_secret_ref": "secretref:runtime/woocommerce-secret",
            "page_size": int(os.environ.get("WOOCOMMERCE_PAGE_SIZE", "25")),
            "max_pages": int(os.environ.get("WOOCOMMERCE_MAX_PAGES", "2")),
            "attribution_id_meta_keys": tuple(
                filter(None, os.environ.get("WOOCOMMERCE_ATTRIBUTION_KEYS", "").split(","))
            ),
            "campaign_meta_keys": tuple(filter(None, os.environ.get("WOOCOMMERCE_CAMPAIGN_KEYS", "").split(","))),
            "content_meta_keys": tuple(filter(None, os.environ.get("WOOCOMMERCE_CONTENT_KEYS", "").split(","))),
        }
    )
    plugin = WooCommerceCatalogPlugin(
        config=config,
        secret_reader=StaticSecretReader(
            {
                "secretref:runtime/woocommerce-key": consumer_key,
                "secretref:runtime/woocommerce-secret": consumer_secret,
            }
        ),
    )
    health = plugin.test_connection()
    if health.get("status") != "ready":
        print(f"REAL WOOCOMMERCE OUTCOMES SMOKE: BLOCKED\nReason: {health.get('message', health.get('status'))}")
        return 1
    sync = plugin.sync_orders()
    if sync.get("status") != "succeeded":
        print(f"REAL WOOCOMMERCE OUTCOMES SMOKE: BLOCKED\nReason: {sync.get('message', sync.get('status'))}")
        return 1
    outcomes = [
        outcome for order in plugin.list_orders() for outcome in plugin.order_outcomes(order, workspace_id="smoke")
    ]
    currencies = sorted({outcome.currency for outcome in outcomes if outcome.currency})
    attributed = sum(
        float(outcome.value or 0)
        for outcome in outcomes
        if outcome.outcome_type == "revenue" and outcome.metadata.get("attribution_confidence") in {"direct", "strong"}
    )
    unknown = sum(
        1
        for outcome in outcomes
        if outcome.outcome_type == "revenue" and outcome.metadata.get("attribution_confidence") == "unknown"
    )
    print("REAL WOOCOMMERCE OUTCOMES SMOKE: PASS")
    print(
        f"orders_observed={sync['orders_observed']} outcomes_mapped={len(outcomes)} attributed_line_revenue={attributed}"
    )
    print(f"unknown_line_items={unknown} currencies={','.join(currencies) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
