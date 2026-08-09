from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import PlaybookExecutionError
from .identifiers import validate_namespaced_id, validate_runtime_id

SECRET_VALUE_FRAGMENTS = ("password", "token", "secret", "credential", "api_key")


@dataclass(frozen=True, order=True)
class EgressDestination:
    host: str
    port: int = 443
    scheme: str = "https"

    def __post_init__(self) -> None:
        host = self.host.strip().lower().rstrip(".")
        if not host:
            raise PlaybookExecutionError("INVALID_EGRESS_DESTINATION", "Egress destination requires a host.")
        if host in {"localhost"} or _is_private_ip(host):
            raise PlaybookExecutionError(
                "INVALID_EGRESS_DESTINATION",
                "Localhost and private IP destinations are not valid external egress grants.",
                {"host": host},
            )
        if not 1 <= int(self.port) <= 65535:
            raise PlaybookExecutionError("INVALID_EGRESS_DESTINATION", "Egress destination port is invalid.")
        if self.scheme and self.scheme not in {"http", "https", "ssh", "git"}:
            raise PlaybookExecutionError("INVALID_EGRESS_DESTINATION", "Egress destination scheme is invalid.")
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "port", int(self.port))
        object.__setattr__(self, "scheme", str(self.scheme or "").lower())

    @classmethod
    def from_value(cls, value: Any) -> EgressDestination:
        if isinstance(value, EgressDestination):
            return value
        if isinstance(value, str):
            host, port = _split_host_port(value)
            return cls(host=host, port=port)
        payload = dict(value or {})
        return cls(
            host=str(payload.get("host") or ""),
            port=int(payload.get("port") or 443),
            scheme=str(payload.get("scheme") or "https"),
        )

    def matches(self, *, host: str, port: int = 443, scheme: str = "https") -> bool:
        return self.host == host.strip().lower().rstrip(".") and self.port == int(port) and self.scheme == scheme

    def to_dict(self) -> dict[str, Any]:
        return {"host": self.host, "port": self.port, "scheme": self.scheme}


@dataclass(frozen=True)
class FilesystemPermissions:
    read: tuple[str, ...] = field(default_factory=tuple)
    write: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "read", _normalize_scopes(self.read))
        object.__setattr__(self, "write", _normalize_scopes(self.write))

    def to_dict(self) -> dict[str, Any]:
        return {"read": list(self.read), "write": list(self.write)}


@dataclass(frozen=True)
class OperationPermissions:
    operations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operations",
            tuple(validate_namespaced_id(item, field_name="operation") for item in self.operations),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"operations": list(self.operations)}


@dataclass(frozen=True)
class NetworkPermissions:
    egress: tuple[EgressDestination, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "egress", tuple(EgressDestination.from_value(item) for item in self.egress))

    def to_dict(self) -> dict[str, Any]:
        return {"egress": [item.to_dict() for item in self.egress]}


@dataclass(frozen=True)
class ComponentPermissions:
    filesystem: FilesystemPermissions = field(default_factory=FilesystemPermissions)
    operations: OperationPermissions = field(default_factory=OperationPermissions)
    network: NetworkPermissions = field(default_factory=NetworkPermissions)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> ComponentPermissions:
        payload = dict(payload or {})
        filesystem = _filesystem_from_dict(dict(payload.get("filesystem") or {}))
        operations_payload = payload.get("operations", ())
        operations = OperationPermissions(tuple(str(item) for item in _list_value(operations_payload)))
        network_payload = dict(payload.get("network") or {})
        egress = network_payload.get("egress", network_payload.get("allowed_domains", ()))
        return cls(filesystem=filesystem, operations=operations, network=NetworkPermissions(tuple(egress or ())))

    def to_dict(self) -> dict[str, Any]:
        return {
            "filesystem": self.filesystem.to_dict(),
            "network": self.network.to_dict(),
            "operations": list(self.operations.operations),
        }


@dataclass(frozen=True)
class InstallPermissionGrants:
    filesystem: FilesystemPermissions = field(default_factory=FilesystemPermissions)
    operations: OperationPermissions = field(default_factory=OperationPermissions)
    network: NetworkPermissions = field(default_factory=NetworkPermissions)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> InstallPermissionGrants:
        component = ComponentPermissions.from_dict(payload or {})
        return cls(component.filesystem, component.operations, component.network)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filesystem": self.filesystem.to_dict(),
            "network": self.network.to_dict(),
            "operations": list(self.operations.operations),
        }


