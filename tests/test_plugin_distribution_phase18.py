from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from dashboard import (
    plugin_distribution_health_payload,
    plugin_distribution_integrity_payload,
    plugin_installed_payload,
    plugin_registry_payload,
)
from src.core.plugin_distribution import (
    PLUGIN_ACTIVATION_CONTRACT_VERSION,
    PLUGIN_DISTRIBUTION_FRAMEWORK_VERSION,
    PLUGIN_ENTRY_POINT_GROUP,
    PLUGIN_INSTALLATION_CONTRACT_VERSION,
    PLUGIN_PACKAGE_CONTRACT_VERSION,
    PLUGIN_REGISTRY_CONTRACT_VERSION,
    PLUGIN_RELEASE_METADATA_CONTRACT_VERSION,
    PLUGIN_SIGNATURE_POLICY_CONTRACT_VERSION,
    PLUGIN_UPDATE_CONTRACT_VERSION,
    InstalledPluginLoader,
    PluginDistributionIntegrityService,
    PluginInstallationService,
    PluginPackageBuildService,
    PluginPackageVerificationService,
    PluginRegistryService,
    PluginRegistrySource,
)
from src.core.plugin_distribution.errors import (
    PluginActivationError,
    PluginArtifactHashError,
    PluginDependencyPolicyError,
    PluginIdentityConflictError,
    PluginInstalledFileDriftError,
    PluginRecordValidationError,
    PluginRegistryExpiredError,
    PluginReleaseRevokedError,
    PluginSignatureVerificationError,
    PluginUninstallBlockedError,
    PluginUnsupportedPackageFormatError,
    PluginWheelPathError,
    PluginWheelValidationError,
)
from src.core.plugin_distribution.services import safe_json


