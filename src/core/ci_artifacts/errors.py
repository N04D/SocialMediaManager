"""CI artifact import errors."""


class CiArtifactError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


__all__ = ["CiArtifactError"]
