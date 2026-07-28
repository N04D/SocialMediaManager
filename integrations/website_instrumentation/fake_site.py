"""Fake static site output for browser instrumentation tests."""

from src.core.website_instrumentation.renderer import render_static_page


def fake_site_html(manifest, *, duplicate_runtime: bool = False) -> str:
    return render_static_page(manifest, duplicate_runtime=duplicate_runtime)


__all__ = ["fake_site_html"]
