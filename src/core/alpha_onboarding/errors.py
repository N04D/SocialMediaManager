"""Errors for alpha onboarding."""

from __future__ import annotations


class AlphaOnboardingError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def to_dict(self) -> dict[str, object]:
        return {"error": self.code, "message": self.message, "status_code": self.status_code}
