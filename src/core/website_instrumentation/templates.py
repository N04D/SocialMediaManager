"""Static site instrumentation template references."""

from __future__ import annotations

from pathlib import Path

TEMPLATE_ROOT = Path("templates/website-instrumentation")


def template_payload(profile_id: str = "") -> dict:
    templates = []
    for path in sorted(TEMPLATE_ROOT.glob("*/README.md")):
        current = path.parent.name
        if profile_id and current != profile_id:
            continue
        templates.append(
            {
                "profile_id": current,
                "path": str(path),
                "content": path.read_text(encoding="utf-8"),
                "contains_credentials": False,
                "auto_install": False,
            }
        )
    return {"templates": templates, "managed_export_only": True}


__all__ = ["template_payload"]
