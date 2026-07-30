"""Minimal API adapter for alpha onboarding routes."""

from __future__ import annotations

from typing import Any

from .service import AlphaOnboardingService


class AlphaOnboardingAPI:
    routes = (
        "GET /api/onboarding",
        "POST /api/onboarding",
        "GET /api/onboarding/{id}",
        "POST /api/onboarding/{id}/resume",
        "POST /api/onboarding/{id}/cancel",
        "GET /api/onboarding/{id}/steps",
        "GET /api/onboarding/{id}/steps/{step_id}",
        "POST /api/onboarding/{id}/steps/{step_id}/validate",
        "POST /api/onboarding/{id}/steps/{step_id}/complete",
        "POST /api/onboarding/{id}/steps/{step_id}/skip",
        "GET /api/onboarding/{id}/readiness",
        "GET /api/onboarding/{id}/recovery",
        "POST /api/onboarding/{id}/recovery/{finding_id}/execute",
        "POST /api/onboarding/{id}/publication/review",
        "POST /api/onboarding/{id}/publication/confirm",
        "GET /api/onboarding/{id}/publication/status",
        "POST /api/onboarding/{id}/analytics/sync",
        "GET /api/onboarding/{id}/funnel",
    )

    ui_routes = (
        "/setup",
        "/setup/{session_id}",
        "/setup/{session_id}/{step_id}",
        "/setup/{session_id}/review",
        "/setup/{session_id}/publish",
        "/setup/{session_id}/result",
        "/setup/{session_id}/funnel",
        "/home",
        "/content",
        "/calendar",
        "/analytics",
        "/operations",
    )

    def __init__(self, service: AlphaOnboardingService | None = None) -> None:
        self.service = service or AlphaOnboardingService()

    def dispatch(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        body = body or {}
        parts = [part for part in path.strip("/").split("/") if part]
        if method == "GET" and parts == ["api", "onboarding"]:
            return self.service.status()
        if method == "POST" and parts == ["api", "onboarding"]:
            return self.service.start(**body)
        if len(parts) >= 3 and parts[:2] == ["api", "onboarding"]:
            session_id = parts[2]
            if method == "GET" and len(parts) == 3:
                return self.service.get(session_id)
            if method == "POST" and parts[3:] == ["resume"]:
                return self.service.resume(session_id)
            if method == "POST" and parts[3:] == ["cancel"]:
                return self.service.cancel(session_id, expected_version=body.get("expected_version"))
            if method == "GET" and parts[3:] == ["steps"]:
                return self.service.steps(session_id)
            if len(parts) == 5 and parts[3] == "steps" and method == "GET":
                return self.service.step(session_id, parts[4])
            if len(parts) == 6 and parts[3] == "steps" and parts[5] == "validate":
                return self.service.validate_step(session_id, parts[4], body)
            if len(parts) == 6 and parts[3] == "steps" and parts[5] == "complete":
                return self.service.complete_step(session_id, parts[4], body)
            if len(parts) == 6 and parts[3] == "steps" and parts[5] == "skip":
                return self.service.skip_step(session_id, parts[4], body)
            if method == "GET" and parts[3:] == ["readiness"]:
                return self.service.readiness(session_id).__dict__
            if method == "GET" and parts[3:] == ["recovery"]:
                return self.service.recovery(session_id)
            if len(parts) == 6 and parts[3] == "recovery" and parts[5] == "execute":
                return self.service.execute_recovery(session_id, parts[4])
            if method == "POST" and parts[3:] == ["publication", "review"]:
                return self.service.publication_review(session_id)
            if method == "POST" and parts[3:] == ["publication", "confirm"]:
                return self.service.publication_confirm(session_id, body)
            if method == "GET" and parts[3:] == ["publication", "status"]:
                return self.service.publication_status(session_id)
            if method == "POST" and parts[3:] == ["analytics", "sync"]:
                return self.service.analytics_sync(session_id)
            if method == "GET" and parts[3:] == ["funnel"]:
                return self.service.funnel(session_id)
        return {"error": "alpha_onboarding.route_not_found", "status_code": 404}
