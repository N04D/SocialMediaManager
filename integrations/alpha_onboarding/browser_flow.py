"""Browser-flow descriptors for phase-32 tests.

The repository's phase tests assert the route contract and flow semantics here;
real Playwright execution in CI uses the same deterministic route list without
external network or user-owned files.
"""

DEMO_BROWSER_FLOW = (
    "/setup",
    "/setup/{session_id}/host_preflight",
    "/setup/{session_id}/workspace",
    "/setup/{session_id}/operator_identity",
    "/setup/{session_id}/managed_secrets",
    "/setup/{session_id}/website_account",
    "/setup/{session_id}/analytics_account",
    "/setup/{session_id}/instrumentation",
    "/setup/{session_id}/social_channels",
    "/setup/{session_id}/first_content",
    "/setup/{session_id}/publication_plan",
    "/setup/{session_id}/review",
    "/setup/{session_id}/publish",
    "/setup/{session_id}/result",
    "/setup/{session_id}/funnel",
)


def accessibility_contract() -> dict[str, object]:
    return {
        "single_h1": True,
        "semantic_progress": True,
        "field_labels": True,
        "errors_linked_to_fields": True,
        "blockers_focusable": True,
        "status_not_color_only": True,
        "keyboard_review_summary": True,
        "confirm_button_accessible_name": "Publish this immutable revision using this plan",
        "autosave_live_region": True,
        "publication_timeline_accessible": True,
    }
