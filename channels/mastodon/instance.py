from __future__ import annotations

import hashlib
import ipaddress
import socket
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse, urlunparse

from .errors import (
    MastodonInstanceIncompatibleError,
    MastodonInstanceUnreachableError,
    MastodonResponseValidationError,
    MastodonUnsafeInstanceError,
)
from .models import MastodonInstanceSnapshot, MastodonRequirementsSnapshot
from .storage import canonical_json

APP_MAX_IMAGES = 4
APP_SUPPORTED_MIME_TYPES = {"image/jpeg", "image/png"}
DEFAULT_SCOPES = ["profile", "read:statuses", "write:statuses", "write:media"]


def normalize_instance_origin(
    value: str,
    *,
    allow_localhost_http: bool = False,
    allowlist: list[str] | None = None,
    resolver: Any = None,
) -> str:
    raw = str(value or "").strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"https", "http"}:
        raise MastodonUnsafeInstanceError(
            "mastodon.instance.invalid_scheme", "Only HTTP(S) Mastodon origins are supported."
        )
    if parsed.username or parsed.password:
        raise MastodonUnsafeInstanceError("mastodon.instance.userinfo", "Instance URL must not include credentials.")
    if parsed.query:
        raise MastodonUnsafeInstanceError("mastodon.instance.query", "Instance URL must not include a query string.")
    if parsed.fragment:
        raise MastodonUnsafeInstanceError("mastodon.instance.fragment", "Instance URL must not include a fragment.")
    if parsed.path not in {"", "/"}:
        raise MastodonUnsafeInstanceError("mastodon.instance.path", "Instance URL must be an origin without a path.")
    if not parsed.hostname:
        raise MastodonUnsafeInstanceError("mastodon.instance.host_missing", "Instance host is required.")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    port = parsed.port
    scheme = parsed.scheme.lower()
    if scheme == "http" and not (allow_localhost_http and _is_localhost_name(host)):
        raise MastodonUnsafeInstanceError(
            "mastodon.instance.http_forbidden", "HTTP is only allowed for local fixtures."
        )
    netloc = host
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    origin = urlunparse((scheme, netloc, "", "", "", ""))
    if allowlist and origin not in set(allowlist):
        raise MastodonUnsafeInstanceError(
            "mastodon.instance.not_allowlisted", "Instance origin is not in the allowlist."
        )
    validate_origin_network(origin, allow_localhost_http=allow_localhost_http, resolver=resolver)
    return origin


