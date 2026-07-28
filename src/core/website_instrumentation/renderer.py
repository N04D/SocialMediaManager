"""Reference template and marker rendering."""

from __future__ import annotations

import html
import json
from dataclasses import asdict

from .contracts import WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION
from .events import property_schema_payload
from .manifests import manifest_payload
from .models import WebsiteInstrumentationManifest


def render_public_markers(manifest: WebsiteInstrumentationManifest) -> str:
    return "\n".join(
        [
            f'<meta name="smm-instrumentation-version" content="{WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION}">',
            f'<meta name="smm-instrumentation-manifest" content="{html.escape(manifest.checksum)}">',
            f'<meta name="smm-publication-id" content="{html.escape(manifest.page_context.publication_id)}">',
            f'<meta name="smm-revision-id" content="{html.escape(manifest.page_context.revision_id)}">',
        ]
    )


def render_page_context_script(manifest: WebsiteInstrumentationManifest) -> str:
    config = {
        "version": WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION,
        "consentMode": manifest.consent_mode,
        "pageContext": asdict(manifest.page_context),
        "events": list(manifest.expected_events),
        "propertySchema": property_schema_payload(),
        "provider": "plausible" if manifest.profile_id == "plausible_generic" else "generic",
    }
    payload = json.dumps(config, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
    return '<script type="application/json" id="smm-analytics-config">' + payload + "</script>"


def render_frontmatter_binding(manifest: WebsiteInstrumentationManifest) -> dict:
    return {
        "analytics": {
            "instrumentation_version": WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION,
            "manifest_checksum": manifest.checksum,
            "page_id": manifest.page_context.page_id,
            "content_id": manifest.page_context.content_id,
            "revision_id": manifest.page_context.revision_id,
            "publication_id": manifest.page_context.publication_id,
            "campaign_id": manifest.page_context.campaign_id,
            "ctas": list(manifest.cta_bindings),
        }
    }


def render_sidecar_bytes(manifest: WebsiteInstrumentationManifest) -> bytes:
    return (json.dumps(manifest_payload(manifest), sort_keys=True, indent=2) + "\n").encode("utf-8")


def render_static_page(manifest: WebsiteInstrumentationManifest, *, duplicate_runtime: bool = False) -> str:
    duplicate = (
        '<script src="/instrumentation/smm-analytics.js" data-smm-runtime></script>' if duplicate_runtime else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
{render_public_markers(manifest)}
{render_page_context_script(manifest)}
<script src="/instrumentation/smm-analytics.js" data-smm-runtime></script>
<script src="/instrumentation/plausible-bridge.js" data-smm-plausible-bridge></script>
{duplicate}
</head>
<body>
<main>
<h1>Fixture article</h1>
<a href="/signup?{html.escape("smm_attribution_id=ignored")}" data-smm-track="cta" data-smm-cta-id="{html.escape(manifest.cta_bindings[0]["id"])}" data-smm-cta-type="signup" data-smm-placement="article-footer">Start</a>
<button data-smm-track="conversion" data-smm-conversion-id="{html.escape(manifest.conversion_bindings[0]["id"])}" data-smm-conversion-type="signup" data-smm-cta-id="{html.escape(manifest.cta_bindings[0]["id"])}">Complete</button>
</main>
</body>
</html>
"""


__all__ = [
    "render_frontmatter_binding",
    "render_page_context_script",
    "render_public_markers",
    "render_sidecar_bytes",
    "render_static_page",
]
