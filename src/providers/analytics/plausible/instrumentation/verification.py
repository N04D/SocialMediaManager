"""Plausible browser bridge verification helpers."""


def plausible_bridge_present(html: str) -> bool:
    return "plausible-bridge.js" in html or "SMMAnalyticsBridge" in html


__all__ = ["plausible_bridge_present"]
