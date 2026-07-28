"""Errors raised by the trusted signing service."""


class TrustedSigningError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


__all__ = ["TrustedSigningError"]
