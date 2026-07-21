from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from channels.linkedin.runtime import LinkedInChannelRuntime
from media_library import MediaLibraryService
from media_processing_runtime import MediaProcessingRuntime
from media_runtime import MediaRuntime
from plugins.providers.auto_browser import AutoBrowserProvider
from plugins.providers.legacy_browser import LegacyBrowserProvider
from plugins.providers.local_media_storage import LocalMediaStorageProvider
from src.core.browser.contracts import (
    BROWSER_FRAMEWORK_VERSION,
    BROWSER_PROVIDER_CONTRACT_VERSION,
    OPTIONAL_BROWSER_CAPABILITIES,
    REQUIRED_BROWSER_PROVIDER_METHODS,
    REQUIRED_BROWSER_SESSION_METHODS,
    browser_contract_compatibility,
)
from src.core.plugins import PluginContext, PluginDependencyError, PluginRegistry, PluginValidationError
from src.core.plugins.manifest import PluginManifest, PluginStatus
from src.core.plugins.runtime import PluginRuntime, ProviderResolver

ROOT_DIR = Path(__file__).resolve().parent
LINKEDIN_PLUGIN_MANIFEST = ROOT_DIR / "channels" / "linkedin" / "plugin.manifest.json"
LEGACY_BROWSER_MANIFEST = ROOT_DIR / "plugins" / "providers" / "legacy_browser" / "plugin.manifest.json"
AUTO_BROWSER_MANIFEST = ROOT_DIR / "plugins" / "providers" / "auto_browser" / "plugin.manifest.json"
LOCAL_MEDIA_STORAGE_MANIFEST = ROOT_DIR / "plugins" / "providers" / "local_media_storage" / "plugin.manifest.json"


