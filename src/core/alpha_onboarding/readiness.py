"""Alpha setup readiness calculations."""

from __future__ import annotations

from dataclasses import asdict

from src.core.owned_publication.operations import ProductionReadinessService

from .models import AlphaOnboardingFinding, AlphaOnboardingSession, AlphaSetupReadinessReport, utc_now_iso
from .steps import OPTIONAL_STEPS, step_registry


class AlphaReadinessService:
    def __init__(self, *, production_service: ProductionReadinessService | None = None) -> None:
        self.production_service = production_service

    def calculate(
        self,
        session: AlphaOnboardingSession,
        findings: list[AlphaOnboardingFinding],
        *,
        analytics_configured: bool = False,
        instrumentation_configured: bool = False,
        website_account_ready: bool = False,
        first_revision_exists: bool = False,
        publication_plan_valid: bool = False,
        first_publication_safe_state: bool = False,
        first_publication_completed: bool = False,
        first_funnel_ready: bool = False,
    ) -> AlphaSetupReadinessReport:
        registry = step_registry(analytics_configured=analytics_configured)
        required_steps = {step_id for step_id, step in registry.items() if step.required}
        completed = set(session.completed_steps)
        blocking = tuple(
            finding.code for finding in findings if finding.severity == "blocking" and finding.status == "open"
        )
        warnings = tuple(
            finding.code for finding in findings if finding.severity != "blocking" and finding.status == "open"
        )
        required_complete = len(required_steps & completed)
        optional_complete = len(OPTIONAL_STEPS & completed)
        setup_progress = round((len(completed) / max(len(registry), 1)) * 100, 2)
        publishing_ready = website_account_ready and first_revision_exists and publication_plan_valid and not blocking
        alpha_operational_ready = (
            "workspace" in completed
            and website_account_ready
            and first_revision_exists
            and publication_plan_valid
            and first_publication_safe_state
            and not blocking
        )
        production = self._production_readiness()
        return AlphaSetupReadinessReport(
            session_id=session.id,
            workspace_id=session.workspace_id,
            setup_progress=setup_progress,
            required_steps_complete=required_complete,
            optional_steps_complete=optional_complete,
            blocking_findings=blocking,
            warning_findings=warnings,
            website_ready=website_account_ready,
            social_ready="optional_not_configured"
            if "social_channels" in session.skipped_optional_steps
            else "not_configured",
            instrumentation_ready=instrumentation_configured,
            analytics_ready=analytics_configured and instrumentation_configured,
            first_publication_ready=publishing_ready,
            first_publication_completed=first_publication_completed,
            first_funnel_ready=first_funnel_ready,
            alpha_setup_status=session.status,
            alpha_operational_ready=alpha_operational_ready,
            publishing_ready=publishing_ready,
            analytics_status="configured" if analytics_configured else "not_configured",
            analytics_ready_status="ready" if analytics_configured and instrumentation_configured else "unaffected",
            instrumentation_ready_status="ready" if instrumentation_configured else "not_configured",
            ci_certification_ready=bool(production.get("ci_certification_ready", False)),
            external_plugin_sandbox_ready=False,
            production_ready=bool(production.get("production_ready", False)) and False,
            remote_ci_status=str(production.get("remote_ci_artifact_status") or "artifact_not_imported"),
            generated_at=utc_now_iso(),
        )

    def _production_readiness(self) -> dict[str, object]:
        if not self.production_service:
            return {
                "production_ready": False,
                "ci_certification_ready": False,
                "remote_ci_artifact_status": "artifact_not_imported",
                "external_plugin_sandbox_ready": False,
            }
        try:
            report = self.production_service.readiness()
            return asdict(report) if not isinstance(report, dict) else report
        except Exception:
            return {
                "production_ready": False,
                "ci_certification_ready": False,
                "remote_ci_artifact_status": "artifact_not_imported",
                "external_plugin_sandbox_ready": False,
            }