@dataclass(frozen=True)
class EffectivePermissionSet:
    requested: ComponentPermissions
    granted: InstallPermissionGrants
    filesystem_read: tuple[str, ...]
    filesystem_write: tuple[str, ...]
    operations: tuple[str, ...]
    egress: tuple[EgressDestination, ...]
    missing_filesystem_read: tuple[str, ...] = field(default_factory=tuple)
    missing_filesystem_write: tuple[str, ...] = field(default_factory=tuple)
    missing_operations: tuple[str, ...] = field(default_factory=tuple)
    missing_egress: tuple[EgressDestination, ...] = field(default_factory=tuple)
    unexpected_filesystem_read: tuple[str, ...] = field(default_factory=tuple)
    unexpected_filesystem_write: tuple[str, ...] = field(default_factory=tuple)
    unexpected_operations: tuple[str, ...] = field(default_factory=tuple)
    unexpected_egress: tuple[EgressDestination, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return not (
            self.missing_filesystem_read
            or self.missing_filesystem_write
            or self.missing_operations
            or self.missing_egress
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective": {
                "egress": [item.to_dict() for item in self.egress],
                "filesystem": {"read": list(self.filesystem_read), "write": list(self.filesystem_write)},
                "operations": list(self.operations),
            },
            "granted": self.granted.to_dict(),
            "missing": {
                "egress": [item.to_dict() for item in self.missing_egress],
                "filesystem": {
                    "read": list(self.missing_filesystem_read),
                    "write": list(self.missing_filesystem_write),
                },
                "operations": list(self.missing_operations),
            },
            "requested": self.requested.to_dict(),
            "unexpected": {
                "egress": [item.to_dict() for item in self.unexpected_egress],
                "filesystem": {
                    "read": list(self.unexpected_filesystem_read),
                    "write": list(self.unexpected_filesystem_write),
                },
                "operations": list(self.unexpected_operations),
            },
        }


@dataclass(frozen=True)
class PermissionValidationResult:
    status: str
    reason_code: str = ""
    effective: EffectivePermissionSet | None = None

    @property
    def ready(self) -> bool:
        return self.status == "READY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective": self.effective.to_dict() if self.effective else {},
            "reason_code": self.reason_code,
            "status": self.status,
        }


@dataclass(frozen=True)
class PermissionContext:
    effective: EffectivePermissionSet
    roots: dict[str, str] = field(default_factory=dict)

    def require_filesystem_read(self, scope: str) -> None:
        if scope not in self.effective.filesystem_read:
            raise PlaybookExecutionError(
                "FILESYSTEM_ACCESS_NOT_ALLOWED",
                "Filesystem read permission is not granted.",
                {"scope": scope},
            )

    def require_filesystem_write(self, scope: str) -> None:
        if scope not in self.effective.filesystem_write:
            raise PlaybookExecutionError(
                "FILESYSTEM_ACCESS_NOT_ALLOWED",
                "Filesystem write permission is not granted.",
                {"scope": scope},
            )

    def require_operation(self, operation_id: str) -> None:
        operation = validate_namespaced_id(operation_id, field_name="operation_id")
        if operation not in self.effective.operations:
            raise PlaybookExecutionError(
                "OPERATION_NOT_ALLOWED",
                "Operation permission is not granted.",
                {"operation": operation},
            )

    def require_egress(self, *, host: str, port: int = 443, scheme: str = "https") -> None:
        if not any(item.matches(host=host, port=port, scheme=scheme) for item in self.effective.egress):
            raise PlaybookExecutionError(
                "EGRESS_DENIED",
                "Network egress destination is not granted.",
                {"host": host, "port": port, "scheme": scheme},
            )

    def resolve_path(self, *, scope: str, relative_path: str, write: bool = False) -> Path:
        if write:
            self.require_filesystem_write(scope)
        else:
            self.require_filesystem_read(scope)
        root = self.roots.get(scope)
        if not root:
            raise PlaybookExecutionError("INVALID_PERMISSION_SCOPE", "No root is configured for filesystem scope.")
        return resolve_authorized_path(root=Path(root), relative_path=relative_path)

    def to_dict(self) -> dict[str, Any]:
        return {"effective": self.effective.to_dict()["effective"], "roots": sorted(self.roots)}


