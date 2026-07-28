"""Managed import/export service helpers."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import CertificationEvidencePackage
from .packages import export_package, read_package_archive


def managed_output_reference(package_id: str) -> str:
    return f"managed-certification-output:{package_id}"


def export_to_managed_bytes(package: CertificationEvidencePackage, artifacts: dict[str, bytes]) -> dict[str, Any]:
    data = export_package(package, artifacts)
    return {
        "output_reference": managed_output_reference(package.package_id),
        "file_name": f"{package.package_id}.zip",
        "media_type": "application/zip",
        "size_bytes": len(data),
        "package": asdict(package),
        "data": data,
    }


def import_from_managed_bytes(data: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    return read_package_archive(data)


def reject_arbitrary_path(path: str | Path) -> None:
    raise ValueError("Certification import/export uses managed references, not arbitrary paths.")


__all__ = ["export_to_managed_bytes", "import_from_managed_bytes", "managed_output_reference", "reject_arbitrary_path"]
