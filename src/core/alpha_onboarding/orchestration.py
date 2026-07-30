"""Orchestration helpers for alpha onboarding."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import AlphaOnboardingEvent, AlphaOnboardingSession, stable_checksum, utc_now_iso


def event(
    session: AlphaOnboardingSession,
    step_id: str,
    event_type: str,
    *,
    resource_type: str = "",
    resource_id: str = "",
    safe_status: str = "ok",
    safe_error_code: str = "",
    actor_id: str = "alpha-operator",
) -> AlphaOnboardingEvent:
    occurred_at = utc_now_iso()
    event_id = (
        "alpha-event-"
        + stable_checksum([session.id, step_id, event_type, resource_type, resource_id, safe_status, occurred_at])[:24]
    )
    return AlphaOnboardingEvent(
        id=event_id,
        session_id=session.id,
        step_id=step_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        safe_status=safe_status,
        safe_error_code=safe_error_code,
        actor_id=actor_id,
        occurred_at=occurred_at,
    )


def session_payload(session: AlphaOnboardingSession) -> dict[str, Any]:
    return asdict(session)


def safe_support_summary(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "session_id",
        "workspace_id",
        "mode",
        "current_step",
        "completed_steps",
        "blocker_codes",
        "warning_codes",
        "account_reference_ids",
        "publication_plan_id",
        "executionstatus",
        "verificationstatus",
        "analyticsstatus",
        "readiness",
    }
    return {key: value for key, value in payload.items() if key in allowed}
