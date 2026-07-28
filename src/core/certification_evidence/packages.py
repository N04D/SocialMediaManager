"""Evidence package build, export, and safe import helpers."""

from __future__ import annotations

import io
import zipfile
from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Any

from .canonical import canonical_json_bytes, canonical_json_text
from .contracts import CERTIFICATION_EVIDENCE_FRAMEWORK_VERSION
from .errors import CertificationEvidenceError
from .models import (
    CertificationArtifactManifest,
    CertificationEvidencePackage,
    CertificationProvenance,
    package_with_checksum,
    stable_checksum,
    utc_now_iso,
)
from .signatures import sign_payload, unsigned_envelope

MAX_PACKAGE_BYTES = 2_000_000
MAX_ARTIFACTS = 16
MAX_COMPRESSION_RATIO = 25
ALLOWED_ARTIFACT_TYPES = {
    "canonical_report",
    "safe_testsummary",
    "safe_readinessreport",
    "safe_schema_version",
    "safe_browsermetadata",
    "safe_workermetadata",
    "safe_reconciliation",
    "safe_provider_observed",
    "safe_checksums",
}
FORBIDDEN_ARTIFACT_MARKERS = (
    "cookie",
    "Authorization",
    "BEGIN PRIVATE KEY",
    "raw_eventpayload",
    "content/",
    "drafts/",
)


def build_artifact(
    path: str, artifact_type: str, payload: Any, *, required: bool = True
) -> tuple[CertificationArtifactManifest, bytes]:
    _validate_relative_path(path)
    if artifact_type not in ALLOWED_ARTIFACT_TYPES:
        raise CertificationEvidenceError("certification.artifact_type", "Artifact type is not allowlisted.")
    data = canonical_json_bytes(payload)
    _validate_artifact_bytes(data)
    manifest = CertificationArtifactManifest(
        artifact_path=path,
        artifact_type=artifact_type,
        media_type="application/json",
        size_bytes=len(data),
        checksum_algorithm="sha256",
        checksum=stable_checksum(data.decode("utf-8")),
        required=required,
        redaction_status="redacted",
    )
    return manifest, data


def build_package(
    *,
    workspace_id: str,
    evidence_type: str,
    report: dict[str, Any],
    provenance: CertificationProvenance,
    artifacts: dict[str, tuple[str, Any]],
    signer_reference_id: str = "",
) -> tuple[CertificationEvidencePackage, dict[str, bytes]]:
    artifact_bytes: dict[str, bytes] = {}
    manifests: list[CertificationArtifactManifest] = []
    report_manifest, report_bytes = build_artifact("report.json", "canonical_report", report)
    provenance_manifest, provenance_bytes = build_artifact("provenance.json", "safe_testsummary", asdict(provenance))
    manifests.extend([report_manifest, provenance_manifest])
    artifact_bytes["report.json"] = report_bytes
    artifact_bytes["provenance.json"] = provenance_bytes
    for path, (artifact_type, payload) in sorted(artifacts.items()):
        if len(manifests) >= MAX_ARTIFACTS:
            raise CertificationEvidenceError(
                "certification.too_many_artifacts", "Evidence package has too many artifacts."
            )
        manifest, data = build_artifact(path, artifact_type, payload, required=False)
        manifests.append(manifest)
        artifact_bytes[path] = data
    payload_for_signature = {
        "evidence_type": evidence_type,
        "workspace_id": workspace_id,
        "report": report,
        "provenance": asdict(provenance),
        "artifact_manifest": [asdict(item) for item in manifests],
    }
    envelope = (
        sign_payload(payload_for_signature, signer_reference_id)
        if signer_reference_id
        else unsigned_envelope(payload_for_signature)
    )
    package = CertificationEvidencePackage(
        package_id="certpkg-" + stable_checksum(payload_for_signature)[:20],
        package_version=CERTIFICATION_EVIDENCE_FRAMEWORK_VERSION,
        evidence_type=evidence_type,
        workspace_id=workspace_id,
        source_environment=provenance.source_type,
        source_origin=provenance.repository_identity,
        generated_at=utc_now_iso(),
        report_reference="report.json",
        provenance_reference="provenance.json",
        artifact_manifest=tuple(manifests),
        signature_envelope=envelope,
        package_checksum="",
    )
    return package_with_checksum(package), artifact_bytes


