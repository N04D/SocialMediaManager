"""Safe plugin sandbox errors."""

from __future__ import annotations


class PluginSandboxError(Exception):
    def __init__(self, code: str, safe_message: str, *, retryable: bool = False) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable

    def to_public(self) -> dict[str, object]:
        return {"code": self.code, "message": self.safe_message, "retryable": self.retryable}


class PluginSandboxPolicyError(PluginSandboxError):
    pass


class PluginSandboxPlanError(PluginSandboxError):
    pass


class PluginSandboxUnavailableError(PluginSandboxError):
    pass


class PluginSandboxVerificationError(PluginSandboxError):
    pass


class PluginSandboxViolationError(PluginSandboxError):
    pass


class PluginSandboxActivationBlockedError(PluginSandboxError):
    pass


__all__ = [
    "PluginSandboxActivationBlockedError",
    "PluginSandboxError",
    "PluginSandboxPlanError",
    "PluginSandboxPolicyError",
    "PluginSandboxUnavailableError",
    "PluginSandboxVerificationError",
    "PluginSandboxViolationError",
]
