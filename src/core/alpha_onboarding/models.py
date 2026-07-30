"""Dataclasses for resumable alpha onboarding."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .contracts import ALPHA_ONBOARDING_SESSION_CONTRACT_VERSION

SESSION_MODES = ("real_setup", "deterministic_demo")
SESSION_STATUSES = (
    "not_started",
    "in_progress",
    "blocked",
    "waiting_for_external_action",
    "ready_for_first_publication",
    "publishing",
    "verifying",
    "completed",
    "cancelled",
    "failed",
)
CHECK_STATUSES = ("PASS", "WARN", "FAIL", "NOT_CONFIGURED", "NOT_REQUIRED")


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def stable_checksum(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class AlphaOnboardingSession:
    id: str
    workspace_id: str
    mode: str
    status: str
    current_step: str
    completed_steps: tuple[str, ...] = ()
    skipped_optional_steps: tuple[str, ...] = ()
    blocking_findings: tuple[str, ...] = ()
    warning_findings: tuple[str, ...] = ()
    created_by: str = "alpha-operator"
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""
    version: int = 1
    contract_version: str = ALPHA_ONBOARDING_SESSION_CONTRACT_VERSION


@dataclass(frozen=True)
class AlphaOnboardingStep:
    step_id: str
    display_name: str
    required: bool
    dependencies: tuple[str, ...] = ()
    validation: str = "not_run"
    completion_state: str = "not_started"
    recovery_actions: tuple[str, ...] = ()
    deep_links: tuple[str, ...] = ()
    section: str = "Foundation"
    conditionally_required_when: str = ""


@dataclass(frozen=True)
class AlphaOnboardingEvent:
    id: str
    session_id: str
    step_id: str
    event_type: str
    resource_type: str
    resource_id: str
    safe_status: str
    safe_error_code: str
    actor_id: str
    occurred_at: str


@dataclass(frozen=True)
class AlphaOnboardingFinding:
    id: str
    session_id: str
    step_id: str
    code: str
    severity: str
    explanation: str
    status: str
    related_resource_ids: tuple[str, ...] = ()
    created_at: str = ""


@dataclass(frozen=True)
class AlphaGuidedRecovery:
    session_id: str
    step_id: str
    finding_code: str
    explanation: str
    safe_actions: tuple[str, ...]
    blocked_actions: tuple[str, ...]
    related_resource_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlphaSetupReadinessReport:
    session_id: str
    workspace_id: str
    setup_progress: float
    required_steps_complete: int
    optional_steps_complete: int
    blocking_findings: tuple[str, ...]
    warning_findings: tuple[str, ...]
    website_ready: bool
    social_ready: str
    instrumentation_ready: bool
    analytics_ready: bool
    first_publication_ready: bool
    first_publication_completed: bool
    first_funnel_ready: bool
    alpha_setup_status: str
    alpha_operational_ready: bool
    publishing_ready: bool
    analytics_status: str
    analytics_ready_status: str
    instrumentation_ready_status: str
    ci_certification_ready: bool
    external_plugin_sandbox_ready: bool
    production_ready: bool
    remote_ci_status: str
    generated_at: str
    contract_version: str = "1.0"


@dataclass(frozen=True)
class FirstPublicationReadmodel:
    session_id: str
    workspace_id: str
    content_item_id: str = ""
    content_revision_id: str = ""
    website_account_id: str = ""
    publication_plan_id: str = ""
    execution_request_id: str = ""
    verification_status: str = "not_started"
    analytics_sync_status: str = "not_configured"
    funnel_status: str = "unavailable_until_configured"
    public_url: str = ""
    evidence_ids: tuple[str, ...] = ()
    mutation_summary: tuple[str, ...] = ()
    checksum_bindings: dict[str, str] = field(default_factory=dict)
    timeline: tuple[dict[str, str], ...] = ()
    updated_at: str = ""


@dataclass(frozen=True)
class HostPreflightCheck:
    name: str
    status: str
    explanation: str
    blocking: bool = False
    safe_actions: tuple[str, ...] = ()