def capability_permission_requirements(component: Any, capability_id: str) -> ComponentPermissions:
    capability = component.capability(capability_id) if hasattr(component, "capability") else None
    if capability is not None:
        policy_permissions = dict(getattr(capability, "policy", {}) or {}).get("permissions")
        if isinstance(policy_permissions, dict):
            return ComponentPermissions.from_dict(policy_permissions)
    permissions = dict(getattr(component, "permissions", {}) or {})
    capability_map = dict(permissions.get("capabilities") or {})
    specific = capability_map.get(capability_id)
    if isinstance(specific, dict):
        return ComponentPermissions.from_dict(specific)
    return ComponentPermissions.from_dict(permissions)


def resolve_effective_permissions(
    *, requested: ComponentPermissions, grants: InstallPermissionGrants
) -> EffectivePermissionSet:
    requested_read = set(requested.filesystem.read)
    requested_write = set(requested.filesystem.write)
    requested_ops = set(requested.operations.operations)
    requested_egress = set(requested.network.egress)
    granted_read = set(grants.filesystem.read)
    granted_write = set(grants.filesystem.write)
    granted_ops = set(grants.operations.operations)
    granted_egress = set(grants.network.egress)
    return EffectivePermissionSet(
        requested=requested,
        granted=grants,
        filesystem_read=tuple(sorted(requested_read & granted_read)),
        filesystem_write=tuple(sorted(requested_write & granted_write)),
        operations=tuple(sorted(requested_ops & granted_ops)),
        egress=tuple(sorted(requested_egress & granted_egress)),
        missing_filesystem_read=tuple(sorted(requested_read - granted_read)),
        missing_filesystem_write=tuple(sorted(requested_write - granted_write)),
        missing_operations=tuple(sorted(requested_ops - granted_ops)),
        missing_egress=tuple(sorted(requested_egress - granted_egress)),
        unexpected_filesystem_read=tuple(sorted(granted_read - requested_read)),
        unexpected_filesystem_write=tuple(sorted(granted_write - requested_write)),
        unexpected_operations=tuple(sorted(granted_ops - requested_ops)),
        unexpected_egress=tuple(sorted(granted_egress - requested_egress)),
    )


def validate_component_permissions(
    *, requested: ComponentPermissions, grants: InstallPermissionGrants
) -> PermissionValidationResult:
    effective = resolve_effective_permissions(requested=requested, grants=grants)
    if effective.missing_filesystem_read or effective.missing_filesystem_write:
        return PermissionValidationResult("BLOCKED", "MISSING_FILESYSTEM_PERMISSION", effective)
    if effective.missing_operations:
        return PermissionValidationResult("BLOCKED", "MISSING_OPERATION_PERMISSION", effective)
    if effective.missing_egress:
        return PermissionValidationResult("BLOCKED", "MISSING_EGRESS_PERMISSION", effective)
    return PermissionValidationResult("READY", effective=effective)


def resolve_authorized_path(*, root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise PlaybookExecutionError("FILESYSTEM_PATH_ESCAPE", "Filesystem path escapes the authorized scope.")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve(strict=False)
    if os.path.commonpath([str(resolved_root), str(resolved)]) != str(resolved_root):
        raise PlaybookExecutionError("FILESYSTEM_PATH_ESCAPE", "Filesystem path escapes the authorized scope.")
    for parent in [resolved, *resolved.parents]:
        if parent == resolved_root:
            break
        if parent.is_symlink():
            raise PlaybookExecutionError("FILESYSTEM_PATH_ESCAPE", "Symlink path escapes are rejected.")
    return resolved


def assert_no_secret_values_in_grants(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).lower()
    if any(fragment in encoded for fragment in SECRET_VALUE_FRAGMENTS):
        raise PlaybookExecutionError("PERMISSION_GRANT_SECRET_VALUE", "Permission grants cannot contain secrets.")


def _filesystem_from_dict(payload: dict[str, Any]) -> FilesystemPermissions:
    if "mode" in payload:
        mode = str(payload.get("mode") or "none")
        if mode == "read":
            return FilesystemPermissions(read=("repository",))
        if mode == "write":
            return FilesystemPermissions(read=("repository",), write=("repository",))
        return FilesystemPermissions()
    return FilesystemPermissions(
        read=tuple(str(item) for item in _list_value(payload.get("read", ()))),
        write=tuple(str(item) for item in _list_value(payload.get("write", ()))),
    )


def _normalize_scopes(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(validate_runtime_id(str(item), field_name="filesystem_scope") for item in values)


def _list_value(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def _split_host_port(value: str) -> tuple[str, int]:
    if ":" not in value:
        return value, 443
    host, port = value.rsplit(":", 1)
    return host, int(port)


def _is_private_ip(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local