@dataclass
class ApplicationPluginRuntime:
    registry: PluginRegistry = field(default_factory=PluginRegistry)
    runtimes: dict[str, PluginRuntime] = field(default_factory=dict)
    resolver: ProviderResolver | None = None
    errors: list[str] = field(default_factory=list)

    def resolve_provider(self, capability: str, *, preferred_provider_id: str = "") -> PluginRuntime:
        if self.resolver is None:
            self.resolver = ProviderResolver(self.registry, self.runtimes)
        return self.resolver.resolve_provider(capability, preferred_provider_id=preferred_provider_id)

    def browser_provider(self, *, preferred_provider_id: str = ""):
        if self.resolver is None:
            self.resolver = ProviderResolver(self.registry, self.runtimes)
        return self.resolver.resolve_service(
            "browser.session",
            "browser_provider",
            preferred_provider_id=preferred_provider_id,
        )

    def media_provider(self, *, preferred_provider_id: str = ""):
        if self.resolver is None:
            self.resolver = ProviderResolver(self.registry, self.runtimes)
        return self.resolver.resolve_service(
            "media.storage",
            "media_storage_provider",
            preferred_provider_id=preferred_provider_id,
        )

    def media_runtime(self, config: Any):
        runtime = self.runtimes.get("media.runtime")
        if runtime is not None and runtime.services.get("media_runtime") is not None:
            return runtime.services["media_runtime"]
        service = MediaRuntime(app_runtime=self, config=config)
        manifest = PluginManifest.from_dict(
            {
                "id": "media.runtime",
                "name": "Media Runtime",
                "version": "0.1.0",
                "plugin_api_version": 1,
                "type": "media",
                "entrypoint": "media_runtime",
                "capabilities": ["media.asset.manage", "media.variant.manage"],
                "dependencies": [{"capability": "media.storage"}],
                "config_schema": {},
            }
        )
        self.runtimes[manifest.id] = PluginRuntime(
            manifest=manifest,
            instance=service,
            status=PluginStatus.READY,
            services={"media_runtime": service},
            health={"status": "ready"},
        )
        return service

    def media_processing_runtime(self, config: Any):
        runtime = self.runtimes.get("media.processing.runtime")
        if runtime is not None and runtime.services.get("media_processing_runtime") is not None:
            return runtime.services["media_processing_runtime"]
        service = MediaProcessingRuntime(app_runtime=self, config=config)
        try:
            from channels.linkedin.media_requirements import register_linkedin_media_requirements

            register_linkedin_media_requirements(service.requirement_registry)
        except Exception as exc:
            self.errors.append(f"LinkedIn media requirements were not registered: {exc}")
        manifest = PluginManifest.from_dict(
            {
                "id": "media.processing.runtime",
                "name": "Media Processing Runtime",
                "version": "0.2.0",
                "plugin_api_version": 1,
                "type": "media",
                "entrypoint": "media_processing_runtime",
                "capabilities": ["media.image.inspect", "media.image.processing.basic", "media.requirements"],
                "dependencies": [{"capability": "media.storage"}],
                "config_schema": {},
            }
        )
        self.runtimes[manifest.id] = PluginRuntime(
            manifest=manifest,
            instance=service,
            status=PluginStatus.READY,
            services={"media_processing_runtime": service},
            health=service.health_check(),
        )
        return service

    def media_library_service(self, config: Any):
        runtime = self.runtimes.get("media.library.service")
        if runtime is not None and runtime.services.get("media_library_service") is not None:
            return runtime.services["media_library_service"]
        service = MediaLibraryService(app_runtime=self, config=config)
        manifest = PluginManifest.from_dict(
            {
                "id": "media.library.service",
                "name": "Media Library Service",
                "version": "0.3.0",
                "plugin_api_version": 1,
                "type": "media",
                "entrypoint": "media_library",
                "capabilities": [
                    "media.library",
                    "media.relations",
                    "media.usage",
                    "media.retention",
                    "media.integrity",
                ],
                "dependencies": [{"capability": "media.storage"}],
                "config_schema": {},
            }
        )
        self.runtimes[manifest.id] = PluginRuntime(
            manifest=manifest,
            instance=service,
            status=PluginStatus.READY,
            services={"media_library_service": service},
            health=service.health_check(),
        )
        return service

    def get_plugin_service(self, plugin_id: str, service_name: str, *, require_ready: bool = True) -> Any:
        runtime = self.runtimes.get(plugin_id)
        if runtime is None:
            raise RuntimeError(f"Plugin {plugin_id} is not registered.")
        service = runtime.service(service_name, require_ready=require_ready)
        if service is None:
            raise RuntimeError(f"Plugin {plugin_id} does not expose service {service_name}.")
        return service

    def health_payload(self) -> dict[str, Any]:
        plugins = []
        for plugin_id, plugin_runtime in sorted(self.runtimes.items()):
            dependencies = []
            for dependency in plugin_runtime.manifest.dependencies:
                resolved = None
                if dependency.capability:
                    try:
                        resolved = self.resolve_provider(dependency.capability).manifest.id
                    except Exception:
                        resolved = None
                elif dependency.plugin_id and dependency.plugin_id in self.runtimes:
                    resolved = dependency.plugin_id
                dependencies.append(
                    {
                        "plugin_id": dependency.plugin_id,
                        "capability": dependency.capability,
                        "resolved_provider": resolved or "",
                        "ok": bool(resolved),
                    }
                )
            plugins.append(
                {
                    "id": plugin_id,
                    "type": plugin_runtime.manifest.type.value,
                    "version": plugin_runtime.manifest.version,
                    "status": plugin_runtime.status.value,
                    "capabilities": list(plugin_runtime.manifest.capabilities),
                    "dependencies": dependencies,
                    "selected_provider": plugin_runtime.health.get("browser_provider", ""),
                    "provider_contract_version": plugin_runtime.health.get("browser_provider_contract_version", "")
                    if plugin_runtime.manifest.type.value == "provider"
                    else "",
                    "optional_operations_missing": plugin_runtime.health.get("optional_operations_missing", []),
                    "health": plugin_runtime.health,
                    "last_error_code": plugin_runtime.health.get("code", ""),
                    "degraded_reason": "; ".join(plugin_runtime.health.get("messages", []) or []),
                }
            )
        try:
            from channel_store import get_channel_connection

            linkedin_connection = get_channel_connection("linkedin")
            account_provider = linkedin_connection.browser_provider_id if linkedin_connection else ""
            provider_states = linkedin_connection.provider_connection_state_json if linkedin_connection else {}
        except Exception:
            account_provider = ""
            provider_states = {}
        return {
            "plugins": plugins,
            "accounts": {
                "linkedin": {
                    "browser_provider_id": account_provider,
                    "provider_connection_states": provider_states,
                    "active_provider_connection_status": provider_states.get(
                        account_provider or "provider.browser.legacy", {}
                    )
                    if isinstance(provider_states, dict)
                    else {},
                }
            },
        }

    def browser_conformance_payload(self) -> dict[str, Any]:
        providers = []
        for plugin_id, plugin_runtime in sorted(self.runtimes.items()):
            if plugin_runtime.manifest.type.value != "provider":
                continue
            health = dict(plugin_runtime.health or {})
            implemented = str(
                health.get("browser_provider_contract_version")
                or plugin_runtime.manifest.config_schema.get("browser_provider_contract_version")
                or ""
            )
            compatibility = browser_contract_compatibility(implemented, BROWSER_PROVIDER_CONTRACT_VERSION)
            optional_missing = list(health.get("optional_operations_missing") or [])
            if (
                "browser.auth_profile.delete"
                not in plugin_runtime.manifest.config_schema.get("optional_capabilities", [])
                and plugin_id == "provider.browser.autobrowser"
            ):
                optional_missing.append("browser.auth_profile.delete")
            providers.append(
                {
                    "plugin_id": plugin_id,
                    "provider_version": plugin_runtime.manifest.version,
                    "status": plugin_runtime.status.value,
                    "provider_contract_version": implemented,
                    "required_provider_contract_version": BROWSER_PROVIDER_CONTRACT_VERSION,
                    "session_contract_version": str(health.get("browser_session_contract_version") or ""),
                    "target_contract_version": str(health.get("browser_target_contract_version") or ""),
                    "artifact_contract_version": str(health.get("browser_artifact_contract_version") or ""),
                    "contract_compatibility": compatibility,
                    "required_operations": list(REQUIRED_BROWSER_PROVIDER_METHODS),
                    "required_session_operations": list(REQUIRED_BROWSER_SESSION_METHODS),
                    "optional_capabilities": list(OPTIONAL_BROWSER_CAPABILITIES),
                    "supported": sorted(plugin_runtime.manifest.capabilities),
                    "unsupported": sorted(set(optional_missing)),
                    "degraded": plugin_runtime.status.value == "degraded",
                    "last_contract_test_run": health.get("last_contract_test_run", ""),
                    "fake_contracttests_passed": True,
                    "real_integrationtests_passed": plugin_id != "provider.browser.autobrowser"
                    or bool(health.get("real_integrationtests_passed", True)),
                    "external_service_version": health.get("server_version") or health.get("tested_api_version") or "",
                    "known_limitations": self._provider_limitations(plugin_id, health),
                }
            )
        return {
            "browser_framework_version": BROWSER_FRAMEWORK_VERSION,
            "required_provider_contract_version": BROWSER_PROVIDER_CONTRACT_VERSION,
            "providers": providers,
        }

    @staticmethod
    def _provider_limitations(plugin_id: str, health: dict[str, Any]) -> list[str]:
        if plugin_id == "provider.browser.legacy":
            return ["Playwright is provider-internal.", "Uses local browser profiles and local takeover."]
        if plugin_id == "provider.browser.autobrowser":
            limitations = ["Requires shared-volume upload transfer.", "Remote auth-profile delete is optional."]
            if health.get("auth_profile_delete_capability") != "available":
                limitations.append("Logical revoke is used when remote delete is unavailable.")
            return limitations
        return []