def export_package(package: CertificationEvidencePackage, artifact_bytes: dict[str, bytes]) -> bytes:
    _validate_manifest(package)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", canonical_json_text(asdict(package)))
        archive.writestr("signature.json", canonical_json_text(asdict(package.signature_envelope)))
        for manifest in package.artifact_manifest:
            data = artifact_bytes.get(manifest.artifact_path)
            if data is None and manifest.required:
                raise CertificationEvidenceError("certification.missing_artifact", "Required artifact is missing.")
            if data is None:
                continue
            if stable_checksum(data.decode("utf-8")) != manifest.checksum:
                raise CertificationEvidenceError("certification.artifact_checksum", "Artifact checksum mismatch.")
            archive.writestr(manifest.artifact_path, data)
    data = buffer.getvalue()
    if len(data) > MAX_PACKAGE_BYTES:
        raise CertificationEvidenceError(
            "certification.package_too_large", "Evidence package exceeds the maximum size."
        )
    return data


def read_package_archive(data: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    if len(data) > MAX_PACKAGE_BYTES:
        raise CertificationEvidenceError(
            "certification.package_too_large", "Evidence package exceeds the maximum size."
        )
    artifacts: dict[str, bytes] = {}
    normalized: set[str] = set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARTIFACTS + 3:
            raise CertificationEvidenceError("certification.too_many_artifacts", "Evidence package has too many files.")
        for info in infos:
            path = _validate_relative_path(info.filename)
            lowered = path.lower()
            if lowered in normalized:
                raise CertificationEvidenceError("certification.duplicate_path", "Duplicate normalized artifact path.")
            normalized.add(lowered)
            if info.is_dir() or _is_link(info):
                raise CertificationEvidenceError(
                    "certification.archive_link", "Archive links and directories are not allowed."
                )
            if info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
                raise CertificationEvidenceError(
                    "certification.compression_ratio", "Archive compression ratio is unsafe."
                )
            if info.file_size > MAX_PACKAGE_BYTES:
                raise CertificationEvidenceError(
                    "certification.artifact_too_large", "Artifact exceeds the maximum size."
                )
            with archive.open(info) as handle:
                artifacts[path] = handle.read(MAX_PACKAGE_BYTES + 1)
    manifest_bytes = artifacts.get("manifest.json")
    if not manifest_bytes:
        raise CertificationEvidenceError("certification.missing_manifest", "Evidence manifest is missing.")
    manifest = __import__("json").loads(manifest_bytes.decode("utf-8"))
    return manifest, artifacts


def verify_artifact_manifest(package: CertificationEvidencePackage, artifact_bytes: dict[str, bytes]) -> None:
    _validate_manifest(package)
    for manifest in package.artifact_manifest:
        data = artifact_bytes.get(manifest.artifact_path)
        if data is None:
            if manifest.required:
                raise CertificationEvidenceError("certification.missing_artifact", "Required artifact is missing.")
            continue
        _validate_artifact_bytes(data)
        if stable_checksum(data.decode("utf-8")) != manifest.checksum:
            raise CertificationEvidenceError("certification.artifact_checksum", "Artifact checksum mismatch.")


def _validate_manifest(package: CertificationEvidencePackage) -> None:
    paths = [item.artifact_path for item in package.artifact_manifest]
    if package.report_reference not in paths or package.provenance_reference not in paths:
        raise CertificationEvidenceError(
            "certification.required_artifact", "Report and provenance artifacts are required."
        )


def _validate_artifact_bytes(data: bytes) -> None:
    text = data.decode("utf-8")
    for marker in FORBIDDEN_ARTIFACT_MARKERS:
        if marker.lower() in text.lower():
            raise CertificationEvidenceError("certification.forbidden_artifact", "Artifact contains forbidden data.")


def _validate_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if normalized.startswith("/") or ":" in normalized.split("/", maxsplit=1)[0] or ".." in pure.parts:
        raise CertificationEvidenceError("certification.traversal", "Artifact path must be relative and safe.")
    if normalized != str(pure) or not normalized or normalized == ".":
        raise CertificationEvidenceError("certification.path", "Artifact path is invalid.")
    return normalized


def _is_link(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return (mode & 0o170000) in {0o120000, 0o100000} and (mode & 0o170000) == 0o120000


__all__ = ["build_artifact", "build_package", "export_package", "read_package_archive", "verify_artifact_manifest"]
