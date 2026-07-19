from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.core.browser import BrowserArtifact


def artifact_from_remote(
    payload: dict[str, Any], *, provider_id: str, session_id: str, job_id: str = ""
) -> BrowserArtifact:
    remote_id = str(payload.get("artifact_id") or payload.get("id") or payload.get("screenshot_id") or uuid4().hex)
    kind = str(payload.get("kind") or payload.get("type") or "screenshot")
    metadata = {
        "provider_id": provider_id,
        "remote_artifact_id": remote_id,
        "remote_reference": str(payload.get("url") or payload.get("path") or ""),
        "session_id": session_id,
        "job_id": job_id,
    }
    return BrowserArtifact(
        id=f"autobrowser_{remote_id}",
        kind=kind,
        content_type=str(payload.get("content_type") or "image/png"),
        metadata={key: value for key, value in metadata.items() if value},
    )