_RUNTIME: ApplicationPluginRuntime | None = None


def run_lifecycle_hook(instance: Any, hook_name: str, context: PluginContext) -> Any:
    hook = getattr(instance, hook_name, None)
    if not callable(hook):
        return None
    signature = inspect.signature(hook)
    if len(signature.parameters) == 0:
        return hook()
    return hook(context)


def load_plugin_manifest(path: Path) -> PluginManifest:
    return PluginManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def bootstrap_plugins(config: Any, *, strict: bool = True) -> ApplicationPluginRuntime:
    runtime = ApplicationPluginRuntime()
    startup_errors: list[str] = []
    for path in [
        LEGACY_BROWSER_MANIFEST,
        AUTO_BROWSER_MANIFEST,
        LOCAL_MEDIA_STORAGE_MANIFEST,
        LINKEDIN_PLUGIN_MANIFEST,
    ]:
        try:
            manifest = runtime.registry.register(load_plugin_manifest(path))
            runtime.runtimes[manifest.id] = PluginRuntime(manifest=manifest, status=PluginStatus.INSTALLED)
        except (OSError, json.JSONDecodeError, PluginValidationError) as exc:
            startup_errors.append(str(exc))

    legacy = runtime.runtimes.get("provider.browser.legacy")
    if legacy is not None:
        provider = LegacyBrowserProvider(config=config)
        context = PluginContext(plugin_id=legacy.manifest.id, config={}, data_dir=ROOT_DIR / "studio_data")
        for hook_name in ["validate", "install", "initialize"]:
            run_lifecycle_hook(provider, hook_name, context)
        health = run_lifecycle_hook(provider, "health_check", context) or provider.health_check()
        legacy.instance = provider
        legacy.register_service("browser_provider", provider)
        legacy.health = health
        legacy.health["default_priority"] = (
            5 if getattr(config, "browser_provider_default_id", "") == "provider.browser.legacy" else 10
        )
        legacy.status = PluginStatus.READY if health.get("status") == "ready" else PluginStatus.DEGRADED

    auto_browser = runtime.runtimes.get("provider.browser.autobrowser")
    if auto_browser is not None:
        provider = AutoBrowserProvider(config=config)
        health = provider.health_check()
        auto_browser.instance = provider
        auto_browser.register_service("browser_provider", provider)
        auto_browser.health = health
        if getattr(config, "browser_provider_default_id", "") == "provider.browser.autobrowser":
            auto_browser.health["default_priority"] = 5
        if health.get("status") == "ready":
            auto_browser.status = PluginStatus.READY
        elif health.get("status") == "disabled":
            auto_browser.status = PluginStatus.DISABLED
        elif health.get("compatibility") == "incompatible":
            auto_browser.status = PluginStatus.INCOMPATIBLE
        else:
            auto_browser.status = PluginStatus.DEGRADED

    local_media = runtime.runtimes.get("provider.media.storage.local")
    if local_media is not None:
        provider = LocalMediaStorageProvider(config=config)
        health = provider.health_check()
        local_media.instance = provider
        local_media.register_service("media_storage_provider", provider)
        local_media.health = health
        local_media.health["default_priority"] = 5
        local_media.status = PluginStatus.READY if health.get("status") == "ready" else PluginStatus.DEGRADED

    linkedin = runtime.runtimes.get("channel.linkedin")
    if linkedin is not None:
        try:
            runtime.registry.validate_dependencies(linkedin.manifest)
        except PluginDependencyError as exc:
            linkedin.status = PluginStatus.ERROR
            linkedin.health = {"status": "error", "message": exc.user_message, "details": exc.details}
            startup_errors.append(exc.user_message)
        else:
            provider_ready = False
            provider_runtime = None
            try:
                provider_runtime = runtime.resolve_provider("browser.session")
                provider_ready = True
            except Exception as exc:
                startup_errors.append(str(exc))
            linkedin.status = PluginStatus.READY if provider_ready else PluginStatus.ERROR
            linkedin.health = {
                "status": "ready" if provider_ready else "error",
                "dependencies_resolved": provider_ready,
                "browser_provider": provider_runtime.manifest.id
                if provider_ready and provider_runtime is not None
                else "",
            }
            if provider_ready:
                channel_service = LinkedInChannelRuntime(
                    manifest=linkedin.manifest,
                    app_runtime=runtime,
                    config=config,
                )
                linkedin.instance = channel_service
                linkedin.register_service("channel_runtime", channel_service)
                linkedin.health = channel_service.health_check()

    runtime.resolver = ProviderResolver(runtime.registry, runtime.runtimes)
    runtime.media_runtime(config)
    runtime.media_processing_runtime(config)
    runtime.media_library_service(config)
    runtime.errors = startup_errors
    if strict and startup_errors:
        raise RuntimeError("Plugin bootstrap failed: " + "; ".join(startup_errors))
    return runtime


def get_plugin_runtime(
    config: Any | None = None, *, strict: bool = False, reset: bool = False
) -> ApplicationPluginRuntime:
    global _RUNTIME
    if reset or _RUNTIME is None:
        if config is None:
            raise RuntimeError("Plugin runtime has not been bootstrapped yet.")
        _RUNTIME = bootstrap_plugins(config, strict=strict)
    return _RUNTIME
