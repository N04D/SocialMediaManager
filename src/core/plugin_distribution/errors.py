"""Safe public errors for plugin distribution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginDistributionError(Exception):
    code: str
    safe_message: str
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False

    def __str__(self) -> str:
        return self.safe_message


class PluginPackageInvalidError(PluginDistributionError): ...


class PluginUnsupportedPackageFormatError(PluginDistributionError): ...


class PluginWheelValidationError(PluginDistributionError): ...


class PluginWheelPathError(PluginDistributionError): ...


class PluginRecordValidationError(PluginDistributionError): ...


class PluginEntrypointValidationError(PluginDistributionError): ...


class PluginIdentityConflictError(PluginDistributionError): ...


class PluginDependencyPolicyError(PluginDistributionError): ...


class PluginSignatureVerificationError(PluginDistributionError): ...


class PluginSignerIdentityError(PluginDistributionError): ...


class PluginRegistryMetadataError(PluginDistributionError): ...


class PluginRegistryExpiredError(PluginDistributionError): ...


class PluginRegistryRollbackError(PluginDistributionError): ...


class PluginArtifactHashError(PluginDistributionError): ...


class PluginArtifactSizeError(PluginDistributionError): ...


class PluginInstallationError(PluginDistributionError): ...


class PluginActivationError(PluginDistributionError): ...


class PluginRollbackError(PluginDistributionError): ...


class PluginUninstallBlockedError(PluginDistributionError): ...


class PluginReleaseYankedError(PluginDistributionError): ...


class PluginReleaseRevokedError(PluginDistributionError): ...


class PluginQuarantinedError(PluginDistributionError): ...


class PluginInstalledFileDriftError(PluginDistributionError): ...


class PluginHostCompatibilityError(PluginDistributionError): ...


__all__ = [name for name in globals() if name.startswith("Plugin")]
