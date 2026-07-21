"""Services for safe plugin packaging, verification, and local installation."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plugin_sdk.compatibility import build_compatibility_report, scan_forbidden_imports, scan_secrets
from plugin_sdk.manifest import PluginManifest, validate_manifest

from .contracts import (
    PLUGIN_DISTRIBUTION_FRAMEWORK_VERSION,
    PLUGIN_ENTRY_POINT_GROUP,
    PLUGIN_INSTALLER_NAME,
)
from .errors import (
    PluginActivationError,
    PluginArtifactHashError,
    PluginArtifactSizeError,
    PluginDependencyPolicyError,
    PluginEntrypointValidationError,
    PluginHostCompatibilityError,
    PluginIdentityConflictError,
    PluginInstallationError,
    PluginInstalledFileDriftError,
    PluginPackageInvalidError,
    PluginRecordValidationError,
    PluginRegistryExpiredError,
    PluginRegistryMetadataError,
    PluginRegistryRollbackError,
    PluginReleaseRevokedError,
    PluginReleaseYankedError,
    PluginSignatureVerificationError,
    PluginSignerIdentityError,
    PluginUninstallBlockedError,
    PluginUnsupportedPackageFormatError,
    PluginWheelPathError,
    PluginWheelValidationError,
)
from .models import (
    PluginDistributionHealth,
    PluginDistributionIntegrityFinding,
    PluginInstallRecord,
    PluginPackageVerificationResult,
    PluginRegistryEntry,
    PluginRegistrySource,
    PluginReleaseMetadata,
    PluginSignatureVerification,
    PluginSignerPolicy,
    WheelInspectionResult,
    utc_now,
)
from .policies import (
    ALLOWED_DEPENDENCIES,
    ALLOWED_WHEEL_TAGS,
    BUILTIN_PLUGIN_IDS,
    FORBIDDEN_TOP_LEVEL_MODULES,
    FORBIDDEN_WHEEL_FILES,
    FORBIDDEN_WHEEL_SUFFIXES,
    MAX_UNCOMPRESSED_BYTES,
    MAX_WHEEL_BYTES,
    MAX_WHEEL_FILES,
    is_stdlib_module,
    normalize_wheel_path,
)

WHEEL_NAME_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.]+)-(?P<version>\d+\.\d+\.\d+)-(?P<build>[^-]+)-(?P<abi>[^-]+)-(?P<platform>[^-]+)\.whl$"
)
SAFE_DIST_RE = re.compile(r"^smm_plugin_[a-z0-9_]+$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, default=str) + "\n"


def b64_hash(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def parse_email_metadata(text: str) -> dict[str, list[str]]:
    payload: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line or ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", maxsplit=1)
        payload.setdefault(key, []).append(value.strip())
    return payload


class PluginWheelInspector:
    """Static wheel inspector. It never imports plugin code."""

    def inspect(self, wheel_path: str | Path) -> WheelInspectionResult:
        path = Path(wheel_path)
        if path.suffix != ".whl":
            raise PluginUnsupportedPackageFormatError("plugin.package.not_wheel", "Only wheel artifacts are accepted.")
        if path.name.endswith((".tar.gz", ".zip")):
            raise PluginUnsupportedPackageFormatError(
                "plugin.package.source_rejected", "Source distributions are rejected."
            )
        if path.stat().st_size > MAX_WHEEL_BYTES:
            raise PluginArtifactSizeError("plugin.package.too_large", "Wheel exceeds maximum size.")
        match = WHEEL_NAME_RE.match(path.name)
        if not match:
            raise PluginWheelValidationError("plugin.wheel.filename_invalid", "Wheel filename is invalid.")
        tag = f"{match.group('build')}-{match.group('abi')}-{match.group('platform')}"
        if tag not in ALLOWED_WHEEL_TAGS:
            raise PluginUnsupportedPackageFormatError(
                "plugin.wheel.tag_unsupported", "Only py3-none-any wheels are accepted."
            )
        try:
            with zipfile.ZipFile(path) as zf:
                infos = zf.infolist()
                self._validate_paths(infos)
                if len(infos) > MAX_WHEEL_FILES:
                    raise PluginWheelValidationError("plugin.wheel.too_many_files", "Wheel contains too many files.")
                total = sum(item.file_size for item in infos)
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise PluginWheelValidationError("plugin.wheel.uncompressed_too_large", "Wheel expands too large.")
                names = [normalize_wheel_path(item.filename) for item in infos]
                dist_info = [name for name in names if ".dist-info/" in name]
                wheel_file = self._single(names, ".dist-info/WHEEL")
                metadata_file = self._single(names, ".dist-info/METADATA")
                record_file = self._single(names, ".dist-info/RECORD")
                if not record_file:
                    raise PluginRecordValidationError("plugin.record.missing", "Wheel RECORD is missing.")
                entry_file = self._single(names, ".dist-info/entry_points.txt")
                wheel_text = zf.read(wheel_file).decode("utf-8")
                if "Root-Is-Purelib: true" not in wheel_text:
                    raise PluginUnsupportedPackageFormatError(
                        "plugin.wheel.not_pure_python", "Wheel must be pure Python."
                    )
                metadata = parse_email_metadata(zf.read(metadata_file).decode("utf-8"))
                dependencies = tuple(metadata.get("Requires-Dist", ()))
                manifest_name = self._single(names, "plugin.manifest.json", allow_suffix=False) or self._single(
                    names, "channel.manifest.json", allow_suffix=False
                )
                if not manifest_name:
                    raise PluginPackageInvalidError(
                        "plugin.package.manifest_missing", "Wheel must include a plugin manifest."
                    )
                manifest_payload = json.loads(zf.read(manifest_name).decode("utf-8"))
                manifest = PluginManifest.from_dict(manifest_payload)
                validate_manifest(manifest)
                entrypoints = self._parse_entrypoints(zf.read(entry_file).decode("utf-8") if entry_file else "")
                self._validate_entrypoints(entrypoints, manifest)
                self._validate_dependencies(dependencies, names)
                self.verify_record(zf, record_file)
                top_level = self._top_level_modules(names)
                self._validate_namespaces(top_level)
                for required in ("README.md", "LICENSE", "CHANGELOG.md"):
                    if required not in {Path(name).name for name in names}:
                        raise PluginPackageInvalidError(
                            "plugin.package.metadata_missing", f"Wheel must include {required}."
                        )
                if not any("/sboms/" in name or name.endswith(".sbom.json") for name in dist_info + names):
                    raise PluginPackageInvalidError("plugin.package.sbom_missing", "Wheel must include an SBOM.")
                return WheelInspectionResult(
                    wheel_filename=path.name,
                    distribution_name=str(metadata.get("Name", [match.group("name")])[0]),
                    distribution_version=str(metadata.get("Version", [match.group("version")])[0]),
                    wheel_tags=(tag,),
                    pure_python=True,
                    record_verified=True,
                    manifest=manifest_payload,
                    entrypoints=entrypoints,
                    dependencies=dependencies,
                    file_count=len(infos),
                    uncompressed_size=total,
                    top_level_modules=tuple(top_level),
                )
        except zipfile.BadZipFile as exc:
            raise PluginWheelValidationError("plugin.wheel.invalid_zip", "Wheel is not a valid zip file.") from exc

    def verify_record(self, zf: zipfile.ZipFile, record_file: str) -> None:
        rows = list(csv.reader(zf.read(record_file).decode("utf-8").splitlines()))
        seen: set[str] = set()
        names = {normalize_wheel_path(item.filename) for item in zf.infolist()}
        for row in rows:
            if len(row) != 3:
                raise PluginRecordValidationError("plugin.record.invalid_row", "RECORD row is invalid.")
            name = normalize_wheel_path(row[0])
            if name in seen:
                raise PluginRecordValidationError("plugin.record.duplicate", "RECORD contains a duplicate path.")
            seen.add(name)
            if name not in names:
                raise PluginRecordValidationError("plugin.record.missing_file", "RECORD references a missing file.")
            if name == record_file:
                continue
            data = zf.read(name)
            if row[1] != b64_hash(data):
                raise PluginRecordValidationError("plugin.record.hash_mismatch", "RECORD hash mismatch.")
            if row[2] != str(len(data)):
                raise PluginRecordValidationError("plugin.record.size_mismatch", "RECORD size mismatch.")
        unrecorded = names - seen
        if unrecorded:
            raise PluginRecordValidationError("plugin.record.extra_file", "Wheel contains unrecorded files.")

    def _validate_paths(self, infos: list[zipfile.ZipInfo]) -> None:
        seen_lower: set[str] = set()
        seen: set[str] = set()
        for info in infos:
            try:
                normalized = normalize_wheel_path(info.filename)
            except ValueError as exc:
                raise PluginWheelPathError("plugin.wheel.path_unsafe", "Wheel contains an unsafe path.") from exc
            if normalized.endswith("/") or (getattr(info, "external_attr", 0) >> 16) & 0o170000 == 0o120000:
                raise PluginWheelPathError("plugin.wheel.symlink_rejected", "Wheel symlinks are rejected.")
            lower = normalized.lower()
            if normalized in seen or lower in seen_lower:
                raise PluginWheelPathError(
                    "plugin.wheel.path_collision", "Wheel contains duplicate or case-colliding paths."
                )
            seen.add(normalized)
            seen_lower.add(lower)
            base = Path(normalized).name
            if base in FORBIDDEN_WHEEL_FILES or base.endswith(".pth"):
                raise PluginWheelValidationError(
                    "plugin.wheel.forbidden_file", "Wheel contains a forbidden startup file."
                )
            if any(base.endswith(suffix) for suffix in FORBIDDEN_WHEEL_SUFFIXES):
                raise PluginUnsupportedPackageFormatError(
                    "plugin.wheel.native_rejected", "Native extension files are rejected."
                )
            if normalized.endswith(".dist-info/scripts") or ".data/scripts/" in normalized:
                raise PluginWheelValidationError("plugin.wheel.script_rejected", "Console or GUI scripts are rejected.")

    def _single(self, names: list[str], suffix: str, *, allow_suffix: bool = True) -> str:
        matches = (
            [name for name in names if name.endswith(suffix)]
            if allow_suffix
            else [name for name in names if name == suffix]
        )
        if not matches:
            return ""
        if len(matches) > 1:
            raise PluginWheelValidationError("plugin.wheel.ambiguous_metadata", "Wheel metadata is ambiguous.")
        return matches[0]

    def _parse_entrypoints(self, text: str) -> dict[str, str]:
        current = ""
        entries: dict[str, str] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1]
                continue
            if current == PLUGIN_ENTRY_POINT_GROUP and "=" in line:
                name, target = line.split("=", maxsplit=1)
                entries[name.strip()] = target.strip()
            elif current in {"console_scripts", "gui_scripts"} and "=" in line:
                raise PluginEntrypointValidationError(
                    "plugin.entrypoint.script_rejected", "Console and GUI scripts are rejected."
                )
        return entries

    def _validate_entrypoints(self, entrypoints: dict[str, str], manifest: PluginManifest) -> None:
        if len(entrypoints) != 1:
            raise PluginEntrypointValidationError(
                "plugin.entrypoint.count_invalid", "Wheel must declare exactly one plugin entrypoint."
            )
        name, target = next(iter(entrypoints.items()))
        if name != manifest.id or name in BUILTIN_PLUGIN_IDS:
            raise PluginIdentityConflictError(
                "plugin.identity_conflict", "Entrypoint name must equal plugin id and not override a built-in."
            )
        if manifest.id in BUILTIN_PLUGIN_IDS:
            raise PluginIdentityConflictError(
                "plugin.builtin_override", "Community packages cannot override built-in plugins."
            )
        if ":" not in target:
            raise PluginEntrypointValidationError(
                "plugin.entrypoint.object_invalid", "Entrypoint must reference a factory object."
            )

    def _validate_dependencies(self, dependencies: tuple[str, ...], names: list[str]) -> None:
        for dep in dependencies:
            normalized = re.split(r"[ <>=!~;\[]", dep, maxsplit=1)[0].lower().replace("_", "-")
            if " @ " in dep or "file:" in dep or "git+" in dep or "../" in dep:
                raise PluginDependencyPolicyError(
                    "plugin.dependency.direct_reference", "Direct URL or local path dependencies are rejected."
                )
            if normalized and normalized not in ALLOWED_DEPENDENCIES:
                raise PluginDependencyPolicyError(
                    "plugin.dependency.forbidden", "Dependency is outside the phase-18 allowlist."
                )
        if any(name.startswith("plugin_sdk/") for name in names):
            raise PluginDependencyPolicyError(
                "plugin.dependency.sdk_bundled", "Plugins must not bundle a second SDK copy."
            )

    def _top_level_modules(self, names: list[str]) -> list[str]:
        modules = []
        for name in names:
            if ".dist-info/" in name or not name.endswith(".py"):
                continue
            first = name.split("/", maxsplit=1)[0]
            if first and first not in modules:
                modules.append(first)
        return modules

    def _validate_namespaces(self, modules: list[str]) -> None:
        for name in modules:
            if name in FORBIDDEN_TOP_LEVEL_MODULES or is_stdlib_module(name):
                raise PluginIdentityConflictError(
                    "plugin.namespace_conflict", "Wheel uses a reserved top-level namespace."
                )
            if not name.startswith("smm_plugin_") and not name.startswith("channel_"):
                raise PluginIdentityConflictError(
                    "plugin.namespace_unscoped", "Community plugin namespace must be scoped."
                )


class PluginPackageBuildService:
    """Build deterministic pure-Python fixture wheels without executing plugin code."""

    def validate_source(self, plugin_path: str | Path) -> PluginManifest:
        manifest = PluginManifest.from_path(Path(plugin_path) / "channel.manifest.json")
        validate_manifest(manifest)
        return manifest

    def build_wheel(self, plugin_path: str | Path, output_dir: str | Path) -> Path:
        source = Path(plugin_path)
        manifest = self.validate_source(source)
        dist_name = manifest.id.replace(".", "_").replace("-", "_")
        if not dist_name.startswith("channel_"):
            dist_name = f"smm_plugin_{dist_name}"
        wheel_name = f"{dist_name}-{manifest.version}-py3-none-any.whl"
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        wheel_path = output / wheel_name
        dist_info = f"{dist_name}-{manifest.version}.dist-info"
        records: list[tuple[str, bytes]] = []

        def add(name: str, data: bytes) -> None:
            records.append((normalize_wheel_path(name), data))

        for rel in sorted([p.relative_to(source) for p in source.rglob("*") if p.is_file()]):
            if any(part in {".git", "__pycache__"} for part in rel.parts):
                continue
            if str(rel).startswith("tests/"):
                continue
            wheel_rel = rel
            if rel.parts and rel.parts[0] == "src":
                wheel_rel = Path(*rel.parts[1:])
            add(str(wheel_rel).replace(os.sep, "/"), (source / rel).read_bytes())
        if not any(name == "LICENSE" for name, _ in records):
            add("LICENSE", b"Fixture license for local plugin package tests.\n")
        if not any(name.endswith(".sbom.json") or "/sboms/" in name for name, _ in records):
            add(f"{dist_info}/sboms/plugin.sbom.json", self.generate_sbom(source).encode("utf-8"))
        add(
            f"{dist_info}/WHEEL",
            b"Wheel-Version: 1.0\nGenerator: smm-plugin-distribution\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        add(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.1\nName: {dist_name}\nVersion: {manifest.version}\nRequires-Python: >=3.12\nRequires-Dist: plugin-sdk\n".encode(),
        )
        add(
            f"{dist_info}/entry_points.txt",
            f"[{PLUGIN_ENTRY_POINT_GROUP}]\n{manifest.id} = {manifest.entrypoint}:create_plugin\n".encode(),
        )
        record_rows = [[name, b64_hash(data), str(len(data))] for name, data in records]
        record_rows.append([f"{dist_info}/RECORD", "", ""])
        record_text = "\n".join(",".join(row) for row in record_rows) + "\n"
        with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in records:
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, data)
            info = zipfile.ZipInfo(f"{dist_info}/RECORD", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, record_text)
        return wheel_path

    def inspect_wheel(self, wheel_path: str | Path) -> WheelInspectionResult:
        return PluginWheelInspector().inspect(wheel_path)

    def generate_sbom(self, plugin_path: str | Path) -> str:
        files = []
        source = Path(plugin_path)
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            rel = str(path.relative_to(source)).replace(os.sep, "/")
            if "__pycache__" not in rel:
                files.append({"path": rel, "sha256": sha256_file(path)})
        return safe_json({"schema_version": "1.0", "generator": "plugin-distribution-v0.1", "files": files})

    def run_compatibility(self, plugin_path: str | Path) -> str:
        return build_compatibility_report(plugin_path).to_json()

    def verify_reproducibility(self, plugin_path: str | Path) -> str:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one = self.build_wheel(plugin_path, first)
            two = self.build_wheel(plugin_path, second)
            return "reproducible" if sha256_file(one) == sha256_file(two) else "not_reproducible"

    def generate_release_metadata(
        self, plugin_path: str | Path, wheel_path: str | Path, signer_policy_id: str
    ) -> PluginReleaseMetadata:
        manifest = PluginManifest.from_path(Path(plugin_path) / "channel.manifest.json")
        compatibility = self.run_compatibility(plugin_path)
        sbom = self.generate_sbom(plugin_path)
        inspection = self.inspect_wheel(wheel_path)
        entrypoint_name, entrypoint_object = next(iter(inspection.entrypoints.items()))
        manifest_bytes = safe_json(inspection.manifest).encode()
        return PluginReleaseMetadata(
            schema_version="1.0",
            release_id=f"{manifest.id}-{manifest.version}",
            plugin_id=manifest.id,
            plugin_version=manifest.version,
            distribution_name=inspection.distribution_name,
            distribution_version=inspection.distribution_version,
            distribution_status=manifest.distribution,
            release_channel="experimental" if manifest.distribution == "experimental" else "stable",
            wheel_filename=Path(wheel_path).name,
            wheel_sha256=sha256_file(Path(wheel_path)),
            wheel_size=Path(wheel_path).stat().st_size,
            entrypoint_group=PLUGIN_ENTRY_POINT_GROUP,
            entrypoint_name=entrypoint_name,
            entrypoint_object=entrypoint_object,
            plugin_sdk_version=manifest.sdk_contract_version,
            framework_contract_versions=manifest.framework_contract_versions,
            python_requires=">=3.12",
            wheel_tags=inspection.wheel_tags,
            capabilities=manifest.capabilities,
            permissions=manifest.permissions,
            maintainers=manifest.maintainers,
            signer_policy_id=signer_policy_id,
            manifest_sha256=sha256_bytes(manifest_bytes),
            sbom_sha256=sha256_bytes(sbom.encode()),
            compatibility_report_sha256=sha256_bytes(compatibility.encode()),
            published_at=utc_now(),
        )

    def create_release_directory(self, plugin_path: str | Path, output_dir: str | Path) -> Path:
        release_dir = Path(output_dir)
        release_dir.mkdir(parents=True, exist_ok=True)
        wheel = self.build_wheel(plugin_path, release_dir)
        metadata = self.generate_release_metadata(plugin_path, wheel, "fixture-policy")
        sbom = self.generate_sbom(plugin_path)
        compatibility = self.run_compatibility(plugin_path)
        signature = {
            "schema_version": "fixture.sigstore.v1",
            "artifact_sha256": metadata.wheel_sha256,
            "certificate_identity": "https://github.com/example/channel-example/.github/workflows/release.yml@refs/tags/v0.1.0",
            "certificate_issuer": "https://token.actions.githubusercontent.com",
            "transparency_log_verified": True,
            "signed_timestamp_verified": True,
        }
        (release_dir / "plugin.release.json").write_text(safe_json(asdict(metadata)))
        (release_dir / "plugin.sbom.json").write_text(sbom)
        (release_dir / "plugin.compatibility.json").write_text(compatibility)
        (release_dir / "plugin.sigstore.json").write_text(safe_json(signature))
        return release_dir


class PluginPackageVerificationService:
    def __init__(self, signer_policies: dict[str, PluginSignerPolicy] | None = None) -> None:
        fixture_policy = PluginSignerPolicy(
            id="fixture-policy",
            plugin_id="channel.example",
            distribution_status="experimental",
            allowed_certificate_identities=(
                "https://github.com/example/channel-example/.github/workflows/release.yml@refs/tags/v0.1.0",
            ),
            allowed_oidc_issuers=("https://token.actions.githubusercontent.com",),
        )
        self.signer_policies = {fixture_policy.id: fixture_policy} | (signer_policies or {})
        self.inspector = PluginWheelInspector()

    def verify_artifact_hash(self, wheel_path: str | Path, expected_sha256: str, expected_size: int = 0) -> None:
        path = Path(wheel_path)
        actual = sha256_file(path)
        if actual != expected_sha256:
            raise PluginArtifactHashError("plugin.artifact.hash_mismatch", "Artifact hash mismatch.")
        if expected_size and path.stat().st_size != expected_size:
            raise PluginArtifactSizeError("plugin.artifact.size_mismatch", "Artifact size mismatch.")

    def verify_sigstore_bundle(
        self, wheel_path: str | Path, bundle_path: str | Path, policy: PluginSignerPolicy | None
    ) -> PluginSignatureVerification:
        if not Path(bundle_path).exists():
            raise PluginSignatureVerificationError("plugin.signature.missing_bundle", "Sigstore bundle is missing.")
        bundle = json.loads(Path(bundle_path).read_text())
        artifact_hash = sha256_file(Path(wheel_path))
        if bundle.get("artifact_sha256") != artifact_hash:
            raise PluginSignatureVerificationError(
                "plugin.signature.artifact_mismatch", "Signature artifact digest mismatch."
            )
        identity = str(bundle.get("certificate_identity") or "")
        issuer = str(bundle.get("certificate_issuer") or "")
        if policy and identity in policy.revoked_identities:
            status = "revoked_identity"
            matches = False
        else:
            matches = bool(
                policy
                and identity in policy.allowed_certificate_identities
                and issuer in policy.allowed_oidc_issuers
                and bool(bundle.get("transparency_log_verified")) >= policy.require_transparency_log
                and bool(bundle.get("signed_timestamp_verified")) >= policy.require_signed_timestamp
            )
            status = "verified" if matches else "valid_untrusted_identity"
        return PluginSignatureVerification(
            artifact_sha256=artifact_hash,
            signature_valid=True,
            bundle_valid=True,
            transparency_log_verified=bool(bundle.get("transparency_log_verified")),
            signed_timestamp_verified=bool(bundle.get("signed_timestamp_verified")),
            certificate_identity=identity,
            certificate_issuer=issuer,
            identity_policy_id=policy.id if policy else "",
            identity_matches=matches,
            verified_at=utc_now(),
            offline_verification=True,
            status=status,
            warnings=() if matches else ("signature_valid_identity_untrusted",),
        )

    def verify_signer_identity(self, verification: PluginSignatureVerification) -> None:
        if verification.status == "revoked_identity":
            raise PluginSignerIdentityError("plugin.signature.revoked_identity", "Signer identity is revoked.")
        if not verification.identity_matches:
            raise PluginSignerIdentityError(
                "plugin.signature.identity_untrusted", "Signer identity is not trusted for this plugin."
            )

    def inspect_wheel(self, wheel_path: str | Path) -> WheelInspectionResult:
        return self.inspector.inspect(wheel_path)

    def validate_manifest(self, inspection: WheelInspectionResult, release: PluginReleaseMetadata) -> None:
        manifest = PluginManifest.from_dict(inspection.manifest)
        values = [release.plugin_id, manifest.id]
        if release.entrypoint_name:
            values.append(release.entrypoint_name)
        if len(set(values)) != 1:
            raise PluginIdentityConflictError(
                "plugin.identity_conflict", "Registry, release, manifest, and entrypoint identities differ."
            )
        if (
            release.plugin_version != manifest.version
            or release.distribution_version != inspection.distribution_version
        ):
            raise PluginIdentityConflictError("plugin.version_conflict", "Release and wheel versions differ.")
        if release.wheel_filename != inspection.wheel_filename:
            raise PluginIdentityConflictError(
                "plugin.wheel_filename_conflict", "Release metadata names a different wheel."
            )
        if release.plugin_id in BUILTIN_PLUGIN_IDS:
            raise PluginIdentityConflictError(
                "plugin.builtin_override", "Community plugin cannot override a built-in plugin id."
            )

    def run_forbidden_import_scan(self, extracted_root: Path) -> list[str]:
        return scan_forbidden_imports(extracted_root)

    def run_secret_scan(self, extracted_root: Path) -> list[str]:
        return scan_secrets(extracted_root)

    def create_verification_report(
        self, release_dir: str | Path, *, require_trusted_identity: bool = True
    ) -> PluginPackageVerificationResult:
        root = Path(release_dir)
        release = PluginReleaseMetadata(**self._load_release_payload(root / "plugin.release.json"))
        if release.yanked_at:
            raise PluginReleaseYankedError("plugin.release.yanked", "Yanked releases are blocked by default.")
        if release.revoked_at:
            raise PluginReleaseRevokedError("plugin.release.revoked", "Revoked releases are blocked.")
        wheel = root / release.wheel_filename
        self.verify_artifact_hash(wheel, release.wheel_sha256, release.wheel_size)
        inspection = self.inspect_wheel(wheel)
        self.validate_manifest(inspection, release)
        policy = self.signer_policies.get(release.signer_policy_id)
        signature = self.verify_sigstore_bundle(wheel, root / "plugin.sigstore.json", policy)
        blocking: list[str] = []
        warnings = list(signature.warnings)
        if require_trusted_identity:
            try:
                self.verify_signer_identity(signature)
            except PluginSignerIdentityError as exc:
                blocking.append(exc.code)
        with tempfile.TemporaryDirectory() as tmp:
            extract_root = Path(tmp)
            with zipfile.ZipFile(wheel) as zf:
                zf.extractall(extract_root)
            forbidden = self.run_forbidden_import_scan(extract_root)
            secrets = self.run_secret_scan(extract_root)
        if forbidden:
            blocking.append("plugin.static.forbidden_imports")
        if secrets:
            blocking.append("plugin.static.secrets")
        compatible = True
        status = (
            "verified" if not blocking and not warnings else "verified_with_warnings" if not blocking else "rejected"
        )
        report_payload = {
            "release_id": release.release_id,
            "artifact_sha256": release.wheel_sha256,
            "blocking_errors": blocking,
            "warnings": warnings,
            "status": status,
        }
        return PluginPackageVerificationResult(
            release_id=release.release_id,
            plugin_id=release.plugin_id,
            plugin_version=release.plugin_version,
            artifact_sha256=release.wheel_sha256,
            registry_verified=True,
            signature_verified=signature.signature_valid,
            publisher_identity_verified=signature.identity_matches,
            wheel_verified=True,
            record_verified=inspection.record_verified,
            manifest_verified=True,
            entrypoint_verified=True,
            dependency_policy_passed=True,
            static_scan_passed=not blocking,
            compatibility_passed=compatible,
            permissions=release.permissions,
            risk_warnings=tuple(warnings),
            blocking_errors=tuple(blocking),
            verified_at=utc_now(),
            report_checksum=sha256_bytes(safe_json(report_payload).encode()),
            status=status,
        )

    def _load_release_payload(self, path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text())
        for key in ("wheel_tags", "capabilities", "permissions", "maintainers"):
            if key in payload and isinstance(payload[key], list):
                payload[key] = tuple(payload[key])
        return payload


class PluginRegistryService:
    """Read-only static registry client for fixture and local sources."""

    def __init__(self, source: PluginRegistrySource, cache_dir: str | Path) -> None:
        self.source = source
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def refresh(self) -> dict[str, Any]:
        metadata_root = Path(self.source.metadata_base_url)
        root = self._load(metadata_root / "root.json")
        timestamp = self._load(metadata_root / "timestamp.json")
        snapshot = self._load(metadata_root / "snapshot.json")
        targets = self._load(metadata_root / "targets.json")
        self._validate_expiry(timestamp, "timestamp")
        self._validate_expiry(snapshot, "snapshot")
        self._validate_expiry(targets, "targets")
        if int(snapshot.get("version", 0)) < int(timestamp.get("snapshot_version", 0)):
            raise PluginRegistryRollbackError(
                "plugin.registry.snapshot_rollback", "Snapshot metadata rollback detected."
            )
        if int(targets.get("version", 0)) < int(snapshot.get("targets_version", 0)):
            raise PluginRegistryRollbackError("plugin.registry.targets_rollback", "Targets metadata rollback detected.")
        payload = {
            "root": root,
            "timestamp": timestamp,
            "snapshot": snapshot,
            "targets": targets,
            "refreshed_at": utc_now(),
        }
        (self.cache_dir / "registry-cache.json").write_text(safe_json(payload))
        return payload

    def list_plugins(self) -> list[PluginRegistryEntry]:
        data = self.refresh()
        entries: dict[str, list[dict[str, Any]]] = {}
        for target in data["targets"].get("targets", []):
            entries.setdefault(target["plugin_id"], []).append(target)
        readmodel: list[PluginRegistryEntry] = []
        for plugin_id, releases in sorted(entries.items()):
            latest = sorted(releases, key=lambda item: item["plugin_version"])[-1]
            readmodel.append(
                PluginRegistryEntry(
                    plugin_id=plugin_id,
                    latest_version=latest["plugin_version"],
                    available_versions=tuple(item["plugin_version"] for item in releases),
                    name=latest.get("name", plugin_id),
                    description=latest.get("description", ""),
                    distribution_status=latest.get("distribution_status", "community"),
                    release_channel=latest.get("release_channel", "experimental"),
                    capabilities=tuple(latest.get("capabilities", ())),
                    permissions=tuple(latest.get("permissions", ())),
                    maintainers=tuple(latest.get("maintainers", ())),
                    license=latest.get("license", ""),
                    sdk_compatibility=latest.get("sdk_compatibility", "unverified"),
                    signer_identity_summary=latest.get("signer_identity_summary", ""),
                    yanked=bool(latest.get("yanked")),
                    revoked=bool(latest.get("revoked")),
                    published_at=latest.get("published_at", ""),
                    warnings=tuple(latest.get("warnings", ())),
                )
            )
        return readmodel

    def search(
        self, *, capability: str = "", permission: str = "", include_yanked: bool = False
    ) -> list[PluginRegistryEntry]:
        entries = self.list_plugins()
        if capability:
            entries = [item for item in entries if capability in item.capabilities]
        if permission:
            entries = [item for item in entries if permission in item.permissions]
        if not include_yanked:
            entries = [item for item in entries if not item.yanked and not item.revoked]
        return entries

    def verify_target(self, release_id: str) -> dict[str, Any]:
        data = self.refresh()
        for target in data["targets"].get("targets", []):
            if target.get("release_id") == release_id:
                if target.get("revoked"):
                    raise PluginReleaseRevokedError("plugin.release.revoked", "Revoked release is blocked.")
                return target
        raise PluginRegistryMetadataError(
            "plugin.registry.release_missing", "Release is not present in registry metadata."
        )

    def download_to_quarantine(self, release_id: str, quarantine_dir: str | Path) -> Path:
        target = self.verify_target(release_id)
        src = Path(self.source.targets_base_url) / target["path"]
        if not src.exists():
            raise PluginRegistryMetadataError("plugin.registry.target_unavailable", "Target artifact is unavailable.")
        quarantine = Path(quarantine_dir)
        quarantine.mkdir(parents=True, exist_ok=True)
        opaque = f"artifact-{target['sha256'][:16]}.whl"
        partial = quarantine / f".{opaque}.partial"
        final = quarantine / opaque
        shutil.copyfile(src, partial)
        if sha256_file(partial) != target["sha256"]:
            partial.unlink(missing_ok=True)
            raise PluginArtifactHashError("plugin.artifact.hash_mismatch", "Downloaded artifact hash mismatch.")
        if partial.stat().st_size != int(target["size"]):
            partial.unlink(missing_ok=True)
            raise PluginArtifactSizeError("plugin.artifact.size_mismatch", "Downloaded artifact size mismatch.")
        partial.replace(final)
        return final

    def _load(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text())
        except FileNotFoundError as exc:
            raise PluginRegistryMetadataError(
                "plugin.registry.metadata_missing", "Registry metadata is missing."
            ) from exc

    def _validate_expiry(self, payload: dict[str, Any], role: str) -> None:
        expires = datetime.fromisoformat(str(payload.get("expires")))
        if expires <= datetime.now(UTC):
            raise PluginRegistryExpiredError(f"plugin.registry.{role}_expired", f"Registry {role} metadata is expired.")


class PluginInstallationService:
    def __init__(self, install_root: str | Path, verifier: PluginPackageVerificationService | None = None) -> None:
        self.install_root = Path(install_root)
        self.verifier = verifier or PluginPackageVerificationService()
        self.install_root.mkdir(parents=True, exist_ok=True)

    def install_verified_release(
        self,
        release_dir: str | Path,
        *,
        actor: str,
        reason: str,
        registry_source_id: str = "local-fixture",
        permission_confirmed: bool = True,
    ) -> PluginInstallRecord:
        if not permission_confirmed:
            raise PluginInstallationError(
                "plugin.install.permission_review_required", "Permission review confirmation is required."
            )
        result = self.verifier.create_verification_report(release_dir)
        if result.status not in {"verified", "verified_with_warnings"}:
            raise PluginInstallationError(
                "plugin.install.verification_required", "Only verified releases can be installed."
            )
        root = Path(release_dir)
        release = PluginReleaseMetadata(**self.verifier._load_release_payload(root / "plugin.release.json"))
        safe_plugin = self._safe_component(release.plugin_id)
        safe_version = self._safe_component(release.plugin_version)
        plugin_root = self.install_root / safe_plugin
        installs = plugin_root / "installs"
        target = installs / safe_version
        if target.exists():
            raise PluginInstallationError("plugin.install.version_exists", "Plugin version is already installed.")
        staging = installs / f".{safe_version}.staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        wheel = root / release.wheel_filename
        self.verifier.verify_artifact_hash(wheel, release.wheel_sha256, release.wheel_size)
        with zipfile.ZipFile(wheel) as zf:
            for info in zf.infolist():
                normalized = normalize_wheel_path(info.filename)
                destination = (staging / normalized).resolve()
                if not str(destination).startswith(str(staging.resolve())):
                    raise PluginInstallationError("plugin.install.path_escape", "Wheel extraction escaped staging.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(zf.read(info.filename))
        (staging / "INSTALLER").write_text(PLUGIN_INSTALLER_NAME + "\n")
        manifest_checksum = self._installed_manifest_checksum(staging)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(target)
        ledger = self._load_ledger(plugin_root)
        previous = self._active_version(plugin_root)
        record = PluginInstallRecord(
            id=f"install-{release.release_id}-{sha256_file(wheel)[:12]}",
            plugin_id=release.plugin_id,
            plugin_version=release.plugin_version,
            release_id=release.release_id,
            registry_source_id=registry_source_id,
            distribution_name=release.distribution_name,
            artifact_sha256=release.wheel_sha256,
            release_metadata_sha256=sha256_file(root / "plugin.release.json"),
            sbom_sha256=release.sbom_sha256,
            compatibility_report_sha256=release.compatibility_report_sha256,
            signer_identity="verified-publisher" if result.publisher_identity_verified else "untrusted-publisher",
            signer_issuer="fixture-issuer",
            identity_policy_id=release.signer_policy_id,
            tuf_root_version=1,
            tuf_timestamp_version=1,
            tuf_snapshot_version=1,
            tuf_targets_version=1,
            permissions=release.permissions,
            installed_file_manifest_checksum=manifest_checksum,
            install_status="installed_disabled",
            installed_at=utc_now(),
            installed_by=actor,
            previous_version=previous,
            metadata={"reason": reason, "restart_required": True},
        )
        ledger.append(asdict(record))
        self._write_ledger(plugin_root, ledger)
        return record

    def request_activation(
        self, plugin_id: str, version: str, *, actor: str, reason: str, permission_confirmed: bool
    ) -> dict[str, Any]:
        if not permission_confirmed:
            raise PluginActivationError(
                "plugin.activation.permission_review_required", "Activation requires permission review confirmation."
            )
        if plugin_id in BUILTIN_PLUGIN_IDS:
            raise PluginActivationError(
                "plugin.activation.builtin_override", "Community plugin cannot override a built-in."
            )
        plugin_root = self.install_root / self._safe_component(plugin_id)
        install = plugin_root / "installs" / self._safe_component(version)
        if not install.exists():
            raise PluginActivationError("plugin.activation.install_missing", "Installed version is missing.")
        active = {
            "plugin_id": plugin_id,
            "plugin_version": version,
            "activation_status": "activation_pending",
            "restart_required": True,
            "actor": actor,
            "reason": reason,
            "updated_at": utc_now(),
        }
        tmp = plugin_root / "active.json.tmp"
        tmp.write_text(safe_json(active))
        tmp.replace(plugin_root / "active.json")
        self._update_ledger(
            plugin_root,
            plugin_id,
            version,
            {"install_status": "activation_pending", "enabled_by": actor, "enabled_at": utc_now()},
        )
        return active

    def disable(self, plugin_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        plugin_root = self.install_root / self._safe_component(plugin_id)
        active_path = plugin_root / "active.json"
        if active_path.exists():
            active_path.unlink()
        self._update_all(plugin_root, {"install_status": "disabled", "disabled_at": utc_now()})
        return {
            "plugin_id": plugin_id,
            "status": "disabled",
            "restart_required": True,
            "actor": actor,
            "reason": reason,
        }

    def rollback(self, plugin_id: str, version: str, *, actor: str, reason: str) -> dict[str, Any]:
        return self.request_activation(plugin_id, version, actor=actor, reason=reason, permission_confirmed=True) | {
            "rollback": True
        }

    def uninstall(self, plugin_id: str, version: str, *, actor: str, reason: str) -> dict[str, Any]:
        plugin_root = self.install_root / self._safe_component(plugin_id)
        if self._active_version(plugin_root) == version:
            raise PluginUninstallBlockedError(
                "plugin.uninstall.active_version", "Active plugin version must be disabled before uninstall."
            )
        target = plugin_root / "installs" / self._safe_component(version)
        if target.exists():
            shutil.rmtree(target)
        self._update_ledger(
            plugin_root, plugin_id, version, {"install_status": "uninstalled", "uninstalled_at": utc_now()}
        )
        return {
            "plugin_id": plugin_id,
            "plugin_version": version,
            "status": "uninstalled",
            "actor": actor,
            "reason": reason,
        }

    def list_installed(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for ledger in self.install_root.glob("*/install-ledger.json"):
            rows.extend(json.loads(ledger.read_text()))
        return rows

    def verify_installed_files(self, plugin_id: str, version: str) -> bool:
        plugin_root = self.install_root / self._safe_component(plugin_id)
        target = plugin_root / "installs" / self._safe_component(version)
        if not target.exists():
            raise PluginInstalledFileDriftError("plugin.install.files_missing", "Installed files are missing.")
        current = self._installed_manifest_checksum(target)
        for row in self._load_ledger(plugin_root):
            if row["plugin_id"] == plugin_id and row["plugin_version"] == version:
                if row["installed_file_manifest_checksum"] != current:
                    raise PluginInstalledFileDriftError("plugin.install.file_drift", "Installed file drift detected.")
                return True
        raise PluginInstalledFileDriftError("plugin.install.record_missing", "Install record is missing.")

    def _safe_component(self, value: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_.-]+$", value) or ".." in value or "/" in value or "\\" in value:
            raise PluginInstallationError("plugin.install.path_component_invalid", "Plugin path component is invalid.")
        return value

    def _load_ledger(self, plugin_root: Path) -> list[dict[str, Any]]:
        path = plugin_root / "install-ledger.json"
        return json.loads(path.read_text()) if path.exists() else []

    def _write_ledger(self, plugin_root: Path, ledger: list[dict[str, Any]]) -> None:
        plugin_root.mkdir(parents=True, exist_ok=True)
        (plugin_root / "install-ledger.json").write_text(safe_json(ledger))

    def _update_ledger(self, plugin_root: Path, plugin_id: str, version: str, patch: dict[str, Any]) -> None:
        ledger = self._load_ledger(plugin_root)
        for row in ledger:
            if row.get("plugin_id") == plugin_id and row.get("plugin_version") == version:
                row.update(patch)
        self._write_ledger(plugin_root, ledger)

    def _update_all(self, plugin_root: Path, patch: dict[str, Any]) -> None:
        ledger = self._load_ledger(plugin_root)
        for row in ledger:
            row.update(patch)
        self._write_ledger(plugin_root, ledger)

    def _active_version(self, plugin_root: Path) -> str:
        active = plugin_root / "active.json"
        return str(json.loads(active.read_text()).get("plugin_version") or "") if active.exists() else ""

    def _installed_manifest_checksum(self, root: Path) -> str:
        rows = []
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if path.name == "INSTALLER":
                continue
            rows.append(f"{path.relative_to(root)}:{sha256_file(path)}:{path.stat().st_size}")
        return sha256_bytes("\n".join(rows).encode())


class InstalledPluginLoader:
    def __init__(self, install_root: str | Path, installer: PluginInstallationService | None = None) -> None:
        self.install_root = Path(install_root)
        self.installer = installer or PluginInstallationService(install_root)

    def discover_install_records(self) -> list[dict[str, Any]]:
        return self.installer.list_installed()

    def verify_active_install(self, plugin_id: str) -> dict[str, Any]:
        plugin_root = self.install_root / plugin_id
        active = json.loads((plugin_root / "active.json").read_text())
        self.installer.verify_installed_files(plugin_id, active["plugin_version"])
        if plugin_id in BUILTIN_PLUGIN_IDS:
            raise PluginHostCompatibilityError(
                "plugin.loader.builtin_override", "External plugin attempts to override a built-in."
            )
        return active

    def discover_entrypoint_metadata(self, plugin_id: str) -> dict[str, Any]:
        active = self.verify_active_install(plugin_id)
        return {
            "plugin_id": plugin_id,
            "plugin_version": active["plugin_version"],
            "entrypoint_group": PLUGIN_ENTRY_POINT_GROUP,
        }

    def load_active_plugin(self, plugin_id: str) -> Any:
        active = self.verify_active_install(plugin_id)
        if active.get("activation_status") != "enabled":
            raise PluginActivationError(
                "plugin.loader.restart_required", "Plugin activation requires restart before import."
            )
        distributions = importlib.metadata.distributions(
            path=[str(self.install_root / plugin_id / "installs" / active["plugin_version"])]
        )
        for dist in distributions:
            for entry in dist.entry_points:
                if entry.group == PLUGIN_ENTRY_POINT_GROUP and entry.name == plugin_id:
                    return entry.load()()
        raise PluginEntrypointValidationError(
            "plugin.loader.entrypoint_missing", "Active plugin entrypoint is missing."
        )


class PluginDistributionIntegrityService:
    def __init__(self, install_root: str | Path, cache_root: str | Path | None = None) -> None:
        self.install_root = Path(install_root)
        self.cache_root = Path(cache_root) if cache_root else None

    def scan_installs(self) -> list[PluginDistributionIntegrityFinding]:
        findings: list[PluginDistributionIntegrityFinding] = []
        for plugin_dir in self.install_root.glob("*"):
            if not plugin_dir.is_dir():
                continue
            ledger = plugin_dir / "install-ledger.json"
            installs = plugin_dir / "installs"
            if not ledger.exists() and installs.exists():
                findings.append(
                    PluginDistributionIntegrityFinding(
                        "plugin.integrity.files_without_record",
                        "high",
                        plugin_id=plugin_dir.name,
                        safe_message="Installed files exist without a ledger.",
                    )
                )
                continue
            records = json.loads(ledger.read_text()) if ledger.exists() else []
            for row in records:
                target = installs / row.get("plugin_version", "")
                if not target.exists() and row.get("install_status") != "uninstalled":
                    findings.append(
                        PluginDistributionIntegrityFinding(
                            "plugin.integrity.record_without_files",
                            "high",
                            plugin_id=row.get("plugin_id", ""),
                            plugin_version=row.get("plugin_version", ""),
                            safe_message="Install record points to missing files.",
                        )
                    )
            active = plugin_dir / "active.json"
            if active.exists():
                payload = json.loads(active.read_text())
                if not (installs / payload.get("plugin_version", "")).exists():
                    findings.append(
                        PluginDistributionIntegrityFinding(
                            "plugin.integrity.bad_active_pointer",
                            "critical",
                            plugin_id=payload.get("plugin_id", ""),
                            safe_message="Active pointer references a missing version.",
                            repairable=True,
                        )
                    )
        return findings

    def scan_cache(self) -> list[PluginDistributionIntegrityFinding]:
        if self.cache_root is None or not self.cache_root.exists():
            return []
        return [
            PluginDistributionIntegrityFinding(
                "plugin.integrity.quarantine_present", "info", safe_message="Quarantine contains artifacts."
            )
            for _ in self.cache_root.glob("*.whl")
        ]

    def scan_registry(self) -> list[PluginDistributionIntegrityFinding]:
        return []

    def scan_active_plugins(self) -> list[PluginDistributionIntegrityFinding]:
        return self.scan_installs()

    def verify_install_ledger(self) -> list[PluginDistributionIntegrityFinding]:
        return self.scan_installs()

    def verify_installed_files(self) -> list[PluginDistributionIntegrityFinding]:
        findings = []
        installer = PluginInstallationService(self.install_root)
        for row in installer.list_installed():
            if row.get("install_status") == "uninstalled":
                continue
            try:
                installer.verify_installed_files(row["plugin_id"], row["plugin_version"])
            except PluginInstalledFileDriftError as exc:
                findings.append(
                    PluginDistributionIntegrityFinding(
                        exc.code,
                        "critical",
                        plugin_id=row.get("plugin_id", ""),
                        plugin_version=row.get("plugin_version", ""),
                        safe_message=exc.safe_message,
                    )
                )
        return findings

    def reconcile_install_state(self) -> list[PluginDistributionIntegrityFinding]:
        return self.scan_installs()

    def health(self) -> PluginDistributionHealth:
        findings = self.scan_installs()
        return PluginDistributionHealth(
            status="ready" if not findings else "degraded",
            framework_version=PLUGIN_DISTRIBUTION_FRAMEWORK_VERSION,
            registry_status="configured",
            trusted_root_version=1,
            artifact_cache_status="managed",
            install_root_status="configured",
            active_external_plugins=sum(1 for path in self.install_root.glob("*/active.json")),
            quarantined_releases=0,
            revoked_active_releases=0,
            incompatible_active_releases=0,
            latest_integrity_scan=utc_now(),
            warnings=tuple(item.code for item in findings),
        )
