"""Corruption fixtures for package import tests."""

from __future__ import annotations

import io
import zipfile


def tamper_first_report_byte(package_data: bytes) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(package_data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "report.json":
                data = data.replace(b"{", b"[", 1)
            target.writestr(info.filename, data)
    return buffer.getvalue()


def traversal_archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("../report.json", b"{}")
        archive.writestr("manifest.json", b"{}")
    return buffer.getvalue()


def forbidden_artifact_archive(package_data: bytes) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(package_data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            target.writestr(info.filename, source.read(info.filename))
        target.writestr("artifacts/forbidden.json", b'{"value":"BEGIN PRIVATE KEY"}')
    return buffer.getvalue()
