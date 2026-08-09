from __future__ import annotations

import pytest

from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.permissions import (
    ComponentPermissions,
    EgressDestination,
    InstallPermissionGrants,
    PermissionContext,
    resolve_effective_permissions,
    validate_component_permissions,
)


def _context() -> PermissionContext:
    requested = ComponentPermissions.from_dict(
        {"network": {"egress": [{"host": "github.com", "port": 443, "scheme": "https"}]}}
    )
    grants = InstallPermissionGrants.from_dict(
        {"network": {"egress": [{"host": "github.com", "port": 443, "scheme": "https"}]}}
    )
    return PermissionContext(resolve_effective_permissions(requested=requested, grants=grants))


def test_egress_allows_exact_destination_only() -> None:
    context = _context()

    context.require_egress(host="github.com", port=443, scheme="https")
    with pytest.raises(PlaybookExecutionError) as suffix:
        context.require_egress(host="github.com.evil.example", port=443, scheme="https")
    assert suffix.value.code == "EGRESS_DENIED"
    with pytest.raises(PlaybookExecutionError) as wrong_port:
        context.require_egress(host="github.com", port=22, scheme="ssh")
    assert wrong_port.value.code == "EGRESS_DENIED"


def test_egress_missing_grant_blocks_preflight() -> None:
    requested = ComponentPermissions.from_dict({"network": {"egress": [{"host": "github.com", "port": 443}]}})

    result = validate_component_permissions(requested=requested, grants=InstallPermissionGrants())

    assert result.status == "BLOCKED"
    assert result.reason_code == "MISSING_EGRESS_PERMISSION"


def test_localhost_and_private_ips_are_not_external_egress_grants() -> None:
    with pytest.raises(PlaybookExecutionError) as localhost:
        EgressDestination("localhost", 443)
    assert localhost.value.code == "INVALID_EGRESS_DESTINATION"
    with pytest.raises(PlaybookExecutionError) as loopback:
        EgressDestination("127.0.0.1", 443)
    assert loopback.value.code == "INVALID_EGRESS_DESTINATION"
    with pytest.raises(PlaybookExecutionError) as metadata_ip:
        EgressDestination("169.254.169.254", 80, "http")
    assert metadata_ip.value.code == "INVALID_EGRESS_DESTINATION"


def test_local_git_transport_is_not_external_egress() -> None:
    requested = ComponentPermissions.from_dict({"filesystem": {"read": ["repository"]}})
    grants = InstallPermissionGrants.from_dict({"filesystem": {"read": ["repository"]}})

    result = validate_component_permissions(requested=requested, grants=grants)

    assert result.ready
    assert result.effective is not None
    assert result.effective.egress == ()
