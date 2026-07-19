from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from channels.linkedin.runtime import LinkedInChannelRuntime
from plugins.providers.legacy_browser import LegacyBrowserProvider
from src.core.plugins import PluginContext, PluginDependencyError, PluginRegistry, PluginValidationError
from src.core.plugins.manifest import PluginManifest, PluginStatus
from src.core.plugins.runtime import PluginRuntime, ProviderResolver

ROOT_DIR = Path(__file__).resolve().parent
LINKEDIN_PLUGIN_MANIFEST = ROOT_DIR / "channels" / "linkedin" / "plugin.manifest.json"
LEGACY_BROWSER_MANIFEST = ROOT_DIR / "plugins" / "providers" / "legacy_browser" / "plugin.manifest.json"


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
                    "health": plugin_runtime.health,
                    "last_error_code": plugin_runtime.health.get("code", ""),
                    "degraded_reason": "; ".join(plugin_runtime.health.get("messages", []) or []),
                }
            )
        return {"plugins": plugins}


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
    for path in [LEGACY_BROWSER_MANIFEST, LINKEDIN_PLUGIN_MANIFEST]:
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
        legacy.status = PluginStatus.READY if health.get("status") == "ready" else PluginStatus.DEGRADED

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
            try:
                runtime.resolve_provider("browser.session")
                provider_ready = True
            except Exception as exc:
                startup_errors.append(str(exc))
            linkedin.status = PluginStatus.READY if provider_ready else PluginStatus.ERROR
            linkedin.health = {
                "status": "ready" if provider_ready else "error",
                "dependencies_resolved": provider_ready,
                "browser_provider": "provider.browser.legacy" if provider_ready else "",
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
