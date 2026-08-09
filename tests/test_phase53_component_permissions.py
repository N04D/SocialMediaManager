from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.permissions import (
    ComponentPermissions,
    EgressDestination,
    InstallPermissionGrants,
    PermissionContext,
    resolve_authorized_path,
    resolve_effective_permissions,
    validate_component_permissions,
)


def test_effective_permissions_are_requested_granted_intersection() -> None:
    requested = ComponentPermissions.from_dict(
        {
            "filesystem": {"read": ["repository"], "write": ["repository"]},
            "operations": ["test.operation.read", "test.operation.write"],
            "network": {"egress": [{"host": "example.invalid", "port": 443}]},
        }
    )
    grants = InstallPermissionGrants.from_dict(
        {
            "filesystem": {"read": ["repository"], "write": ["extra_scope"]},
            "operations": ["test.operation.read", "test.operation.extra"],
            "network": {
                "egress": [
                    {"host": "example.invalid", "port": 443},
                    {"host": "unused.invalid", "port": 443},
                ]
            },
        }
    )

    effective = resolve_effective_permissions(requested=requested, grants=grants)

    assert effective.filesystem_read == ("repository",)
    assert effective.filesystem_write == ()
    assert effective.operations == ("test.operation.read",)
    assert effective.egress == (EgressDestination("example.invalid"),)
    assert effective.unexpected_filesystem_write == ("extra_scope",)
    assert effective.unexpected_operations == ("test.operation.extra",)
    assert effective.missing_filesystem_write == ("repository",)
    assert effective.missing_operations == ("test.operation.write",)


def test_validate_component_permissions_default_denies_missing_grants() -> None:
    requested = ComponentPermissions.from_dict({"operations": ["test.operation.write"]})

    result = validate_component_permissions(requested=requested, grants=InstallPermissionGrants())

    assert result.status == "BLOCKED"
    assert result.reason_code == "MISSING_OPERATION_PERMISSION"


def test_permission_serialization_roundtrip() -> None:
    permissions = ComponentPermissions.from_dict(
        {
            "filesystem": {"read": ["repository"]},
            "operations": ["test.operation.read"],
            "network": {"egress": [{"host": "example.invalid", "port": 443, "scheme": "https"}]},
        }
    )

    assert ComponentPermissions.from_dict(permissions.to_dict()) == permissions


def test_filesystem_authorized_path_blocks_escape_absolute_and_symlink() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        assert resolve_authorized_path(root=root, relative_path="docs/example.md") == root / "docs" / "example.md"
        with pytest.raises(PlaybookExecutionError) as escape:
            resolve_authorized_path(root=root, relative_path="../secret.txt")
        assert escape.value.code == "FILESYSTEM_PATH_ESCAPE"
        with pytest.raises(PlaybookExecutionError) as absolute:
            resolve_authorized_path(root=root, relative_path="/etc/passwd")
        assert absolute.value.code == "FILESYSTEM_PATH_ESCAPE"
        outside = root.parent / "outside-phase53"
        outside.mkdir(exist_ok=True)
        symlink = root / "escape"
        symlink.symlink_to(outside, target_is_directory=True)
        with pytest.raises(PlaybookExecutionError) as symlink_escape:
            resolve_authorized_path(root=root, relative_path="escape/file.txt")
        assert symlink_escape.value.code == "FILESYSTEM_PATH_ESCAPE"


def test_permission_context_blocks_denied_filesystem_operation_and_egress() -> None:
    requested = ComponentPermissions.from_dict(
        {
            "filesystem": {"read": ["test_workspace"], "write": ["test_workspace"]},
            "operations": ["test.operation.read"],
            "network": {"egress": [{"host": "example.invalid", "port": 443}]},
        }
    )
    grants = InstallPermissionGrants.from_dict(
        {
            "filesystem": {"read": ["test_workspace"]},
            "operations": ["test.operation.read"],
        }
    )
    effective = resolve_effective_permissions(requested=requested, grants=grants)
    context = PermissionContext(effective, roots={"test_workspace": "/tmp"})

    context.require_filesystem_read("test_workspace")
    context.require_operation("test.operation.read")
    with pytest.raises(PlaybookExecutionError) as denied_write:
        context.require_filesystem_write("test_workspace")
    assert denied_write.value.code == "FILESYSTEM_ACCESS_NOT_ALLOWED"
    with pytest.raises(PlaybookExecutionError) as denied_operation:
        context.require_operation("test.operation.write")
    assert denied_operation.value.code == "OPERATION_NOT_ALLOWED"
    with pytest.raises(PlaybookExecutionError) as denied_egress:
        context.require_egress(host="example.invalid", port=443)
    assert denied_egress.value.code == "EGRESS_DENIED"
