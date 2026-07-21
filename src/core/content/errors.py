from __future__ import annotations


class ContentError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class ContentNotFoundError(ContentError):
    pass


class ContentValidationError(ContentError):
    pass


class ContentConflictError(ContentError):
    pass
