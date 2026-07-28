"""Synthetic staging site HTML."""

from __future__ import annotations

import html
import json

from src.core.website_instrumentation.contracts import WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION


def synthetic_staging_page(config: dict, *, missing_marker: bool = False, missing_noindex: bool = False) -> str:
    marker = "" if missing_marker else '<meta name="smm-synthetic-analytics-page" content="true">'
    noindex = "" if missing_noindex else '<meta name="robots" content="noindex,nofollow">'
    payload = json.dumps(config, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
    cta_id = html.escape(config["synthetic"]["cta_id"])
    conversion_id = html.escape(config["synthetic"]["conversion_id"])
    return f"""<!doctype html>
<html lang="en">
<head>
{noindex}
{marker}
<meta name="smm-synthetic-profile" content="synthetic-page-plausible-smoke">
<meta name="smm-instrumentation-version" content="{WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION}">
<script type="application/json" id="smm-analytics-config">{payload}</script>
</head>
<body>
<main>
<h1>Synthetic analytics certification page</h1>
<a href="/synthetic/next" data-smm-track="cta" data-smm-cta-id="{cta_id}" data-smm-cta-type="signup" data-smm-placement="synthetic-fixture">Synthetic CTA</a>
<button data-smm-track="conversion" data-smm-conversion-id="{conversion_id}" data-smm-conversion-type="signup" data-smm-cta-id="{cta_id}">Synthetic conversion</button>
</main>
</body>
</html>
"""


__all__ = ["synthetic_staging_page"]
