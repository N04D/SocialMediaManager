"""Managed secret errors."""


class ManagedSecretError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


__all__ = ["ManagedSecretError"]
