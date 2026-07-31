"""Errors for the Owned Publication Workspace."""


class OwnedPublicationError(ValueError):
    """Public error that carries a safe machine-readable code."""

    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}
