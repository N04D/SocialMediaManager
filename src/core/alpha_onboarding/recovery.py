"""Guided recovery explanations for alpha onboarding."""

from __future__ import annotations

from .models import AlphaGuidedRecovery, AlphaOnboardingFinding

SAFE_ACTIONS = {
    "vault_unavailable": ("open settings", "retry read-only check", "show operator runbook"),
    "repository_dirty": ("open settings", "retry read-only check", "select another registered resource"),
    "accountdoctor_failure": ("open settings", "retry read-only check", "show operator runbook"),
    "missing_secret": ("create missing managed reference", "open settings", "show operator runbook"),
    "approval_pending": ("open settings", "retry read-only check"),
    "renderer_validation": ("open settings", "retry read-only check"),
    "missing_media": ("open settings", "select another registered resource"),
    "publication_uncertain": ("retry read-only check", "show operator runbook"),
    "verification_pending": ("retry read-only check", "show operator runbook"),
    "analytics_not_configured": ("open settings", "show operator runbook"),
    "instrumentation_drift": ("open settings", "retry read-only check"),
    "provider_rate_limited": ("retry read-only check", "show operator runbook"),
    "current_revision_changed": ("open settings", "show operator runbook"),
}

BLOCKED_ACTIONS = (
    "change credentials automatically",
    "replace database",
    "force Git operations",
    "repeat external mutation",
    "mark sandbox as passed",
)


def recovery_for_finding(finding: AlphaOnboardingFinding) -> AlphaGuidedRecovery:
    return AlphaGuidedRecovery(
        session_id=finding.session_id,
        step_id=finding.step_id,
        finding_code=finding.code,
        explanation=finding.explanation,
        safe_actions=SAFE_ACTIONS.get(
            finding.code, ("open settings", "retry read-only check", "show operator runbook")
        ),
        blocked_actions=BLOCKED_ACTIONS,
        related_resource_ids=finding.related_resource_ids,
    )
