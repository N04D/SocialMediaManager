"""Parser placeholders for GitHub Actions REST fixture responses."""

from __future__ import annotations

from src.core.ci_artifacts.models import CiWorkflowArtifact, CiWorkflowRun


def parse_run(payload: dict) -> CiWorkflowRun:
    return CiWorkflowRun(**payload)


def parse_artifact(payload: dict) -> CiWorkflowArtifact:
    return CiWorkflowArtifact(**payload)


__all__ = ["parse_artifact", "parse_run"]
