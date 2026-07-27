"""Integrity checks for Markdown Website state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarkdownWebsiteIntegrityFinding:
    code: str
    severity: str
    message: str


class MarkdownWebsiteIntegrityService:
    def scan(self) -> tuple[MarkdownWebsiteIntegrityFinding, ...]:
        return ()
