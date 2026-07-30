"""Central step registry for alpha onboarding."""

from __future__ import annotations

from .models import AlphaOnboardingStep

FOUNDATION = "Foundation"
DESTINATIONS = "Destinations"
ANALYTICS = "Analytics"
CONTENT = "Content"
PUBLISH = "Publish"
RESULTS = "Results"

REQUIRED_STEPS = {
    "welcome",
    "host_preflight",
    "workspace",
    "operator_identity",
    "publication_destination",
    "website_account",
    "first_content",
    "publication_plan",
    "final_review",
    "publish",
    "verification",
    "completion",
}

OPTIONAL_STEPS = {
    "analytics_account",
    "instrumentation",
    "social_channels",
    "analytics_sync",
    "first_funnel",
}

STEP_ORDER = (
    "welcome",
    "host_preflight",
    "workspace",
    "operator_identity",
    "managed_secrets",
    "publication_destination",
    "website_account",
    "analytics_account",
    "instrumentation",
    "social_channels",
    "first_content",
    "publication_plan",
    "final_review",
    "publish",
    "verification",
    "analytics_sync",
    "first_funnel",
    "completion",
)


def step_registry(
    *, analytics_configured: bool = False, secrets_required: bool = False
) -> dict[str, AlphaOnboardingStep]:
    required = set(REQUIRED_STEPS)
    if analytics_configured:
        required.add("instrumentation")
    if secrets_required:
        required.add("managed_secrets")
    definitions = {
        "welcome": ("Welcome", (), FOUNDATION, ""),
        "host_preflight": ("Host preflight", ("welcome",), FOUNDATION, ""),
        "workspace": ("Workspace", ("host_preflight",), FOUNDATION, ""),
        "operator_identity": ("Operator identity", ("workspace",), FOUNDATION, ""),
        "managed_secrets": (
            "Managed secrets",
            ("operator_identity",),
            FOUNDATION,
            "when selected accounts need secrets",
        ),
        "publication_destination": ("Publication destination", ("operator_identity",), DESTINATIONS, ""),
        "website_account": ("Markdown Website account", ("publication_destination",), DESTINATIONS, ""),
        "analytics_account": ("Analytics account", ("website_account",), ANALYTICS, ""),
        "instrumentation": ("Instrumentation", ("analytics_account",), ANALYTICS, "when analytics is configured"),
        "social_channels": ("Social channels", ("website_account",), DESTINATIONS, ""),
        "first_content": ("First article", ("website_account",), CONTENT, ""),
        "publication_plan": ("Publication plan", ("first_content",), PUBLISH, ""),
        "final_review": ("Final review", ("publication_plan",), PUBLISH, ""),
        "publish": ("Explicit publish", ("final_review",), PUBLISH, ""),
        "verification": ("Website verification", ("publish",), PUBLISH, ""),
        "analytics_sync": ("Analytics sync", ("verification",), RESULTS, ""),
        "first_funnel": ("First funnel", ("analytics_sync",), RESULTS, ""),
        "completion": ("Completion", ("verification",), RESULTS, ""),
    }
    return {
        step_id: AlphaOnboardingStep(
            step_id=step_id,
            display_name=display,
            required=step_id in required,
            dependencies=deps,
            recovery_actions=("retry read-only check", "show operator runbook"),
            deep_links=(f"/setup/{{session_id}}/{step_id}",),
            section=section,
            conditionally_required_when=condition,
        )
        for step_id, (display, deps, section, condition) in definitions.items()
    }


def next_step(current_step: str, completed_steps: tuple[str, ...], skipped_steps: tuple[str, ...]) -> str:
    done = set(completed_steps) | set(skipped_steps)
    for step_id in STEP_ORDER:
        if step_id not in done:
            return step_id
    return "completion"
