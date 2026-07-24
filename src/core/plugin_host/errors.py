"""Safe Plugin Host Framework errors."""

from __future__ import annotations


class PluginHostError(Exception):
    def __init__(self, code: str, safe_message: str, *, retryable: bool = False) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable

    def to_public(self) -> dict[str, object]:
        return {"code": self.code, "message": self.safe_message, "retryable": self.retryable}


class PluginHostProtocolError(PluginHostError):
    pass


class PluginHostFrameError(PluginHostProtocolError):
    pass


class PluginHostHandshakeError(PluginHostError):
    pass


class PluginHostIdentityError(PluginHostHandshakeError):
    pass


class PluginHostEnvironmentError(PluginHostError):
    pass


class PluginHostProcessError(PluginHostError):
    pass


class PluginHostTimeoutError(PluginHostError):
    pass


class PluginHostCallbackAuthorizationError(PluginHostError):
    pass


class PluginHostPermissionError(PluginHostError):
    pass


class PluginHostResourceLimitError(PluginHostError):
    pass


class PluginHostCrashLoopError(PluginHostError):
    pass


class PluginHostQuarantineError(PluginHostError):
    pass


class PluginHostStateError(PluginHostError):
    pass


__all__ = [
    "PluginHostCallbackAuthorizationError",
    "PluginHostCrashLoopError",
    "PluginHostEnvironmentError",
    "PluginHostError",
    "PluginHostFrameError",
    "PluginHostHandshakeError",
    "PluginHostIdentityError",
    "PluginHostPermissionError",
    "PluginHostProcessError",
    "PluginHostProtocolError",
    "PluginHostQuarantineError",
    "PluginHostResourceLimitError",
    "PluginHostStateError",
    "PluginHostTimeoutError",
]
