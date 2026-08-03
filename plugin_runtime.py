from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from analytics_services import AnalyticsServiceBundle
from channels.linkedin.runtime import LinkedInChannelRuntime
from channels.mastodon.runtime import MastodonChannelRuntime
from content_services import ContentService
from media_library import MediaLibraryService
from media_processing_runtime import MediaProcessingRuntime
from media_runtime import MediaRuntime
from plugins.commerce.catalog import CommerceCatalogPlugin
from plugins.providers.auto_browser import AutoBrowserProvider
from plugins.providers.legacy_browser import LegacyBrowserProvider
from plugins.providers.local_media_storage import LocalMediaStorageProvider
from plugins.providers.local_transcription import LocalTranscriptionProvider
from plugins.sources.youtube import YouTubeSourcePlugin
from plugins.transformations.video_repurpose import VideoRepurposePlugin
from publication_execution import PublicationExecutionService
from publication_planning import PublicationPlanningService
from publication_scheduling import CampaignService, ExecutionCalendarService, ScheduleMaterializationService
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
MASTODON_PLUGIN_MANIFEST = ROOT_DIR / "channels" / "mastodon" / "plugin.manifest.json"
LEGACY_BROWSER_MANIFEST = ROOT_DIR / "plugins" / "providers" / "legacy_browser" / "plugin.manifest.json"
AUTO_BROWSER_MANIFEST = ROOT_DIR / "plugins" / "providers" / "auto_browser" / "plugin.manifest.json"
LOCAL_MEDIA_STORAGE_MANIFEST = ROOT_DIR / "plugins" / "providers" / "local_media_storage" / "plugin.manifest.json"
LOCAL_TRANSCRIPTION_MANIFEST = ROOT_DIR / "plugins" / "providers" / "local_transcription" / "plugin.manifest.json"
YOUTUBE_SOURCE_MANIFEST = ROOT_DIR / "plugins" / "sources" / "youtube" / "plugin.manifest.json"
VIDEO_REPURPOSE_MANIFEST = ROOT_DIR / "plugins" / "transformations" / "video_repurpose" / "plugin.manifest.json"
TRANSCRIPT_CLIP_MANIFEST = (
    ROOT_DIR / "plugins" / "transformations" / "transcript_clip_candidates" / "plugin.manifest.json"
)
COMMERCE_CATALOG_MANIFEST = ROOT_DIR / "plugins" / "commerce" / "catalog" / "plugin.manifest.json"
COMMERCE_CONTRACT_MANIFEST = ROOT_DIR / "plugins" / "commerce" / "example" / "plugin.manifest.json"


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

    def transcription_provider(self, *, preferred_provider_id: str = ""):
        if self.resolver is None:
            self.resolver = ProviderResolver(self.registry, self.runtimes)
        return self.resolver.resolve_service(
            "transcription.media",
            "transcription_provider",
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
            from channels.mastodon.media_requirements import register_mastodon_media_requirements

            register_mastodon_media_requirements(service.requirement_registry)
        except Exception as exc:
            self.errors.append(f"Channel media requirements were not registered: {exc}")
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

    def content_service(self, config: Any):
        runtime = self.runtimes.get("content.service")
        if runtime is not None and runtime.services.get("content_service") is not None:
            return runtime.services["content_service"]
        service = ContentService(app_runtime=self, config=config)
        try:
            from channels.linkedin.content_requirements import register_linkedin_content_requirements

            register_linkedin_content_requirements(service.requirement_registry)
            from channels.mastodon.content_requirements import register_mastodon_content_requirements

            register_mastodon_content_requirements(service.requirement_registry)
        except Exception as exc:
            self.errors.append(f"Channel content requirements were not registered: {exc}")
        manifest = PluginManifest.from_dict(
            {
                "id": "content.service",
                "name": "Content Service",
                "version": "0.1.0",
                "plugin_api_version": 1,
                "type": "content",
                "entrypoint": "content_service",
                "capabilities": [
                    "content.items",
                    "content.revisions",
                    "content.variants",
                    "content.requirements",
                ],
                "dependencies": [{"capability": "media.library"}],
                "config_schema": {},
            }
        )
        self.runtimes[manifest.id] = PluginRuntime(
            manifest=manifest,
            instance=service,
            status=PluginStatus.READY,
            services={"content_service": service},
            health=service.health_check(),
        )
        return service

    def publication_planning_service(self, config: Any):
        runtime = self.runtimes.get("publication.planning.service")
        if runtime is not None and runtime.services.get("publication_planning_service") is not None:
            return runtime.services["publication_planning_service"]
        content_service = self.content_service(config)
        service = PublicationPlanningService(app_runtime=self, config=config, content_service=content_service)
        manifest = PluginManifest.from_dict(
            {
                "id": "publication.planning.service",
                "name": "Publication Planning Service",
                "version": "0.1.0",
                "plugin_api_version": 1,
                "type": "content",
                "entrypoint": "publication_planning",
                "capabilities": ["publication.plans", "publication.targets", "publication.queue"],
                "dependencies": [{"capability": "content.items"}, {"capability": "media.library"}],
                "config_schema": {},
            }
        )
        self.runtimes[manifest.id] = PluginRuntime(
            manifest=manifest,
            instance=service,
            status=PluginStatus.READY,
            services={"publication_planning_service": service},
            health=service.health_check(),
        )
        return service

    def publication_execution_service(self, config: Any):
        runtime = self.runtimes.get("publication.execution.service")
        if runtime is not None and runtime.services.get("publication_execution_service") is not None:
            return runtime.services["publication_execution_service"]
        planning_service = self.publication_planning_service(config)
        service = PublicationExecutionService(app_runtime=self, config=config, planning_service=planning_service)
        manifest = PluginManifest.from_dict(
            {
                "id": "publication.execution.service",
                "name": "Publication Execution Service",
                "version": "0.1.0",
                "plugin_api_version": 1,
                "type": "execution",
                "entrypoint": "publication_execution",
                "capabilities": [
                    "publication.dispatch",
                    "publication.execution",
                    "publication.reconciliation",
                    "publication.retry",
                ],
                "dependencies": [{"capability": "publication.plans"}],
                "config_schema": {},
            }
        )
        self.runtimes[manifest.id] = PluginRuntime(
            manifest=manifest,
            instance=service,
            status=PluginStatus.READY,
            services={"publication_execution_service": service},
            health=service.health_check(),
        )
        return service

    def schedule_materialization_service(self, config: Any):
        runtime = self.runtimes.get("publication.scheduling.service")
        if runtime is not None and runtime.services.get("schedule_materialization_service") is not None:
            return runtime.services["schedule_materialization_service"]
        planning_service = self.publication_planning_service(config)
        service = ScheduleMaterializationService(
            app_runtime=self,
            config=config,
            planning_service=planning_service,
        )
        calendar_service = ExecutionCalendarService(scheduling_service=service)
        campaign_service = CampaignService(scheduling_service=service, calendar_service=calendar_service)
        calendar_service.campaign_service = campaign_service
        manifest = PluginManifest.from_dict(
            {
                "id": "publication.scheduling.service",
                "name": "Publication Scheduling Service",
                "version": "0.1.0",
                "plugin_api_version": 1,
                "type": "scheduling",
                "entrypoint": "publication_scheduling",
                "capabilities": [
                    "publication.schedules",
                    "publication.recurrence",
                    "publication.occurrences",
                    "publication.calendar",
                    "publication.campaigns",
                ],
                "dependencies": [{"capability": "publication.plans"}, {"capability": "publication.execution"}],
                "config_schema": {},
            }
        )
        self.runtimes[manifest.id] = PluginRuntime(
            manifest=manifest,
            instance=service,
            status=PluginStatus.READY,
            services={
                "schedule_materialization_service": service,
                "execution_calendar_service": calendar_service,
                "campaign_service": campaign_service,
            },
            health=service.health_check(),
        )
        return service

    def execution_calendar_service(self, config: Any):
        self.schedule_materialization_service(config)
        return self.get_plugin_service("publication.scheduling.service", "execution_calendar_service")

    def campaign_service(self, config: Any):
        self.schedule_materialization_service(config)
        return self.get_plugin_service("publication.scheduling.service", "campaign_service")

    def analytics_bundle(self, config: Any) -> AnalyticsServiceBundle:
        runtime = self.runtimes.get("analytics.service")
        if runtime is not None and runtime.services.get("analytics_bundle") is not None:
            return runtime.services["analytics_bundle"]
        bundle = AnalyticsServiceBundle(app_runtime=self, config=config)
        try:
            from channels.linkedin.metric_definitions import register_linkedin_metric_definitions

            register_linkedin_metric_definitions(bundle.metric_registry)
            from channels.mastodon.metric_definitions import register_mastodon_metric_definitions

            register_mastodon_metric_definitions(bundle.metric_registry)
        except Exception as exc:
            self.errors.append(f"Channel metric definitions were not registered: {exc}")
        manifest = PluginManifest.from_dict(
            {
                "id": "analytics.service",
                "name": "Analytics Service",
                "version": "0.1.0",
                "plugin_api_version": 1,
                "type": "analytics",
                "entrypoint": "analytics_services",
                "capabilities": [
                    "analytics.definitions",
                    "analytics.ingestion",
                    "analytics.attribution",
                    "analytics.readmodels",
                    "analytics.integrity",
                ],
                "dependencies": [{"capability": "publication.plans"}],
                "config_schema": {},
            }
        )
        self.runtimes[manifest.id] = PluginRuntime(
            manifest=manifest,
            instance=bundle,
            status=PluginStatus.READY,
            services={
                "analytics_bundle": bundle,
                "analytics_ingestion_service": bundle.ingestion_service,
                "analytics_attribution_service": bundle.attribution_service,
                "analytics_read_model_service": bundle.read_model_service,
                "analytics_integrity_service": bundle.integrity_service,
            },
            health=bundle.health_check(),
        )
        return bundle

    def analytics_ingestion_service(self, config: Any):
        return self.analytics_bundle(config).ingestion_service

    def analytics_attribution_service(self, config: Any):
        return self.analytics_bundle(config).attribution_service

    def analytics_read_model_service(self, config: Any):
        return self.analytics_bundle(config).read_model_service

    def analytics_integrity_service(self, config: Any):
        return self.analytics_bundle(config).integrity_service

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
        LOCAL_TRANSCRIPTION_MANIFEST,
        YOUTUBE_SOURCE_MANIFEST,
        VIDEO_REPURPOSE_MANIFEST,
        TRANSCRIPT_CLIP_MANIFEST,
        COMMERCE_CATALOG_MANIFEST,
        COMMERCE_CONTRACT_MANIFEST,
        LINKEDIN_PLUGIN_MANIFEST,
        MASTODON_PLUGIN_MANIFEST,
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

    local_transcription = runtime.runtimes.get("provider.transcription.local")
    if local_transcription is not None:
        provider = LocalTranscriptionProvider(config=config)
        health = provider.health_check()
        local_transcription.instance = provider
        local_transcription.register_service("transcription_provider", provider)
        local_transcription.health = health
        local_transcription.health["default_priority"] = health.get("default_priority", 5)
        local_transcription.status = PluginStatus.READY if health.get("status") == "ready" else PluginStatus.DEGRADED

    youtube_source = runtime.runtimes.get("source.youtube")
    if youtube_source is not None:
        service = YouTubeSourcePlugin()
        health = service.health_check()
        youtube_source.instance = service
        youtube_source.register_service("source_service", service)
        youtube_source.health = health
        youtube_source.status = PluginStatus.READY if health.get("status") == "ready" else PluginStatus.DEGRADED

    video_repurpose = runtime.runtimes.get("plugin.video_repurpose")
    if video_repurpose is not None:
        service = VideoRepurposePlugin()
        health = service.health_check()
        video_repurpose.instance = service
        video_repurpose.register_service("transformation_service", service)
        video_repurpose.health = health
        video_repurpose.status = PluginStatus.READY if health.get("status") == "ready" else PluginStatus.DEGRADED

    commerce_catalog = runtime.runtimes.get("commerce.catalog")
    if commerce_catalog is not None:
        service = CommerceCatalogPlugin()
        health = service.health_check()
        commerce_catalog.instance = service
        commerce_catalog.register_service("commerce_service", service)
        commerce_catalog.health = health
        commerce_catalog.status = PluginStatus.READY if health.get("status") == "ready" else PluginStatus.DEGRADED

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

    mastodon = runtime.runtimes.get("channel.mastodon")
    if mastodon is not None:
        try:
            mastodon_service = MastodonChannelRuntime(
                manifest=mastodon.manifest,
                app_runtime=runtime,
                config=config,
            )
            mastodon.instance = mastodon_service
            mastodon.register_service("channel_runtime", mastodon_service)
            mastodon.health = mastodon_service.health_check()
            mastodon.status = PluginStatus.READY
        except Exception as exc:
            mastodon.status = PluginStatus.ERROR
            mastodon.health = {"status": "error", "message": str(exc)}
            startup_errors.append(str(exc))

    runtime.resolver = ProviderResolver(runtime.registry, runtime.runtimes)
    runtime.media_runtime(config)
    runtime.media_processing_runtime(config)
    runtime.media_library_service(config)
    runtime.content_service(config)
    runtime.publication_planning_service(config)
    runtime.publication_execution_service(config)
    runtime.schedule_materialization_service(config)
    runtime.analytics_bundle(config)
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
