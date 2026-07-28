"""Additive instrumentation bindings for Markdown Website publications."""

from __future__ import annotations

from pathlib import PurePosixPath

from src.core.website_instrumentation.models import WebsiteInstrumentationManifest
from src.core.website_instrumentation.renderer import render_frontmatter_binding, render_sidecar_bytes


def instrumentation_frontmatter(manifest: WebsiteInstrumentationManifest) -> dict:
    return render_frontmatter_binding(manifest)


def instrumentation_sidecar_path(markdown_relative_path: str) -> str:
    path = PurePosixPath(markdown_relative_path)
    if path.is_absolute() or ".." in path.parts or path.name == "":
        raise ValueError("instrumentation sidecar path must be publication-relative")
    return str(path.with_suffix(path.suffix + ".analytics.json"))


def instrumentation_sidecar_bytes(manifest: WebsiteInstrumentationManifest) -> bytes:
    return render_sidecar_bytes(manifest)


__all__ = ["instrumentation_frontmatter", "instrumentation_sidecar_bytes", "instrumentation_sidecar_path"]
