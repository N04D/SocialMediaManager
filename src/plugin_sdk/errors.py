"""Public Plugin SDK errors.

Errors raised through this module are safe to show in CLI, tests, and
compatibility reports. Tracebacks and remote response bodies remain internal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginSDKError(Exception):
    """Base class for public SDK failures."""

    code: str
    safe_message: str
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False

    def __str__(self) -> str:
        return self.safe_message


class PluginManifestValidationError(PluginSDKError):
    """Raised when a plugin manifest fails SDK schema validation."""


class PluginCapabilityUnsupportedError(PluginSDKError):
    """Raised when a runtime operation is requested without a capability."""


class PluginPermissionError(PluginSDKError):
    """Raised when a facade is requested without a declared permission."""


class PluginCompatibilityError(PluginSDKError):
    """Raised when compatibility checks fail hard."""


class PluginSecurityError(PluginSDKError):
    """Raised by import or secret scanners."""


__all__ = [
    "PluginSDKError",
    "PluginManifestValidationError",
    "PluginCapabilityUnsupportedError",
    "PluginPermissionError",
    "PluginCompatibilityError",
    "PluginSecurityError",
]
