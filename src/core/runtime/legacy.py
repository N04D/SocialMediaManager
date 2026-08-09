from __future__ import annotations

from dataclasses import dataclass

from src.core.plugins.manifest import PluginManifest

from .capabilities import CapabilityDescriptor, CapabilityMode
from .components import ComponentManifest

LEGACY_CAPABILITY_MAP: dict[str, tuple[str, str, str]] = {
    "channel.connect": (
        "account.connection.start",
        CapabilityMode.WRITE.value,
        "Start or validate an account connection.",
    ),
    "channel.disconnect": ("account.connection.disconnect", CapabilityMode.WRITE.value, "Disconnect an account."),
    "channel.status": ("account.connection.read", CapabilityMode.READ.value, "Read account connection status."),
    "channel.health": ("component.health.read", CapabilityMode.READ.value, "Read component health."),
    "channel.publish.text": ("content.text.publish", CapabilityMode.WRITE.value, "Publish text content."),
    "channel.publish.image": ("content.image.publish", CapabilityMode.WRITE.value, "Publish image content."),
    "channel.publish.video": ("content.video.publish", CapabilityMode.WRITE.value, "Publish video content."),
    "channel.publish.short_video": (
        "content.short_video.publish",
        CapabilityMode.WRITE.value,
        "Publish short video content.",
    ),
    "channel.metrics.collect": ("analytics.metrics.read", CapabilityMode.READ.value, "Collect publication metrics."),
    "publication.status.read": ("publication.status.read", CapabilityMode.READ.value, "Read publication status."),
    "source.video": ("video.read", CapabilityMode.READ.value, "Read video source metadata."),
    "source.metadata": ("metadata.read", CapabilityMode.READ.value, "Read source metadata."),
    "source.transcript": ("transcript.read", CapabilityMode.READ.value, "Read transcript data."),
    "source.transcript.import": ("transcript.import", CapabilityMode.WRITE.value, "Import transcript data."),
}


@dataclass(frozen=True)
class LegacyCapabilityAdapter:
    sdk_version: str = "runtime-contracts-0.1"

    def component_for_plugin(
        self,
        manifest: PluginManifest,
        *,
        component_id: str = "",
        provider: str = "",
        capability_overrides: dict[str, tuple[str, str, str]] | None = None,
        metadata: dict | None = None,
    ) -> ComponentManifest:
        resolved_provider = provider or manifest.id.split(".", 1)[0]
        mapping = dict(LEGACY_CAPABILITY_MAP)
        mapping.update(capability_overrides or {})
        capabilities: list[CapabilityDescriptor] = []
        for legacy_capability in manifest.capabilities:
            mapped = mapping.get(legacy_capability)
            if mapped is None:
                continue
            suffix, mode, description = mapped
            capabilities.append(
                CapabilityDescriptor(
                    capability_id=f"{resolved_provider}.{suffix}",
                    version=manifest.version,
                    mode=mode,
                    description=f"Legacy {manifest.id}: {description}",
                )
            )
        return ComponentManifest(
            component_id=component_id or manifest.id.replace("channel.", "").replace("source.", "") + "-legacy",
            provider=resolved_provider,
            version=manifest.version,
            sdk_version=self.sdk_version,
            capabilities=tuple(capabilities),
            required_secrets=tuple(
                str(name)
                for name, schema in manifest.config_schema.items()
                if isinstance(schema, dict) and str(schema.get("type")) == "secret_ref"
            ),
            config_schema=manifest.config_schema,
            metadata={"legacy_plugin_id": manifest.id, **dict(metadata or {})},
        )
