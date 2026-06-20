from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import channel_registry

from tests.test_support import build_manifest, isolated_channel_store, write_plugin


class ChannelRegistryTests(unittest.TestCase):
    def test_missing_channels_directory_fails_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_dir = Path(tmp) / "missing-channels"
            with isolated_channel_store(Path(tmp)):
                with patch.object(channel_registry, "CHANNELS_DIR", missing_dir):
                    self.assertEqual(channel_registry.scan_channel_registry(), [])

    def test_valid_placeholder_plugin_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            channels_dir = tmp_path / "channels"
            manifest = build_manifest(channel_id="blog", name="Blog / Website")
            write_plugin(channels_dir, "blog", manifest, include_readme=True)
            with isolated_channel_store(tmp_path):
                with patch.object(channel_registry, "CHANNELS_DIR", channels_dir):
                    entries = channel_registry.scan_channel_registry()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].id, "blog")
            self.assertEqual(entries[0].health, "ready")
            self.assertEqual(entries[0].connection_status, "disabled")

    def test_invalid_manifest_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            channels_dir = tmp_path / "channels"
            invalid_manifest = build_manifest(channel_id="broken")
            invalid_manifest.pop("description")
            write_plugin(channels_dir, "broken", invalid_manifest, include_readme=True)
            with isolated_channel_store(tmp_path):
                with patch.object(channel_registry, "CHANNELS_DIR", channels_dir):
                    entries = channel_registry.scan_channel_registry()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].health, "invalid_manifest")
            self.assertTrue(any("description is required." in error for error in entries[0].errors))

    def test_duplicate_plugin_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            channels_dir = tmp_path / "channels"
            manifest = build_manifest(channel_id="shared", name="Shared")
            write_plugin(channels_dir, "one", manifest, include_readme=True)
            write_plugin(channels_dir, "two", manifest, include_readme=True)
            with isolated_channel_store(tmp_path):
                with patch.object(channel_registry, "CHANNELS_DIR", channels_dir):
                    entries = channel_registry.scan_channel_registry()
            self.assertEqual(len(entries), 2)
            self.assertTrue(all(entry.health == "invalid_manifest" for entry in entries))
            self.assertTrue(any("Duplicate plugin id 'shared'" in " ".join(entry.errors) for entry in entries))

    def test_generate_plugin_requires_rules_prompts_and_worker_when_declared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            channels_dir = tmp_path / "channels"
            manifest = build_manifest(
                channel_id="linkedinish",
                name="Linkedinish",
                status="experimental",
                mode="playwright_local",
                can_generate=True,
                can_publish=True,
                can_fetch_metrics=True,
                can_connect=True,
                can_disconnect=True,
                can_check_status=True,
                output_types=["linkedin_post"],
                metrics_mode="playwright_local_snapshot",
            )
            write_plugin(channels_dir, "linkedinish", manifest, include_readme=True)
            with isolated_channel_store(tmp_path):
                with patch.object(channel_registry, "CHANNELS_DIR", channels_dir):
                    entries = channel_registry.scan_channel_registry()
            self.assertEqual(entries[0].health, "worker_missing")


class ManifestValidationTests(unittest.TestCase):
    def test_required_fields_and_supported_values_are_validated(self) -> None:
        manifest = build_manifest(channel_id="demo")
        manifest["mode"] = "bad-mode"
        manifest["status"] = "bad-status"
        manifest["outputTypes"] = [""]
        manifest["metrics"]["mode"] = "bad-metrics"
        manifest["capabilities"]["canGenerate"] = "yes"
        errors = channel_registry.validate_channel_manifest(manifest)
        self.assertTrue(any("mode must be one of" in error for error in errors))
        self.assertTrue(any("status must be one of" in error for error in errors))
        self.assertTrue(any("outputTypes entries must be non-empty strings." in error for error in errors))
        self.assertTrue(any("metrics.mode must be one of" in error for error in errors))
        self.assertTrue(any("capabilities.canGenerate must be a boolean." in error for error in errors))
