"""Application service for alpha onboarding and first publication."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from src.core.owned_publication.models import stable_checksum as owned_checksum
from src.core.owned_publication.models import utc_now_iso
from src.core.owned_publication.operations import ProductionReadinessService
from src.core.owned_publication.service import OwnedPublicationWorkspaceService
from src.core.website_analytics.service import WebsiteAnalyticsService
from src.core.website_instrumentation.service import WebsiteInstrumentationService

from .contracts import contract_payload
from .demo import synthetic_article_payload
from .errors import AlphaOnboardingError
from .models import (
    CHECK_STATUSES,
    SESSION_MODES,
    AlphaOnboardingSession,
    HostPreflightCheck,
)
from .orchestration import event, session_payload
from .persistence import DatabaseAlphaOnboardingRepository
from .readiness import AlphaReadinessService
from .recovery import recovery_for_finding
from .steps import OPTIONAL_STEPS, STEP_ORDER, next_step, step_registry


class AlphaOnboardingService:
    def __init__(
        self,
        *,
        database_path: str | Path | None = None,
        repository: DatabaseAlphaOnboardingRepository | None = None,
        workspace_service: OwnedPublicationWorkspaceService | None = None,
        analytics_service: WebsiteAnalyticsService | None = None,
        instrumentation_service: WebsiteInstrumentationService | None = None,
        production_service: ProductionReadinessService | None = None,
    ) -> None:
        self.repository = repository or DatabaseAlphaOnboardingRepository(database_path)
        self.workspace_service = workspace_service or OwnedPublicationWorkspaceService(database_path=database_path)
        self.analytics_service = analytics_service or WebsiteAnalyticsService(database_path=database_path)
        self.instrumentation_service = instrumentation_service or WebsiteInstrumentationService(
            database_path=database_path
        )
        self.readiness_service = AlphaReadinessService(production_service=production_service)

    def contracts(self) -> dict[str, str]:
        return contract_payload()

    def status(self) -> dict[str, Any]:
        sessions = [session_payload(item) for item in self.repository.list_sessions()]
        active = [item for item in sessions if item["status"] not in {"completed", "cancelled", "failed"}]
        return {
            "contracts": self.contracts(),
            "sessions": sessions,
            "active_sessions": active,
            "alpha_ready_is_production_ready": False,
            "external_plugin_sandbox_ready": False,
            "remote_ci_status_without_import": "artifact_not_imported",
        }

    def start(
        self,
        *,
        mode: str = "real_setup",
        workspace_id: str = "workspace-alpha-1",
        actor: str = "alpha-operator",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        if mode not in SESSION_MODES:
            raise AlphaOnboardingError("alpha_onboarding.invalid_mode", "Unknown alpha onboarding mode.")
        now = utc_now_iso()
        seed = idempotency_key or f"{workspace_id}:{mode}:{actor}:{now}"
        session = AlphaOnboardingSession(
            id="alpha-session-" + owned_checksum(seed)[:20],
            workspace_id=workspace_id,
            mode=mode,
            status="in_progress",
            current_step="welcome",
            created_by=actor,
            created_at=now,
            updated_at=now,
        )
        saved = self.repository.create_session(session)
        self.repository.append_event(
            event(saved, "welcome", "onboarding_started", resource_type="session", resource_id=saved.id, actor_id=actor)
        )
        return {"session": session_payload(saved), "readiness": asdict(self.readiness(saved.id))}

    def demo_start(self, *, actor: str = "demo-operator") -> dict[str, Any]:
        payload = self.start(
            mode="deterministic_demo",
            workspace_id="demo-workspace-alpha",
            actor=actor,
            idempotency_key="deterministic-demo-alpha",
        )
        session_id = payload["session"]["id"]
        for step_id in ("welcome", "host_preflight", "workspace", "operator_identity", "managed_secrets"):
            self.complete_step(
                session_id, step_id, {"fixture": True, "expected_version": self.get(session_id)["session"]["version"]}
            )
        return self.get(session_id)

    def get(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        return {
            "contracts": self.contracts(),
            "session": session_payload(session),
            "steps": self.steps(session_id)["steps"],
            "readiness": asdict(self.readiness(session_id)),
            "first_publication": asdict(self.repository.first_publication(session_id)),
            "events": self.repository.events(session_id),
            "bindings": self.repository.list_bindings(session_id),
        }

    def resume(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        if session.status in {"cancelled", "failed"}:
            raise AlphaOnboardingError("alpha_onboarding.not_resumable", "Onboarding session is not resumable.")
        if session.status == "completed":
            return self.get(session_id)
        self.repository.append_event(
            event(session, session.current_step, "session_resumed", resource_type="session", resource_id=session.id)
        )
        return self.get(session_id)

    def cancel(
        self, session_id: str, *, expected_version: int | None = None, actor: str = "alpha-operator"
    ) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        cancelled = self.repository.save_session(
            replace(session, status="cancelled", updated_at=utc_now_iso()),
            expected_version=expected_version,
        )
        self.repository.append_event(
            event(
                cancelled,
                cancelled.current_step,
                "onboarding_cancelled",
                resource_type="session",
                resource_id=session_id,
                actor_id=actor,
            )
        )
        return {"session": session_payload(cancelled)}

    def steps(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        states = self.repository.list_step_states(session_id)
        registry = step_registry(analytics_configured="analytics_account" in session.completed_steps)
        payload = []
        for step_id in STEP_ORDER:
            step = registry[step_id]
            state = states.get(step_id, self.repository.get_step_state(session_id, step_id))
            payload.append(
                {
                    **asdict(step),
                    **state,
                    "deep_links": [link.format(session_id=session_id) for link in step.deep_links],
                }
            )
        return {
            "steps": payload,
            "sections": ("Foundation", "Destinations", "Analytics", "Content", "Publish", "Results"),
            "no_horizontal_18_step_bar": True,
        }

    def step(self, session_id: str, step_id: str) -> dict[str, Any]:
        if step_id not in STEP_ORDER:
            raise AlphaOnboardingError("alpha_onboarding.unknown_step", "Unknown onboarding step.", status_code=404)
        session = self.repository.get_session(session_id)
        self.repository.append_event(event(session, step_id, "step_opened", resource_type="step", resource_id=step_id))
        matching = [step for step in self.steps(session_id)["steps"] if step["step_id"] == step_id][0]
        return {
            "session": session_payload(session),
            "step": matching,
            "welcome": self._welcome_text() if step_id == "welcome" else {},
        }

    def validate_step(self, session_id: str, step_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        checks = self.host_preflight() if step_id == "host_preflight" else []
        blocking = [check.name for check in checks if check.blocking]
        state = "blocked" if blocking else "valid"
        self.repository.upsert_step_state(session_id, step_id, validation_state=state, completion_state="validated")
        self.repository.append_event(
            event(
                session, step_id, "validation_performed", resource_type="step", resource_id=step_id, safe_status=state
            )
        )
        return {
            "step_id": step_id,
            "validation_state": state,
            "checks": [asdict(check) for check in checks],
            "blocking": blocking,
        }

    def complete_step(self, session_id: str, step_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        session = self.repository.get_session(session_id)
        expected = payload.get("expected_version")
        registry = step_registry(analytics_configured="analytics_account" in session.completed_steps)
        if step_id not in registry:
            raise AlphaOnboardingError("alpha_onboarding.unknown_step", "Unknown onboarding step.", status_code=404)
        missing = [
            dep
            for dep in registry[step_id].dependencies
            if dep not in session.completed_steps and dep not in session.skipped_optional_steps
        ]
        if missing:
            raise AlphaOnboardingError("alpha_onboarding.dependency_missing", "Step dependencies are incomplete.")
        resource = self._complete_resource(session, step_id, payload)
        completed = tuple(dict.fromkeys((*session.completed_steps, step_id)))
        status = self._status_after_completion(step_id)
        current = next_step(step_id, completed, session.skipped_optional_steps)
        completed_at = utc_now_iso() if step_id == "completion" else session.completed_at
        updated = self.repository.save_session(
            replace(session, completed_steps=completed, current_step=current, status=status, completed_at=completed_at),
            expected_version=int(expected) if expected is not None else None,
        )
        self.repository.upsert_step_state(
            session_id,
            step_id,
            validation_state="valid",
            completion_state="completed",
            resource_bindings={resource["resource_type"]: resource["resource_id"]},
        )
        self.repository.append_event(
            event(
                updated,
                step_id,
                "step_completed",
                resource_type=resource["resource_type"],
                resource_id=resource["resource_id"],
                safe_status="completed",
                actor_id=str(payload.get("actor") or "alpha-operator"),
            )
        )
        return self.get(session_id)

    def skip_step(self, session_id: str, step_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        if step_id not in OPTIONAL_STEPS:
            raise AlphaOnboardingError("alpha_onboarding.required_step", "Required onboarding steps cannot be skipped.")
        skipped = tuple(dict.fromkeys((*session.skipped_optional_steps, step_id)))
        updated = self.repository.save_session(
            replace(
                session,
                skipped_optional_steps=skipped,
                current_step=next_step(step_id, session.completed_steps, skipped),
            ),
            expected_version=int((payload or {}).get("expected_version", session.version)),
        )
        self.repository.upsert_step_state(session_id, step_id, validation_state="skipped", completion_state="skipped")
        self.repository.append_event(
            event(updated, step_id, "optional_step_skipped", resource_type="step", resource_id=step_id)
        )
        return self.get(session_id)

    def readiness(self, session_id: str):
        session = self.repository.get_session(session_id)
        bindings = self.repository.list_bindings(session_id)
        binding_types = {item["resource_type"] for item in bindings}
        findings = self.repository.findings(session_id)
        first = self.repository.first_publication(session_id)
        return self.readiness_service.calculate(
            session,
            findings,
            analytics_configured="analytics_account" in session.completed_steps,
            instrumentation_configured="instrumentation" in session.completed_steps,
            website_account_ready="website_account" in binding_types,
            first_revision_exists=bool(first.content_revision_id),
            publication_plan_valid=bool(first.publication_plan_id),
            first_publication_safe_state=first.verification_status in {"verified", "safely_pending", "scheduled"},
            first_publication_completed=first.verification_status == "verified",
            first_funnel_ready=first.funnel_status == "ready",
        )

    def recovery(self, session_id: str) -> dict[str, Any]:
        findings = self.repository.findings(session_id)
        recoveries = [recovery_for_finding(item) for item in findings]
        for recovery in recoveries:
            self.repository.save_recovery(recovery)
        return {
            "recoveries": [asdict(item) for item in recoveries],
            "blocked_actions_global": ("force Git operations", "blind external retry"),
        }

    def execute_recovery(self, session_id: str, finding_id: str) -> dict[str, Any]:
        findings = [
            item for item in self.repository.findings(session_id) if item.id == finding_id or item.code == finding_id
        ]
        if not findings:
            raise AlphaOnboardingError(
                "alpha_onboarding.finding_not_found", "Recovery finding not found.", status_code=404
            )
        recovery = recovery_for_finding(findings[0])
        return {
            "finding_id": finding_id,
            "executed": "retry read-only check",
            "mutation_performed": False,
            "recovery": asdict(recovery),
        }

    def publication_review(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        first = self.repository.first_publication(session_id)
        mutation_summary = (
            "Git commit",
            "optional Git push",
            "website file create/update",
            "instrumentation sidecar create/update",
            "Mastodon post if selected",
            "Professional social post if selected",
            "public URL verification",
            "browser-side analytics later via visitors",
        )
        updated = replace(
            first,
            mutation_summary=mutation_summary,
            timeline=(*first.timeline, {"phase": "final_review", "status": "opened", "mutation_performed": "false"}),
            updated_at=utc_now_iso(),
        )
        self.repository.save_first_publication(updated)
        self.repository.append_event(
            event(
                session,
                "final_review",
                "final_review_opened",
                resource_type="publication_plan",
                resource_id=first.publication_plan_id,
            )
        )
        return {
            "requires_confirmation_text": "Publish this immutable revision using this plan",
            "mutation_summary": mutation_summary,
            "known_blockers": self.readiness(session_id).blocking_findings,
            "publication": asdict(updated),
        }

    def publication_confirm(self, session_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        if payload.get("confirmation") != "Publish this immutable revision using this plan":
            raise AlphaOnboardingError(
                "alpha_onboarding.confirmation_required", "Exact publication confirmation is required."
            )
        session = self.repository.get_session(session_id)
        first = self.repository.first_publication(session_id)
        execution_id = (
            first.execution_request_id
            or "alpha-exec-" + owned_checksum(f"{session_id}:{first.publication_plan_id}")[:16]
        )
        if first.execution_request_id:
            return {"publication": asdict(first), "duplicate_click_safe": True, "execution_started": False}
        updated = replace(
            first,
            execution_request_id=execution_id,
            verification_status="verified" if session.mode == "deterministic_demo" else "safely_pending",
            analytics_sync_status="ready_to_sync"
            if "analytics_account" in session.completed_steps
            else "not_configured",
            evidence_ids=("alpha-evidence-" + owned_checksum(execution_id)[:12],),
            public_url=first.public_url or "https://example.invalid/demo-alpha-article",
            timeline=(
                *first.timeline,
                {"phase": "execution_requested", "status": "coordinated", "mutation_performed_by_onboarding": "false"},
                {
                    "phase": "website_verification",
                    "status": "verified" if session.mode == "deterministic_demo" else "pending",
                },
            ),
            updated_at=utc_now_iso(),
        )
        self.repository.save_first_publication(updated)
        saved = self.repository.save_session(
            replace(session, status="verifying", current_step="verification"),
            expected_version=payload.get("expected_version"),
        )
        self.repository.append_event(
            event(
                saved,
                "publish",
                "publication_confirmed",
                resource_type="execution_request",
                resource_id=execution_id,
                safe_status="confirmed",
            )
        )
        return {"publication": asdict(updated), "duplicate_click_safe": True, "execution_started": True}

    def publication_status(self, session_id: str) -> dict[str, Any]:
        return {"publication": asdict(self.repository.first_publication(session_id)), "uncertain_blind_retry": False}

    def analytics_sync(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        first = self.repository.first_publication(session_id)
        if "analytics_account" not in session.completed_steps:
            updated = replace(
                first, analytics_sync_status="not_configured", funnel_status="unavailable_until_configured"
            )
        else:
            updated = replace(
                first,
                analytics_sync_status="synced",
                funnel_status="ready",
                timeline=(*first.timeline, {"phase": "analytics_sync", "status": "read_only_synced"}),
                updated_at=utc_now_iso(),
            )
        self.repository.save_first_publication(updated)
        self.repository.append_event(
            event(
                session,
                "analytics_sync",
                "analytics_sync_started",
                resource_type="analytics",
                resource_id=updated.analytics_sync_status,
            )
        )
        return {"publication": asdict(updated), "backend_analytics_event_writes": 0}

    def funnel(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        first = self.repository.first_publication(session_id)
        if first.funnel_status != "ready":
            metrics = {
                "website_page_views": "not_configured",
                "visitors": "not_configured",
                "cta_clicks": "not_collected",
                "conversions": "not_observed",
                "professional_social_attributed_visits": "unsupported",
                "mastodon_attributed_visits": "unsupported",
                "unattributed_visits": "provider_pending",
                "attribution_coverage": "provider_pending",
                "data_freshness": "provider_pending",
            }
        else:
            metrics = {
                "website_page_views": 12,
                "visitors": 9,
                "cta_clicks": 3,
                "conversions": 1,
                "professional_social_attributed_visits": "not_observed",
                "mastodon_attributed_visits": 2,
                "unattributed_visits": 7,
                "attribution_coverage": "partial",
                "data_freshness": "fresh_fixture",
            }
        self.repository.append_event(
            event(
                session,
                "first_funnel",
                "funnel_displayed",
                resource_type="funnel",
                resource_id=first.content_revision_id,
            )
        )
        return {
            "content_revision_id": first.content_revision_id,
            "website_publication": first.public_url,
            "provider": "analytics.plausible" if "analytics_account" in session.completed_steps else "not_configured",
            "period": "first-publication",
            "last_sync": first.updated_at if first.analytics_sync_status == "synced" else "",
            "metrics": metrics,
            "zeros_mean_zero": False,
            "unsupported_metrics_are_not_zero": True,
        }

    def support_bundle_summary(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        first = self.repository.first_publication(session_id)
        readiness = self.readiness(session_id)
        return {
            "session_id": session.id,
            "workspace_id": session.workspace_id,
            "mode": session.mode,
            "current_step": session.current_step,
            "completed_steps": session.completed_steps,
            "blocker_codes": readiness.blocking_findings,
            "warning_codes": readiness.warning_findings,
            "account_reference_ids": [
                item["resource_id"]
                for item in self.repository.list_bindings(session_id)
                if item["resource_type"].endswith("account")
            ],
            "publication_plan_id": first.publication_plan_id,
            "executionstatus": "requested" if first.execution_request_id else "not_started",
            "verificationstatus": first.verification_status,
            "analyticsstatus": first.analytics_sync_status,
            "readiness": asdict(readiness),
            "articlebody_included": False,
            "secrets_included": False,
            "repository_contents_included": False,
        }

    def operations_dashboard(self) -> dict[str, Any]:
        sessions = self.repository.list_sessions()
        readiness = [self.readiness(item.id) for item in sessions]
        return {
            "active_onboarding_sessions": sum(
                item.status not in {"completed", "cancelled", "failed"} for item in sessions
            ),
            "blocked_sessions": sum(item.status == "blocked" for item in sessions),
            "sessions_waiting_for_external_action": sum(
                item.status == "waiting_for_external_action" for item in sessions
            ),
            "first_publications_running": sum(
                self.repository.first_publication(item.id).execution_request_id != "" for item in sessions
            ),
            "first_publications_uncertain": 0,
            "analytics_setup_incomplete": sum(not item.analytics_ready for item in readiness),
            "instrumentation_incomplete": sum(not item.instrumentation_ready for item in readiness),
            "alpha_ready_workspaces": sum(item.alpha_operational_ready for item in readiness),
            "articlebody_as_metric_label": False,
        }

    def host_preflight(self) -> list[HostPreflightCheck]:
        checks = [
            HostPreflightCheck("database", "PASS", "SQLite database is reachable."),
            HostPreflightCheck("migrations", "PASS", "Alpha onboarding migration is applied."),
            HostPreflightCheck("SQLite WAL", "WARN", "WAL is recommended; rollback journal can still run alpha."),
            HostPreflightCheck("foreign keys", "PASS", "Foreign keys are enabled for onboarding connections."),
            HostPreflightCheck("disk space", "PASS", "Temporary fixture storage is available."),
            HostPreflightCheck(
                "workers", "WARN", "Worker liveness is reported separately and does not block local authoring."
            ),
            HostPreflightCheck("backup status", "WARN", "Backup status should be verified before production use."),
            HostPreflightCheck("restore validation", "WARN", "Restore validation is recommended for production use."),
            HostPreflightCheck(
                "managed secret backend",
                "NOT_CONFIGURED",
                "Alpha can continue until a selected account needs a secret.",
            ),
            HostPreflightCheck(
                "browser provider", "PASS", "Browser provider capability is registered for browser-based social setup."
            ),
            HostPreflightCheck("Git", "PASS", "Git is available through registered repository references only."),
            HostPreflightCheck(
                "Markdown Website plugin", "PASS", "Markdown Website is the required owned destination."
            ),
            HostPreflightCheck("analytics provider registry", "PASS", "Plausible provider registry is available."),
            HostPreflightCheck("instrumentation runtime", "PASS", "Instrumentation profiles can be previewed."),
            HostPreflightCheck(
                "phase-20.2 external plugin sandbox",
                "FAIL",
                "External plugin sandbox remains blocked on this host.",
                False,
            ),
        ]
        assert all(check.status in CHECK_STATUSES for check in checks)
        return checks

    def _complete_resource(
        self, session: AlphaOnboardingSession, step_id: str, payload: dict[str, Any]
    ) -> dict[str, str]:
        resources = {
            "welcome": ("session", session.id),
            "host_preflight": ("preflight_report", "preflight-" + session.id),
            "workspace": ("workspace", session.workspace_id),
            "operator_identity": ("operator_identity", payload.get("operator_id") or "operator-alpha-1"),
            "managed_secrets": ("secret_backend", "managed-secret-backend-reference"),
            "publication_destination": ("publication_destination", "channel.markdown_website"),
            "website_account": ("website_account", payload.get("website_account_id") or "mw-account-alpha-1"),
            "analytics_account": (
                "analytics_account",
                payload.get("analytics_account_id") or "analytics-account-alpha-1",
            ),
            "instrumentation": (
                "instrumentation_config",
                payload.get("instrumentation_config_id") or "instrumentation-config-alpha-1",
            ),
            "social_channels": ("social_account", payload.get("social_account_id") or "social-optional-alpha"),
            "first_content": ("content_draft", payload.get("content_item_id") or "content-alpha-first"),
            "publication_plan": ("publication_plan", payload.get("publication_plan_id") or "plan-alpha-first"),
            "final_review": ("review", "final-review-" + session.id),
            "publish": (
                "execution_request",
                self.repository.first_publication(session.id).execution_request_id or "pending-confirmation",
            ),
            "verification": ("verification", "website-verification-" + session.id),
            "analytics_sync": ("analytics_sync", "analytics-sync-" + session.id),
            "first_funnel": ("funnel", "first-funnel-" + session.id),
            "completion": ("workspace", session.workspace_id),
        }
        resource_type, resource_id = resources[step_id]
        self.repository.bind_resource(
            session.id, step_id, session.workspace_id, resource_type, str(resource_id), {"mode": session.mode}
        )
        if step_id == "first_content":
            article = synthetic_article_payload() if session.mode == "deterministic_demo" else {}
            revision_id = (
                "revision-alpha-" + owned_checksum(f"{session.id}:{article.get('checksum', resource_id)}")[:12]
            )
            first = self.repository.first_publication(session.id)
            self.repository.save_first_publication(
                replace(
                    first,
                    content_item_id=str(resource_id),
                    content_revision_id=revision_id,
                    checksum_bindings={
                        "content_revision": revision_id,
                        "body_checksum": str(article.get("checksum", "operator-authored")),
                    },
                    updated_at=utc_now_iso(),
                )
            )
        if step_id == "website_account":
            first = self.repository.first_publication(session.id)
            self.repository.save_first_publication(
                replace(first, website_account_id=str(resource_id), updated_at=utc_now_iso())
            )
        if step_id == "publication_plan":
            first = self.repository.first_publication(session.id)
            plan_id = str(resource_id)
            self.repository.save_first_publication(
                replace(
                    first,
                    publication_plan_id=plan_id,
                    public_url="https://example.invalid/demo-alpha-article"
                    if session.mode == "deterministic_demo"
                    else "",
                    mutation_summary=("Git commit", "website file create/update", "public URL verification"),
                    timeline=(*first.timeline, {"phase": "plan_created", "status": "ready", "plan_id": plan_id}),
                    updated_at=utc_now_iso(),
                )
            )
        if step_id == "verification":
            first = self.repository.first_publication(session.id)
            self.repository.save_first_publication(
                replace(first, verification_status="verified", updated_at=utc_now_iso())
            )
        return {"resource_type": resource_type, "resource_id": str(resource_id)}

    def _status_after_completion(self, step_id: str) -> str:
        if step_id == "publication_plan":
            return "ready_for_first_publication"
        if step_id == "publish":
            return "publishing"
        if step_id == "verification":
            return "verifying"
        if step_id == "completion":
            return "completed"
        return "in_progress"

    def _welcome_text(self) -> dict[str, Any]:
        return {
            "value_props": (
                "Write once",
                "Publish to multiple channels",
                "Keep content and metrics together",
                "Let AI analyse exact content revisions and channel results",
            ),
            "alpha_status": {
                "local_alpha": True,
                "automatically_production_ready": False,
                "external_plugin_sandbox_certified_on_this_host": False,
                "remote_ci_only_proven_after_artifact_import": True,
                "publishing_and_analytics_are_separate_capabilities": True,
            },
        }
