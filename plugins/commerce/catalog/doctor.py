from __future__ import annotations


def run_doctor() -> dict[str, object]:
    return {
        "status": "ok",
        "catalog": "fixture_read_only",
        "payment_mutation": False,
        "order_creation": False,
    }
