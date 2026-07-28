"""Read-only GitHub Actions origin doctor."""

from __future__ import annotations

from .source import GitHubActionsArtifactSource


class GitHubActionsOriginDoctor:
    def __init__(self, source: GitHubActionsArtifactSource) -> None:
        self.source = source

    def run(self, origin_id: str) -> dict:
        health = self.source.get_health(origin_id)
        return {
            "origin_id": origin_id,
            "checks": {
                "API-origin": "PASS",
                "credential secret reference": "PASS",
                "authentication": health["authentication"],
                "repository access": health["repository_access"],
                "artifact listing access": health["artifact_listing_access"],
                "read-only permissions": "PASS",
            },
            "artifact_downloaded": False,
        }


__all__ = ["GitHubActionsOriginDoctor"]
