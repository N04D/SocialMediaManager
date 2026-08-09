from __future__ import annotations

from publication_calendar_runtime_handlers import (
    CALENDAR_EVENT_READ_INPUT_SCHEMA,
    CALENDAR_EVENT_READ_OUTPUT_SCHEMA,
)
from publication_git_runtime_handlers import (
    GIT_REPOSITORY_STATUS_READ_INPUT_SCHEMA,
    GIT_REPOSITORY_STATUS_READ_OUTPUT_SCHEMA,
)
from src.core.runtime.capabilities import CapabilityDescriptor, CapabilityMode
from src.core.runtime.components import ComponentManifest
from src.core.runtime.installs import ComponentBinding, Install
from src.core.runtime.resolver import RuntimeRegistry

RUNTIME_SDK_VERSION = "runtime-contracts-0.1"


def phase41_component_manifests() -> tuple[ComponentManifest, ...]:
    return (
        ComponentManifest(
            component_id="linkedin-browser-channel",
            provider="linkedin",
            version="0.1.0",
            sdk_version=RUNTIME_SDK_VERSION,
            capabilities=(
                CapabilityDescriptor("linkedin.connection.start", "0.1.0", CapabilityMode.WRITE.value),
                CapabilityDescriptor("linkedin.connection.read", "0.1.0", CapabilityMode.READ.value),
                CapabilityDescriptor("linkedin.post.create", "0.1.0", CapabilityMode.WRITE.value),
                CapabilityDescriptor("linkedin.post.read", "0.1.0", CapabilityMode.READ.value),
                CapabilityDescriptor("linkedin.analytics.read", "0.1.0", CapabilityMode.READ.value),
            ),
            required_secrets=("linkedin-session-profile-ref",),
            metadata={"legacy_plugin_id": "channel.linkedin", "transport": "browser"},
        ),
        ComponentManifest(
            component_id="youtube-source-import",
            provider="youtube",
            version="0.1.0",
            sdk_version=RUNTIME_SDK_VERSION,
            capabilities=(
                CapabilityDescriptor("youtube.video.read", "0.1.0", CapabilityMode.READ.value),
                CapabilityDescriptor("youtube.transcript.read", "0.1.0", CapabilityMode.READ.value),
                CapabilityDescriptor("youtube.transcript.import", "0.1.0", CapabilityMode.WRITE.value),
            ),
            metadata={"legacy_plugin_id": "source.youtube", "transport": "local_import"},
        ),
        ComponentManifest(
            component_id="youtube-upload-channel",
            provider="youtube",
            version="0.1.0",
            sdk_version=RUNTIME_SDK_VERSION,
            capabilities=(
                CapabilityDescriptor("youtube.connection.start", "0.1.0", CapabilityMode.WRITE.value),
                CapabilityDescriptor("youtube.connection.read", "0.1.0", CapabilityMode.READ.value),
                CapabilityDescriptor("youtube.video.publish", "0.1.0", CapabilityMode.WRITE.value),
                CapabilityDescriptor("youtube.short.publish", "0.1.0", CapabilityMode.WRITE.value),
                CapabilityDescriptor("youtube.publication.status.read", "0.1.0", CapabilityMode.READ.value),
            ),
            required_secrets=("youtube-client-secret-ref", "youtube-refresh-token-ref"),
            metadata={"legacy_plugin_id": "channel.youtube", "transport": "youtube_api"},
        ),
        ComponentManifest(
            component_id="github-markdown-website",
            provider="github",
            version="0.1.0",
            sdk_version=RUNTIME_SDK_VERSION,
            capabilities=(
                CapabilityDescriptor("github.file.write", "0.1.0", CapabilityMode.WRITE.value),
                CapabilityDescriptor("github.file.read", "0.1.0", CapabilityMode.READ.value),
                CapabilityDescriptor(
                    "git.repository.status.read",
                    "0.1.0",
                    CapabilityMode.READ.value,
                    input_schema=GIT_REPOSITORY_STATUS_READ_INPUT_SCHEMA,
                    output_schema=GIT_REPOSITORY_STATUS_READ_OUTPUT_SCHEMA,
                    description="Read local Git repository branch, HEAD, and worktree status.",
                ),
                CapabilityDescriptor("website.article.publish", "0.1.0", CapabilityMode.WRITE.value),
                CapabilityDescriptor("website.publication.verify", "0.1.0", CapabilityMode.READ.value),
                CapabilityDescriptor("website.analytics.read", "0.1.0", CapabilityMode.READ.value),
            ),
            metadata={"legacy_plugin_id": "channel.markdown_website", "transport": "git_worktree"},
        ),
        ComponentManifest(
            component_id="publication-calendar-local",
            provider="calendar",
            version="0.1.0",
            sdk_version=RUNTIME_SDK_VERSION,
            capabilities=(
                CapabilityDescriptor(
                    "calendar.event.read",
                    "0.1.0",
                    CapabilityMode.READ.value,
                    input_schema=CALENDAR_EVENT_READ_INPUT_SCHEMA,
                    output_schema=CALENDAR_EVENT_READ_OUTPUT_SCHEMA,
                    description="Read local publication calendar entries from ExecutionCalendarService.",
                ),
                CapabilityDescriptor("calendar.event.create", "0.1.0", CapabilityMode.WRITE.value),
                CapabilityDescriptor("calendar.event.update", "0.1.0", CapabilityMode.WRITE.value),
            ),
            metadata={"legacy_plugin_id": "publication.scheduling.service", "transport": "local_json_store"},
        ),
    )


