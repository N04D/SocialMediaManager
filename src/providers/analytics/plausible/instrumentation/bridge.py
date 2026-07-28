"""Plausible browser bridge renderer.

The backend returns JavaScript/template references only. It does not call
Plausible's Events API.
"""

from __future__ import annotations

from pathlib import Path

from .manifest import PLAUSIBLE_BROWSER_INSTRUMENTATION_MANIFEST


class PlausibleBrowserInstrumentationBridge:
    provider_id = "analytics.plausible"
    bridge_version = "0.1.0"

    def script(self) -> str:
        return Path("web/instrumentation/plausible-bridge.js").read_text(encoding="utf-8")

    def manifest(self) -> dict:
        return dict(PLAUSIBLE_BROWSER_INSTRUMENTATION_MANIFEST)


__all__ = ["PlausibleBrowserInstrumentationBridge"]
