"""Certification evidence errors."""

from __future__ import annotations


class CertificationEvidenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


__all__ = ["CertificationEvidenceError"]
