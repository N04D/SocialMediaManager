"""Support bundle entrypoint for staging analytics certification."""

from __future__ import annotations

from .service import StagingAnalyticsCertificationService


def create_support_bundle(service: StagingAnalyticsCertificationService | None = None) -> dict:
    return (service or StagingAnalyticsCertificationService()).support_bundle()


__all__ = ["create_support_bundle"]
