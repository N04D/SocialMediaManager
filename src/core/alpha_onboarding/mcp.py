"""Read-only MCP-style query surface for alpha onboarding."""

from __future__ import annotations

from typing import Any

from .service import AlphaOnboardingService


class AlphaOnboardingMCP:
    def __init__(self, service: AlphaOnboardingService | None = None) -> None:
        self.service = service or AlphaOnboardingService()

    def get_alpha_onboarding_status(self) -> dict[str, Any]:
        return {"tool": "get_alpha_onboarding_status", "read_only": True, **self.service.status()}

    def get_alpha_onboarding_steps(self, session_id: str) -> dict[str, Any]:
        return {"tool": "get_alpha_onboarding_steps", "read_only": True, **self.service.steps(session_id)}

    def get_alpha_onboarding_blockers(self, session_id: str) -> dict[str, Any]:
        readiness = self.service.readiness(session_id)
        return {"tool": "get_alpha_onboarding_blockers", "read_only": True, "blockers": readiness.blocking_findings}

    def get_alpha_setup_readiness(self, session_id: str) -> dict[str, Any]:
        return {
            "tool": "get_alpha_setup_readiness",
            "read_only": True,
            "readiness": self.service.readiness(session_id).__dict__,
        }

    def get_first_publication_plan(self, session_id: str) -> dict[str, Any]:
        return {"tool": "get_first_publication_plan", "read_only": True, **self.service.publication_review(session_id)}

    def get_first_publication_status(self, session_id: str) -> dict[str, Any]:
        return {
            "tool": "get_first_publication_status",
            "read_only": True,
            **self.service.publication_status(session_id),
        }

    def get_first_publication_evidence(self, session_id: str) -> dict[str, Any]:
        publication = self.service.publication_status(session_id)["publication"]
        return {
            "tool": "get_first_publication_evidence",
            "read_only": True,
            "evidence_ids": publication["evidence_ids"],
        }

    def get_first_funnel_status(self, session_id: str) -> dict[str, Any]:
        return {"tool": "get_first_funnel_status", "read_only": True, "funnel": self.service.funnel(session_id)}

    def explain_alpha_readiness(self, session_id: str) -> dict[str, Any]:
        readiness = self.service.readiness(session_id)
        return {
            "tool": "explain_alpha_readiness",
            "read_only": True,
            "alpha_operational_ready": readiness.alpha_operational_ready,
            "production_ready": readiness.production_ready,
            "explanation": "Alpha authoring can be ready while production readiness, remote CI import, and phase-20.2 sandbox certification remain incomplete.",
        }

    def explain_onboarding_blocker(self, session_id: str, finding_code: str) -> dict[str, Any]:
        recoveries = self.service.recovery(session_id)["recoveries"]
        match = [item for item in recoveries if item["finding_code"] == finding_code]
        return {
            "tool": "explain_onboarding_blocker",
            "read_only": True,
            "finding_code": finding_code,
            "recovery": match[0] if match else None,
        }
