from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MastodonInstanceSnapshot:
    id: str
    origin: str
    server_version: str = ""
    api_version: str = ""
    software_status: str = "unreachable"
    discovered_at: str = ""
    expires_at: str = ""
    max_characters: int = 500
    max_media_attachments: int = 4
    characters_reserved_per_url: int = 23
    supported_mime_types: list[str] = field(default_factory=lambda: ["image/jpeg", "image/png"])
    image_size_limit: int = 8_000_000
    image_matrix_limit: int = 16_777_216
    media_description_limit: int = 1500
    oauth_pkce_supported: bool = True
    media_v2_supported: bool = True
    media_delete_supported: bool = False
    quotes_count_supported: bool = False
    rate_limit_metadata_supported: bool = False
    capability_checksum: str = ""
    safe_warnings: list[str] = field(default_factory=list)


@dataclass
class MastodonRequirementsSnapshot:
    id: str
    channel_account_id: str
    instance_origin: str
    instance_snapshot_id: str
    capability_checksum: str
    content_length_limit: int
    characters_reserved_per_url: int
    maximum_media_count: int
    supported_mime_types: list[str]
    maximum_image_bytes: int
    maximum_image_pixels: int
    description_limit: int
    discovered_at: str
    expires_at: str
    plugin_version: str = "0.1.0"
    checksum: str = ""


@dataclass
class MastodonAccountState:
    channel_account_id: str
    workspace_id: str
    instance_origin: str
    instance_host: str
    remote_account_id: str = ""
    acct: str = ""
    username: str = ""
    display_name: str = ""
    profile_url: str = ""
    connection_status: str = "oauth_required"
    scope_set: list[str] = field(default_factory=list)
    connected_at: str = ""
    last_verified_at: str = ""
    instance_snapshot_id: str = ""
    requirements_snapshot_id: str = ""
    safe_error_code: str = ""
    token_secret_ref: str = ""
    token_secret_version: int = 0
    revoked_local: bool = False
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MastodonAppRegistration:
    id: str
    instance_origin: str
    redirect_uri: str
    scopes: list[str]
    application_name: str
    client_id_secret_ref: str
    client_secret_ref: str
    created_at: str
    last_verified_at: str = ""


@dataclass
class MastodonOAuthFlowState:
    id: str
    workspace_id: str
    channel_account_id: str
    instance_origin: str
    redirect_uri: str
    scope_set: list[str]
    state_secret_ref: str
    verifier_secret_ref: str
    challenge: str
    app_registration_id: str
    created_at: str
    expires_at: str
    consumed_at: str = ""


@dataclass
class MastodonPublicationOptions:
    visibility: str = "public"
    language: str = ""
    spoiler_text: str = ""
    sensitive: bool = False


@dataclass
class MastodonRemoteMediaUpload:
    attachment_id: str
    account_id: str
    publication_target_id: str
    execution_attempt_id: str
    uploaded_at: str
    processing_status: str = "uploaded_pending"
    attached_status_id: str = ""
    cleanup_status: str = "cleanup_pending"
    ownership_status: str = "owned_by_execution"
    metadata: dict[str, Any] = field(default_factory=dict)
