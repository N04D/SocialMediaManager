from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from src.core.browser import BrowserInteractionError

ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_UPLOAD_BYTES = 25_000_000


@dataclass(frozen=True)
class SharedUploadReference:
    host_path: Path
    controller_path: str


@dataclass(frozen=True)
class SharedVolumeUploadTransfer:
    host_dir: Path
    controller_dir: str

    def prepare(self, source: Path, *, session_id: str) -> SharedUploadReference:
        resolved = source.resolve()
        if not resolved.is_file():
            raise BrowserInteractionError(
                "browser_interaction.upload_missing_file",
                "Upload file is not available.",
                {"path": str(source)},
            )
        if resolved.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
            raise BrowserInteractionError(
                "browser_interaction.upload_type_blocked",
                "Upload file type is not supported.",
            )
        if resolved.stat().st_size > MAX_UPLOAD_BYTES:
            raise BrowserInteractionError("browser_interaction.upload_too_large", "Upload file is too large.")
        safe_session = "".join(ch for ch in session_id if ch.isalnum() or ch in {"-", "_"})[:80] or "session"
        destination_dir = self.host_dir / safe_session
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{uuid4().hex}{resolved.suffix.lower()}"
        shutil.copyfile(resolved, destination)
        return SharedUploadReference(
            host_path=destination,
            controller_path=f"{self.controller_dir.rstrip('/')}/{safe_session}/{destination.name}",
        )

    def cleanup(self, reference: SharedUploadReference) -> None:
        try:
            reference.host_path.unlink(missing_ok=True)
        except OSError:
            return
        try:
            reference.host_path.parent.rmdir()
        except OSError:
            return
