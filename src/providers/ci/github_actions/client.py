"""Typed GitHub Actions client boundary.

The v0.1 source is intentionally facade-backed. Production hosts provide a
registered safe HTTP facade; tests use deterministic fixtures. This module does
not perform direct network calls.
"""

from __future__ import annotations


class GitHubActionsClient:
    def __init__(self, facade) -> None:
        self.facade = facade

    def get_json(self, path: str) -> dict:
        if not path.startswith("/repos/"):
            raise ValueError("registered GitHub REST path required")
        return self.facade.get_json(path)


__all__ = ["GitHubActionsClient"]
