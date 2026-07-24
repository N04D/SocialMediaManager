"""Child process runtime for external plugins."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from typing import Any

from src.plugin_sdk.contracts import PLUGIN_SDK_VERSION

from .dispatcher import PluginRuntimeDispatcher
from .framing import decode_frame, encode_frame
from .logging import log_safe
from .protocol import error_response, success_response

CHANNEL_METHOD_MAP = {
    "channel.start_connect": "start_connect",
    "channel.complete_connect": "complete_connect",
    "channel.disconnect": "disconnect",
    "channel.get_status": "get_status",
    "channel.check_session": "check_session",
    "channel.publish": "publish",
    "channel.collect_metrics": "collect_metrics",
    "channel.health": "health_check",
    "channel.integrity": "integrity_check",
}

PLUGIN_ENTRY_POINT_GROUP = "social_media_manager.plugins"


class ChildPluginHost:
    def __init__(self) -> None:
        self.plugin: Any = None
        self.dispatcher: PluginRuntimeDispatcher | None = None
        self.initialized: dict[str, Any] = {}

    def run(self) -> int:
        while True:
            try:
                payload = decode_frame(sys.stdin.buffer)
                response = self.handle(payload)
            except Exception as exc:
                response = error_response(
                    None, getattr(exc, "code", "plugin_host_runtime.error"), "Plugin runtime error."
                )
                log_safe(f"child runtime error: {exc}")
            sys.stdout.buffer.write(encode_frame(response))
            sys.stdout.buffer.flush()
            if response.get("result", {}).get("status") == "shutdown":
                return 0

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("id") or "")
        method = str(payload.get("method") or "")
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        try:
            if method == "host.initialize":
                return success_response(request_id, self.initialize(params))
            if method == "plugin.activate":
                return success_response(request_id, self._dispatcher().activate())
            if method == "plugin.shutdown":
                return success_response(request_id, self._dispatcher().shutdown())
            if method == "plugin.ping":
                return success_response(request_id, {"status": "ok"})
            if method in CHANNEL_METHOD_MAP:
                return success_response(request_id, self._dispatcher().channel_call(CHANNEL_METHOD_MAP[method], params))
            return error_response(request_id, "plugin_host_runtime.method_unsupported", "Method is not supported.")
        except Exception as exc:
            log_safe(f"request failed: {exc}")
            return error_response(
                request_id, getattr(exc, "code", "plugin_host_runtime.call_failed"), "Plugin call failed."
            )

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        expected_id = str(params["expected_plugin_id"])
        expected_version = str(params["expected_plugin_version"])
        install_root = Path(os.environ["SMM_PLUGIN_INSTALL_ROOT"])
        version_root = install_root / expected_id / "installs" / expected_version
        sys.path.insert(0, str(version_root))
        src_root = version_root / "src"
        if src_root.exists():
            sys.path.insert(0, str(src_root))
        self.plugin = self._load_plugin(expected_id)
        manifest = self._manifest()
        entrypoint = str(params.get("entrypoint") or "")
        ready = {
            "protocol_version": params["protocol_version"],
            "plugin_id": manifest["id"],
            "plugin_version": manifest["version"],
            "manifest_checksum": params["manifest_checksum"],
            "entrypoint_identity": entrypoint,
            "plugin_sdk_version": PLUGIN_SDK_VERSION,
            "capabilities": manifest.get("capabilities", []),
            "requested_permissions": manifest.get("permissions", []),
            "supported_methods": ["plugin.activate", "plugin.shutdown", "plugin.ping", *CHANNEL_METHOD_MAP.keys()],
            "runtime_checksum": params.get("environment_checksum", ""),
            "warnings": [],
        }
        self.initialized = ready
        return ready

    def _load_plugin(self, plugin_id: str) -> Any:
        for dist in importlib.metadata.distributions(
            path=[
                str(
                    Path(os.environ["SMM_PLUGIN_INSTALL_ROOT"])
                    / plugin_id
                    / "installs"
                    / os.environ["SMM_PLUGIN_VERSION"]
                )
            ]
        ):
            for entry in dist.entry_points:
                if entry.group == PLUGIN_ENTRY_POINT_GROUP and entry.name == plugin_id:
                    module_name, _, attr = entry.value.partition(":")
                    module = importlib.import_module(module_name)
                    factory = getattr(module, attr)
                    return factory()
        raise RuntimeError("entrypoint missing")

    def _manifest(self) -> dict[str, Any]:
        installed = self._installed_manifest()
        if installed:
            return installed
        manifest = self.plugin.manifest
        if hasattr(manifest, "to_dict"):
            return manifest.to_dict()
        if isinstance(manifest, dict):
            return manifest
        if hasattr(manifest, "__dict__"):
            return dict(manifest.__dict__)
        return json.loads(str(manifest))

    def _installed_manifest(self) -> dict[str, Any]:
        version_root = (
            Path(os.environ["SMM_PLUGIN_INSTALL_ROOT"])
            / os.environ["SMM_PLUGIN_ID"]
            / "installs"
            / os.environ["SMM_PLUGIN_VERSION"]
        )
        manifests = sorted(version_root.rglob("*.manifest.json"))
        return json.loads(manifests[0].read_text()) if manifests else {}

    def _dispatcher(self) -> PluginRuntimeDispatcher:
        if self.dispatcher is None:
            self.dispatcher = PluginRuntimeDispatcher(self.plugin)
        return self.dispatcher


__all__ = ["ChildPluginHost"]
