"""Deterministic alpha onboarding scenarios."""

from __future__ import annotations

from pathlib import Path

from .fixtures import build_alpha_onboarding_service


def complete_demo_flow(root: Path) -> dict[str, object]:
    service = build_alpha_onboarding_service(root)
    payload = service.demo_start()
    session_id = payload["session"]["id"]
    for step_id in (
        "publication_destination",
        "website_account",
        "analytics_account",
        "instrumentation",
        "social_channels",
        "first_content",
        "publication_plan",
        "final_review",
    ):
        payload = service.complete_step(
            session_id, step_id, {"expected_version": service.get(session_id)["session"]["version"]}
        )
    review = service.publication_review(session_id)
    publish = service.publication_confirm(
        session_id,
        {
            "confirmation": "Publish this immutable revision using this plan",
            "expected_version": service.get(session_id)["session"]["version"],
        },
    )
    payload = service.complete_step(
        session_id, "publish", {"expected_version": service.get(session_id)["session"]["version"]}
    )
    payload = service.complete_step(
        session_id, "verification", {"expected_version": service.get(session_id)["session"]["version"]}
    )
    sync = service.analytics_sync(session_id)
    payload = service.complete_step(
        session_id, "analytics_sync", {"expected_version": service.get(session_id)["session"]["version"]}
    )
    funnel = service.funnel(session_id)
    payload = service.complete_step(
        session_id, "first_funnel", {"expected_version": service.get(session_id)["session"]["version"]}
    )
    payload = service.complete_step(
        session_id, "completion", {"expected_version": service.get(session_id)["session"]["version"]}
    )
    return {"payload": payload, "review": review, "publish": publish, "sync": sync, "funnel": funnel}
