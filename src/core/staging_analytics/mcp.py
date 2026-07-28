"""MCP-style query surface for staging analytics certification."""

from __future__ import annotations

from typing import Any

from .service import StagingAnalyticsCertificationService


class StagingAnalyticsMCP:
    def __init__(self, service: StagingAnalyticsCertificationService | None = None) -> None:
        self.service = service or StagingAnalyticsCertificationService()

    def get_staging_analytics_profiles(self) -> dict[str, Any]:
        return self.service.list_profiles()

    def get_staging_analytics_run(self, run_id: str) -> dict[str, Any]:
        return self.service.run(run_id)

    def get_staging_browser_evidence(self, run_id: str) -> dict[str, Any]:
        return self.service.evidence(run_id)

    def get_staging_provider_reconciliation(self, run_id: str) -> dict[str, Any]:
        run = self.service.run(run_id)["run"]
        return {"reconciliation": self.service.repository.latest_reconciliation(run["run_id"])}

    def get_staging_certification_report(self, run_id: str) -> dict[str, Any]:
        return self.service.report(run_id)

    def explain_staging_certification_failure(self, run_id: str) -> dict[str, Any]:
        report = self.service.report(run_id)["report"]
        return {
            "run_id": run_id,
            "deterministic_only": report.get("deterministic_only", True),
            "reason": report.get("provider_observed_status", "staging_provider_certification_not_run"),
            "no_false_live_claim": True,
        }


__all__ = ["StagingAnalyticsMCP"]
