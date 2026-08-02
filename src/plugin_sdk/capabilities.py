"""Public capability and permission registry for Plugin SDK v1."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .contracts import PLUGIN_SDK_VERSION
from .errors import PluginManifestValidationError

CORE_CAPABILITIES = {
    "channel.connect",
    "channel.disconnect",
    "channel.status",
    "channel.publish.text",
    "channel.publish.image",
    "channel.metrics.collect",
    "channel.health",
    "browser.session",
    "browser.auth_profile",
    "browser.navigation",
    "browser.interaction",
    "browser.human_takeover",
    "media.storage",
    "media.library",
    "media.relations",
    "media.usage",
    "media.retention",
    "media.integrity",
    "media.image.inspect",
    "media.image.processing.basic",
    "media.requirements",
    "content.items",
    "content.revisions",
    "content.variants",
    "content.requirements",
    "publication.plans",
    "publication.targets",
    "publication.queue",
    "publication.execution",
    "publication.dispatch",
    "publication.reconciliation",
    "analytics.definitions",
    "analytics.ingestion",
    "analytics.attribution",
    "analytics.readmodels",
    "analytics.integrity",
    "source.written",
    "source.youtube",
    "source.video",
    "source.transcript",
    "source.transcript.import",
    "source.metadata",
    "timeline.transcript",
    "canonical.text",
    "entity.product",
    "entity.collection",
    "entity.release",
    "asset.video",
    "asset.transcript",
    "asset.transcript.timeline",
    "asset.clip_candidate",
    "asset.short_video",
    "asset.image",
    "asset.storage",
    "transformation.clip_candidates",
    "transformation.transcript.clip_candidates",
    "transformation.accepts.asset.video",
    "transformation.accepts.timeline.transcript",
    "transformation.accepts.canonical.text",
    "transformation.accepts.asset.transcript",
    "transformation.accepts.asset.transcript.timeline",
    "transformation.accepts.asset.image",
    "transformation.accepts.variant.social_text",
    "transformation.produces.transformation.clip_candidates",
    "transformation.produces.asset.clip_candidate",
    "transformation.produces.asset.short_video",
    "transformation.produces.asset.image",
    "transformation.produces.variant.social_text",
    "transformation.produces.variant.article",
    "transformation.image.basic",
    "variant.social_text",
    "variant.article",
    "variant.commercial_cta",
    "action.publish",
    "channel.linkedin",
    "channel.mastodon",
    "channel.markdown_website",
    "provider.media.storage",
    "commerce.product_catalog",
    "commerce.product_lookup",
    "commerce.product_media",
    "outcome.social_metrics",
    "outcome.video_view",
    "outcome.social_view",
    "outcome.product_click",
    "outcome.purchase",
    "outcome.sale",
    "outcome.revenue",
}

RESERVED_FUTURE_CHANNEL_CAPABILITIES = {
    "channel.publish.video",
    "channel.publish.article",
    "channel.publish.poll",
    "channel.publish.reply",
    "channel.delete.publication",
    "channel.update.publication",
    "channel.messages",
}

CORE_PERMISSIONS = {
    "outbound_network",
    "browser_session",
    "secret_storage",
    "media_read",
    "media_materialization",
    "analytics_ingestion",
    "execution_reporting",
    "account_configuration",
}

PLUGIN_ID_PATTERN = re.compile(r"^(channel|provider|media|source|commerce|plugin)\.[a-z0-9][a-z0-9_.-]{1,80}$")
CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9_-]*)+$")


@dataclass(frozen=True)
class CapabilityDefinition:
    """Machine-readable capability metadata."""

    name: str
    owner_type: str
    description: str
    stability: str = "stable"
    introduced_in: str = PLUGIN_SDK_VERSION
    deprecated_since: str = ""
    replacement: str = ""


def validate_plugin_id(plugin_id: str) -> None:
    """Validate the SDK v1 namespaced plugin ID policy."""

    if not PLUGIN_ID_PATTERN.match(plugin_id):
        raise PluginManifestValidationError(
            "plugin_manifest.invalid_id",
            "Plugin id must be namespaced, lowercase ASCII, and start with channel/provider/media/source/commerce/plugin.",
            {"plugin_id": plugin_id},
        )
    if "/" in plugin_id or "\\" in plugin_id or ".." in plugin_id:
        raise PluginManifestValidationError(
            "plugin_manifest.invalid_id_path",
            "Plugin id must not contain path separators or traversal.",
            {"plugin_id": plugin_id},
        )


def validate_capability(capability: str, *, plugin_id: str = "") -> None:
    """Validate a core or plugin-namespaced capability."""

    if not CAPABILITY_PATTERN.match(capability):
        raise PluginManifestValidationError(
            "plugin_manifest.invalid_capability",
            "Capability name is invalid.",
            {"capability": capability},
        )
    if capability in CORE_CAPABILITIES:
        return
    if plugin_id and capability.startswith(f"{plugin_id}."):
        return
    raise PluginManifestValidationError(
        "plugin_manifest.unknown_capability",
        "Unknown capabilities must be namespaced under the plugin id.",
        {"plugin_id": plugin_id, "capability": capability},
    )


def validate_permission(permission: str) -> None:
    """Validate high-level declared plugin permissions."""

    if permission not in CORE_PERMISSIONS:
        raise PluginManifestValidationError(
            "plugin_manifest.unknown_permission",
            "Unknown plugin permission.",
            {"permission": permission},
        )


def capability_catalog() -> list[CapabilityDefinition]:
    """Return stable capability metadata for documentation and reports."""

    return [
        CapabilityDefinition(name=item, owner_type=item.split(".", maxsplit=1)[0], description=f"{item} capability")
        for item in sorted(CORE_CAPABILITIES)
    ]


__all__ = [
    "CORE_CAPABILITIES",
    "CORE_PERMISSIONS",
    "RESERVED_FUTURE_CHANNEL_CAPABILITIES",
    "CapabilityDefinition",
    "capability_catalog",
    "validate_capability",
    "validate_permission",
    "validate_plugin_id",
]
