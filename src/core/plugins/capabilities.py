from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PluginFamily(StrEnum):
    SOURCES = "sources"
    TRANSFORMATIONS = "transformations"
    MEDIA = "media"
    CHANNELS = "channels"
    COMMERCE = "commerce"
    PROVIDERS = "providers"
    ANALYTICS = "analytics"
    ACTIONS = "actions"
    CONTENT = "content"
    PUBLICATION = "publication"
    UNKNOWN = "unknown"


FAMILY_PREFIXES: tuple[tuple[str, PluginFamily], ...] = (
    ("source.", PluginFamily.SOURCES),
    ("entity.", PluginFamily.SOURCES),
    ("transformation.", PluginFamily.TRANSFORMATIONS),
    ("clip.", PluginFamily.TRANSFORMATIONS),
    ("asset.", PluginFamily.MEDIA),
    ("media.", PluginFamily.MEDIA),
    ("channel.", PluginFamily.CHANNELS),
    ("commerce.", PluginFamily.COMMERCE),
    ("provider.", PluginFamily.PROVIDERS),
    ("transcription.", PluginFamily.PROVIDERS),
    ("transcript.", PluginFamily.PROVIDERS),
    ("browser.", PluginFamily.PROVIDERS),
    ("analytics.", PluginFamily.ANALYTICS),
    ("outcome.", PluginFamily.ANALYTICS),
    ("action.", PluginFamily.ACTIONS),
    ("content.", PluginFamily.CONTENT),
    ("publication.", PluginFamily.PUBLICATION),
)


@dataclass(frozen=True, order=True)
class Capability:
    id: str
    description: str = ""
    accepts: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Capability id is required.")

    @property
    def family(self) -> PluginFamily:
        return family_for_capability(self.id)


def family_for_capability(capability_id: str) -> PluginFamily:
    normalized = capability_id.strip()
    for prefix, family in FAMILY_PREFIXES:
        if normalized.startswith(prefix):
            return family
    return PluginFamily.UNKNOWN


def family_label(family: PluginFamily | str) -> str:
    value = PluginFamily(family) if not isinstance(family, PluginFamily) else family
    return {
        PluginFamily.SOURCES: "Sources",
        PluginFamily.TRANSFORMATIONS: "Transformations",
        PluginFamily.MEDIA: "Media",
        PluginFamily.CHANNELS: "Channels",
        PluginFamily.COMMERCE: "Commerce",
        PluginFamily.PROVIDERS: "Providers",
        PluginFamily.ANALYTICS: "Analytics",
        PluginFamily.ACTIONS: "Actions",
        PluginFamily.CONTENT: "Content",
        PluginFamily.PUBLICATION: "Publication",
        PluginFamily.UNKNOWN: "Other",
    }[value]