def phase41_sample_installs() -> tuple[Install, ...]:
    return (
        Install(
            install_id="linkedin-don-personal",
            workspace_id="local",
            provider="linkedin",
            account_ref="linkedin",
            component_bindings={
                "linkedin.connection.start": ComponentBinding("linkedin-browser-channel"),
                "linkedin.connection.read": ComponentBinding("linkedin-browser-channel"),
                "linkedin.post.create": ComponentBinding("linkedin-browser-channel"),
                "linkedin.post.read": ComponentBinding("linkedin-browser-channel"),
                "linkedin.analytics.read": ComponentBinding("linkedin-browser-channel"),
            },
            config={"channel_id": "linkedin", "browser_profile_ref": "linkedin-session-profile-ref"},
            secret_refs=("linkedin-session-profile-ref",),
        ),
        Install(
            install_id="youtube-don-main-channel",
            workspace_id="local",
            provider="youtube",
            account_ref="youtube",
            component_bindings={
                "youtube.connection.start": ComponentBinding("youtube-upload-channel"),
                "youtube.connection.read": ComponentBinding("youtube-upload-channel"),
                "youtube.video.publish": ComponentBinding("youtube-upload-channel"),
                "youtube.short.publish": ComponentBinding("youtube-upload-channel"),
                "youtube.publication.status.read": ComponentBinding("youtube-upload-channel"),
                "youtube.video.read": ComponentBinding("youtube-source-import"),
                "youtube.transcript.read": ComponentBinding("youtube-source-import"),
                "youtube.transcript.import": ComponentBinding("youtube-source-import"),
            },
            config={
                "channel_account_id": "youtube",
                "client_id_ref": "youtube-client-id",
                "client_secret_ref": "youtube-client-secret-ref",
            },
            secret_refs=("youtube-client-secret-ref", "youtube-refresh-token-ref"),
        ),
        Install(
            install_id="github-don-website",
            workspace_id="local",
            provider="github",
            account_ref="markdown_website",
            component_bindings={
                "github.file.write": ComponentBinding("github-markdown-website"),
                "github.file.read": ComponentBinding("github-markdown-website"),
                "git.repository.status.read": ComponentBinding("github-markdown-website"),
                "website.article.publish": ComponentBinding("github-markdown-website"),
                "website.publication.verify": ComponentBinding("github-markdown-website"),
                "website.analytics.read": ComponentBinding("github-markdown-website"),
            },
            config={"repository_reference_id": "configured-in-channel-account"},
            secret_refs=(),
        ),
        Install(
            install_id="calendar-publication-local",
            workspace_id="local",
            provider="calendar",
            account_ref="publication_calendar",
            component_bindings={
                "calendar.event.read": ComponentBinding("publication-calendar-local"),
                "calendar.event.create": ComponentBinding("publication-calendar-local"),
                "calendar.event.update": ComponentBinding("publication-calendar-local"),
            },
            config={"storage": "studio_data/publication_*.json"},
            secret_refs=(),
        ),
    )


def phase41_runtime_registry() -> RuntimeRegistry:
    registry = RuntimeRegistry()
    for manifest in phase41_component_manifests():
        registry.register_component(manifest)
    for install in phase41_sample_installs():
        registry.register_install(install)
    return registry