def validate_origin_network(origin: str, *, allow_localhost_http: bool = False, resolver: Any = None) -> None:
    parsed = urlparse(origin)
    host = parsed.hostname or ""
    if _is_localhost_name(host) and allow_localhost_http:
        return
    addresses = resolve_host_addresses(host, resolver=resolver)
    if not addresses:
        raise MastodonInstanceUnreachableError("mastodon.instance.dns_failed", "Instance host could not be resolved.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if _blocked_ip(ip):
            raise MastodonUnsafeInstanceError(
                "mastodon.instance.blocked_address", "Instance resolves to a blocked network."
            )


def resolve_host_addresses(host: str, *, resolver: Any = None) -> list[str]:
    if resolver is not None:
        return [str(item) for item in resolver(host)]
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    return sorted({str(item[4][0]) for item in infos})


def validate_redirect_origin(
    source_origin: str,
    target_url: str,
    *,
    allow_localhost_http: bool = False,
    resolver: Any = None,
) -> str:
    target = normalize_instance_origin(target_url, allow_localhost_http=allow_localhost_http, resolver=resolver)
    if target != source_origin:
        raise MastodonUnsafeInstanceError(
            "mastodon.instance.cross_origin_redirect", "Cross-origin redirects are blocked."
        )
    return target


def _blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return (
        any(
            (
                ip.is_loopback,
                ip.is_private,
                ip.is_link_local,
                ip.is_multicast,
                ip.is_reserved,
                ip.is_unspecified,
            )
        )
        or str(ip) == "169.254.169.254"
    )


def _is_localhost_name(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost")


class MastodonInstanceService:
    def __init__(
        self, *, transport, allow_localhost_http: bool = False, allowlist: list[str] | None = None, resolver: Any = None
    ):
        self.transport = transport
        self.allow_localhost_http = allow_localhost_http
        self.allowlist = allowlist or []
        self.resolver = resolver

    def discover(self, instance_origin: str) -> MastodonInstanceSnapshot:
        origin = normalize_instance_origin(
            instance_origin,
            allow_localhost_http=self.allow_localhost_http,
            allowlist=self.allowlist or None,
            resolver=self.resolver,
        )
        payload, metadata = self.transport.get_json(origin, "/api/v2/instance")
        if not isinstance(payload, dict):
            raise MastodonResponseValidationError(
                "mastodon.instance.malformed", "Instance discovery response is malformed."
            )
        snapshot = snapshot_from_instance(origin, payload, rate_limit_headers=metadata.get("rate_limit", {}))
        if snapshot.software_status in {"incompatible", "invalid"}:
            raise MastodonInstanceIncompatibleError("mastodon.instance.incompatible", "Instance is not pilot-ready.")
        return snapshot


def snapshot_from_instance(
    origin: str, payload: dict[str, Any], *, rate_limit_headers: dict[str, Any] | None = None
) -> MastodonInstanceSnapshot:
    config = payload.get("configuration") if isinstance(payload.get("configuration"), dict) else {}
    statuses = config.get("statuses") if isinstance(config.get("statuses"), dict) else {}
    media = config.get("media_attachments") if isinstance(config.get("media_attachments"), dict) else {}
    server_version = str(payload.get("version") or "")
    api_versions = payload.get("api_versions") if isinstance(payload.get("api_versions"), dict) else {}
    software = payload.get("software") if isinstance(payload.get("software"), dict) else {}
    software_name = str(software.get("name") or "mastodon").lower()
    warnings: list[str] = []
    status = "supported"
    if software_name and software_name != "mastodon":
        status = "unverified_compatible"
        warnings.append("software_not_official_mastodon")
    max_chars = _positive_int(statuses.get("max_characters"), 500)
    max_media = _positive_int(statuses.get("max_media_attachments"), 4)
    mime_types = [
        str(item) for item in media.get("supported_mime_types") or [] if str(item) in APP_SUPPORTED_MIME_TYPES
    ]
    if not mime_types:
        mime_types = ["image/jpeg", "image/png"]
        warnings.append("mime_support_defaulted")
    now = datetime.now(UTC)
    core = {
        "origin": origin,
        "server_version": server_version,
        "api_version": str(api_versions.get("mastodon") or api_versions.get("v2") or ""),
        "software_status": status,
        "max_characters": max_chars,
        "max_media_attachments": min(max_media, APP_MAX_IMAGES),
        "characters_reserved_per_url": _positive_int(statuses.get("characters_reserved_per_url"), 23),
        "supported_mime_types": sorted(mime_types),
        "image_size_limit": min(_positive_int(media.get("image_size_limit"), 8_000_000), 25_000_000),
        "image_matrix_limit": _positive_int(media.get("image_matrix_limit"), 16_777_216),
        "media_description_limit": _positive_int(media.get("description_limit"), 1500),
        "oauth_pkce_supported": True,
        "media_v2_supported": True,
        "media_delete_supported": True,
        "quotes_count_supported": "quote_approval_policy" in config or "quotes" in payload,
        "rate_limit_metadata_supported": bool(rate_limit_headers),
    }
    capability_checksum = hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()
    return MastodonInstanceSnapshot(
        id=f"mastodon_instance_{capability_checksum[:16]}",
        discovered_at=now.isoformat(timespec="seconds"),
        expires_at=(now + timedelta(hours=24)).isoformat(timespec="seconds"),
        capability_checksum=capability_checksum,
        safe_warnings=warnings,
        **core,
    )


def requirements_from_snapshot(account_id: str, snapshot: MastodonInstanceSnapshot) -> MastodonRequirementsSnapshot:
    payload = {
        "instance_capability_checksum": snapshot.capability_checksum,
        "content_length_limit": snapshot.max_characters,
        "characters_reserved_per_url": snapshot.characters_reserved_per_url,
        "maximum_media_count": min(snapshot.max_media_attachments, APP_MAX_IMAGES),
        "supported_mime_types": sorted(set(snapshot.supported_mime_types) & APP_SUPPORTED_MIME_TYPES),
        "maximum_image_bytes": snapshot.image_size_limit,
        "maximum_image_pixels": snapshot.image_matrix_limit,
        "description_limit": snapshot.media_description_limit,
        "plugin_version": "0.1.0",
    }
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return MastodonRequirementsSnapshot(
        id=f"mastodon_requirements_{digest[:16]}",
        channel_account_id=account_id,
        instance_origin=snapshot.origin,
        instance_snapshot_id=snapshot.id,
        capability_checksum=snapshot.capability_checksum,
        content_length_limit=snapshot.max_characters,
        characters_reserved_per_url=snapshot.characters_reserved_per_url,
        maximum_media_count=min(snapshot.max_media_attachments, APP_MAX_IMAGES),
        supported_mime_types=sorted(set(snapshot.supported_mime_types) & APP_SUPPORTED_MIME_TYPES),
        maximum_image_bytes=snapshot.image_size_limit,
        maximum_image_pixels=snapshot.image_matrix_limit,
        description_limit=snapshot.media_description_limit,
        discovered_at=snapshot.discovered_at,
        expires_at=snapshot.expires_at,
        checksum=digest,
    )


def instance_snapshot_safe_payload(snapshot: MastodonInstanceSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