class PluginDistributionPhase18Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import integrations.plugin_registry.build_fixture as build_fixture

        build_fixture.main()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.template = Path("templates/channel-plugin")
        self.builder = PluginPackageBuildService()
        self.release_dir = self.root / "release"
        self.builder.create_release_directory(self.template, self.release_dir)
        self.wheel = next(self.release_dir.glob("*.whl"))

    def test_distribution_contract_versions_are_central(self) -> None:
        self.assertEqual(PLUGIN_DISTRIBUTION_FRAMEWORK_VERSION, "0.1.0")
        self.assertEqual(PLUGIN_PACKAGE_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_RELEASE_METADATA_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_SIGNATURE_POLICY_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_REGISTRY_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_INSTALLATION_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_ACTIVATION_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_UPDATE_CONTRACT_VERSION, "1.0")
        self.assertEqual(PLUGIN_ENTRY_POINT_GROUP, "social_media_manager.plugins")

    def test_builds_pure_python_wheel_release_metadata_sbom_and_reproducible_hash(self) -> None:
        inspection = self.builder.inspect_wheel(self.wheel)
        self.assertTrue(inspection.pure_python)
        self.assertEqual(inspection.wheel_tags, ("py3-none-any",))
        self.assertEqual(inspection.manifest["id"], "channel.example")
        self.assertIn("channel.example", inspection.entrypoints)
        self.assertTrue((self.release_dir / "plugin.release.json").exists())
        self.assertTrue((self.release_dir / "plugin.sbom.json").exists())
        self.assertEqual(self.builder.verify_reproducibility(self.template), "reproducible")

    def test_rejects_source_distributions_native_wheels_and_unsupported_tags(self) -> None:
        sdist = self.root / "pkg-0.1.0.tar.gz"
        sdist.write_text("x")
        with self.assertRaises(PluginUnsupportedPackageFormatError):
            self.builder.inspect_wheel(sdist)
        native = self.root / "pkg-0.1.0-cp312-cp312-linux_x86_64.whl"
        native.write_bytes(self.wheel.read_bytes())
        with self.assertRaises(PluginUnsupportedPackageFormatError):
            self.builder.inspect_wheel(native)

    def _mutated_wheel(self, name: str, extra: dict[str, bytes] | None = None, remove_record: bool = False) -> Path:
        target = self.root / name
        with zipfile.ZipFile(self.wheel) as src, zipfile.ZipFile(target, "w") as dst:
            for info in src.infolist():
                if remove_record and info.filename.endswith("/RECORD"):
                    continue
                dst.writestr(info, src.read(info.filename))
            for entry, data in (extra or {}).items():
                dst.writestr(entry, data)
        return target

    def _replace_metadata_wheel(self, name: str, append: str) -> Path:
        from src.core.plugin_distribution.services import b64_hash

        target = self.root / name
        files: dict[str, bytes] = {}
        with zipfile.ZipFile(self.wheel) as src:
            record = ""
            for info in src.infolist():
                if info.filename.endswith("/RECORD"):
                    record = info.filename
                    continue
                data = src.read(info.filename)
                if info.filename.endswith("/METADATA"):
                    data = data + append.encode()
                files[info.filename] = data
        rows = [f"{entry},{b64_hash(data)},{len(data)}" for entry, data in files.items()]
        rows.append(f"{record},,")
        with zipfile.ZipFile(target, "w") as dst:
            for entry, data in files.items():
                dst.writestr(entry, data)
            dst.writestr(record, "\n".join(rows) + "\n")
        return target

    def test_wheel_path_and_forbidden_file_security(self) -> None:
        with self.assertRaises(PluginWheelPathError):
            self.builder.inspect_wheel(self._mutated_wheel("bad-0.1.0-py3-none-any.whl", {"../evil.py": b"x"}))
        with self.assertRaises(PluginWheelValidationError):
            self.builder.inspect_wheel(self._mutated_wheel("bad2-0.1.0-py3-none-any.whl", {"bad.pth": b"import os"}))
        with self.assertRaises(PluginWheelValidationError):
            self.builder.inspect_wheel(self._mutated_wheel("bad3-0.1.0-py3-none-any.whl", {"sitecustomize.py": b""}))
        with self.assertRaises(PluginUnsupportedPackageFormatError):
            self.builder.inspect_wheel(
                self._mutated_wheel("bad4-0.1.0-py3-none-any.whl", {"channel_example/native.so": b""})
            )

    def test_record_validation_rejects_missing_or_extra_files(self) -> None:
        with self.assertRaises(PluginRecordValidationError):
            self.builder.inspect_wheel(self._mutated_wheel("missing-0.1.0-py3-none-any.whl", remove_record=True))
        with self.assertRaises(PluginRecordValidationError):
            self.builder.inspect_wheel(
                self._mutated_wheel("extra-0.1.0-py3-none-any.whl", {"channel_example/extra.py": b"x"})
            )

    def test_entrypoint_dependency_and_identity_policies(self) -> None:
        release = json.loads((self.release_dir / "plugin.release.json").read_text())
        release["entrypoint_name"] = "channel.other"
        (self.release_dir / "plugin.release.json").write_text(safe_json(release))
        with self.assertRaises(PluginIdentityConflictError):
            PluginPackageVerificationService().create_verification_report(self.release_dir)
        self.builder.create_release_directory(self.template, self.release_dir)
        bad_dep = self._replace_metadata_wheel("dep-0.1.0-py3-none-any.whl", "Requires-Dist: requests\n")
        with self.assertRaises(PluginDependencyPolicyError):
            self.builder.inspect_wheel(bad_dep)

    def test_sigstore_policy_offline_verification_and_failures(self) -> None:
        result = PluginPackageVerificationService().create_verification_report(self.release_dir)
        self.assertEqual(result.status, "verified")
        bundle = json.loads((self.release_dir / "plugin.sigstore.json").read_text())
        bundle["artifact_sha256"] = "0" * 64
        (self.release_dir / "plugin.sigstore.json").write_text(safe_json(bundle))
        with self.assertRaises(PluginSignatureVerificationError):
            PluginPackageVerificationService().create_verification_report(self.release_dir)

    def test_registry_fixture_refresh_search_and_metadata_only_browsing(self) -> None:
        source = PluginRegistrySource(
            id="fixture",
            name="Fixture",
            metadata_base_url="integrations/plugin_registry/metadata",
            targets_base_url="integrations/plugin_registry/targets",
            trusted_root_path="integrations/plugin_registry/trusted-root.json",
            allow_download=True,
            allow_install=True,
        )
        service = PluginRegistryService(source, self.root / "cache")
        service.refresh()
        entries = service.search(capability="channel.publish.text")
        self.assertEqual(entries[0].plugin_id, "channel.example")
        self.assertFalse(any(path.suffix == ".whl" for path in (self.root / "cache").rglob("*")))

    def test_registry_expired_metadata_and_hash_mismatch(self) -> None:
        metadata = self.root / "metadata"
        shutil.copytree("integrations/plugin_registry/metadata", metadata)
        targets = self.root / "targets"
        shutil.copytree("integrations/plugin_registry/targets", targets)
        timestamp = json.loads((metadata / "timestamp.json").read_text())
        timestamp["expires"] = "2000-01-01T00:00:00+00:00"
        (metadata / "timestamp.json").write_text(safe_json(timestamp))
        source = PluginRegistrySource("fixture", "Fixture", str(metadata), str(targets), "trusted-root.json")
        with self.assertRaises(PluginRegistryExpiredError):
            PluginRegistryService(source, self.root / "cache").refresh()
        timestamp["expires"] = "2999-01-01T00:00:00+00:00"
        (metadata / "timestamp.json").write_text(safe_json(timestamp))
        tuf_targets = json.loads((metadata / "targets.json").read_text())
        tuf_targets["targets"][0]["sha256"] = "0" * 64
        (metadata / "targets.json").write_text(safe_json(tuf_targets))
        with self.assertRaises(PluginArtifactHashError):
            PluginRegistryService(source, self.root / "cache2").download_to_quarantine(
                "channel.example-0.1.0", self.root / "q"
            )

    def test_download_quarantine_install_disabled_enable_requires_restart_and_loader_does_not_hot_import(self) -> None:
        install_root = self.root / "installs"
        installer = PluginInstallationService(install_root)
        record = installer.install_verified_release(
            self.release_dir, actor="tester", reason="reviewed", permission_confirmed=True
        )
        self.assertEqual(record.install_status, "installed_disabled")
        with self.assertRaises(PluginActivationError):
            installer.request_activation(
                "channel.example", "0.1.0", actor="tester", reason="no review", permission_confirmed=False
            )
        active = installer.request_activation(
            "channel.example", "0.1.0", actor="tester", reason="reviewed", permission_confirmed=True
        )
        self.assertTrue(active["restart_required"])
        with self.assertRaises(PluginActivationError):
            InstalledPluginLoader(install_root).load_active_plugin("channel.example")

    def test_installed_file_drift_rollback_disable_and_uninstall_guards(self) -> None:
        install_root = self.root / "installs"
        installer = PluginInstallationService(install_root)
        installer.install_verified_release(
            self.release_dir, actor="tester", reason="reviewed", permission_confirmed=True
        )
        installer.request_activation(
            "channel.example", "0.1.0", actor="tester", reason="reviewed", permission_confirmed=True
        )
        with self.assertRaises(PluginUninstallBlockedError):
            installer.uninstall("channel.example", "0.1.0", actor="tester", reason="active")
        installer.disable("channel.example", actor="tester", reason="stop")
        self.assertEqual(
            installer.uninstall("channel.example", "0.1.0", actor="tester", reason="cleanup")["status"], "uninstalled"
        )
        installer.install_verified_release(self.release_dir, actor="tester", reason="again", permission_confirmed=True)
        target = install_root / "channel.example" / "installs" / "0.1.0" / "channel_example" / "models.py"
        target.write_text("drift = True\n")
        with self.assertRaises(PluginInstalledFileDriftError):
            installer.verify_installed_files("channel.example", "0.1.0")

    def test_revoked_yanked_and_builtin_override_are_blocked(self) -> None:
        release = json.loads((self.release_dir / "plugin.release.json").read_text())
        release["revoked_at"] = "2026-01-01T00:00:00+00:00"
        (self.release_dir / "plugin.release.json").write_text(safe_json(release))
        with self.assertRaises(PluginReleaseRevokedError):
            PluginPackageVerificationService().create_verification_report(self.release_dir)
        self.builder.create_release_directory(self.template, self.release_dir)
        release = json.loads((self.release_dir / "plugin.release.json").read_text())
        release["plugin_id"] = "channel.linkedin"
        release["entrypoint_name"] = "channel.linkedin"
        (self.release_dir / "plugin.release.json").write_text(safe_json(release))
        with self.assertRaises(PluginIdentityConflictError):
            PluginPackageVerificationService().create_verification_report(self.release_dir)

    def test_local_unsigned_install_requires_development_flags_via_cli_policy(self) -> None:
        from plugin_sdk.cli import main as cli_main

        with self.assertRaises(SystemExit):
            cli_main(["plugin", "install-local", str(self.wheel), "--developer-unsigned"])
        self.assertEqual(
            cli_main(["plugin", "install-local", str(self.wheel), "--developer-unsigned", "--development-mode"]),
            0,
        )
        with self.assertRaises(SystemExit):
            cli_main(
                [
                    "plugin",
                    "install-local",
                    "https://example.invalid/plugin.whl",
                    "--developer-unsigned",
                    "--development-mode",
                ]
            )

    def test_dashboard_distribution_helpers_are_safe_and_read_only(self) -> None:
        health = plugin_distribution_health_payload()
        self.assertIn("signed != safe", health["warning"])
        registry = plugin_registry_payload()
        self.assertIn("plugins", registry)
        installed = plugin_installed_payload()
        self.assertIn("plugins", installed)
        integrity = plugin_distribution_integrity_payload()
        public = json.dumps(
            {"health": health, "registry": registry, "installed": installed, "integrity": integrity}
        ).lower()
        self.assertNotIn("private key", public)
        self.assertNotIn("certificatechain", public)

    def test_integrity_detects_records_and_files(self) -> None:
        install_root = self.root / "installs"
        findings = PluginDistributionIntegrityService(install_root).scan_installs()
        self.assertEqual(findings, [])
        dangling = install_root / "channel.example" / "installs" / "0.1.0"
        dangling.mkdir(parents=True)
        findings = PluginDistributionIntegrityService(install_root).scan_installs()
        self.assertEqual(findings[0].code, "plugin.integrity.files_without_record")

    def test_distribution_code_does_not_import_plugins_during_verify_or_install(self) -> None:
        text = Path("src/core/plugin_distribution/services.py").read_text()
        verify_section = text.split("class PluginPackageVerificationService", maxsplit=1)[1].split(
            "class PluginRegistryService", maxsplit=1
        )[0]
        install_section = text.split("class PluginInstallationService", maxsplit=1)[1].split(
            "class InstalledPluginLoader", maxsplit=1
        )[0]
        self.assertNotIn("entry.load", verify_section)
        self.assertNotIn("import_module", verify_section)
        self.assertNotIn("entry.load", install_section)
        self.assertNotIn("import_module", install_section)


if __name__ == "__main__":
    unittest.main()
