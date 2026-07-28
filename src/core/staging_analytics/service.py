"""Application service for staging analytics certification."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from integrations.staging_analytics.browser_certification import StagingBrowserCertificationRunner
from integrations.staging_analytics.scenarios import staging_account_payload, staging_profile_payload
from integrations.website_analytics.scenarios import event_mappings_payload
from src.core.website_analytics.models import ProviderMetricObservation
from src.core.website_analytics.service import WebsiteAnalyticsService
from src.core.website_instrumentation.contracts import WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION
from src.core.website_instrumentation.manifests import build_manifest
from src.core.website_instrumentation.service import WebsiteInstrumentationService

from .contracts import STAGING_ANALYTICS_CERTIFICATION_VERSION
from .errors import StagingAnalyticsError
from .models import (
    StagingAnalyticsCertificationProfile,
    StagingAnalyticsCertificationReport,
    StagingAnalyticsCertificationRun,
    opaque_run_id,
    report_with_checksum,
    safe_url_reference,
    stable_checksum,
    utc_now_iso,
    window_end,
)
from .persistence import DatabaseStagingAnalyticsRepository
from .polling import StagingProviderPollingPlanner
from .profiles import get_staging_origin, get_synthetic_page_profile, list_staging_origins, list_synthetic_page_profiles
from .reconciliation import reconcile_provider_observations

STAGING_ACCOUNT_CLASSIFICATION = {
    "analytics-account-plausible": {"environment": "staging", "synthetic_testing_allowed": True},
    "analytics-account-production": {"environment": "production", "synthetic_testing_allowed": False},
}


class StagingAnalyticsCertificationService:
    def __init__(
        self, *, database_path: Path | None = None, browser_runner: StagingBrowserCertificationRunner | None = None
    ) -> None:
        self.repository = DatabaseStagingAnalyticsRepository(database_path)
        self.analytics = WebsiteAnalyticsService(database_path=database_path)
        self.instrumentation = WebsiteInstrumentationService(database_path=database_path)
        self.browser_runner = browser_runner or StagingBrowserCertificationRunner()

    def origins(self) -> dict[str, Any]:
        return {"origins": [asdict(item) for item in list_staging_origins()], "host_owned": True}

    def synthetic_pages(self) -> dict[str, Any]:
        return {"profiles": [asdict(item) for item in list_synthetic_page_profiles()], "synthetic_only": True}

    def create_profile(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or staging_profile_payload()
        origin = self._validate_origin(str(payload.get("staging_origin_reference_id", "")))
        page = self._validate_synthetic_page(str(payload.get("synthetic_page_profile_id", "")), origin)
        account_id = str(payload.get("analytics_account_id", ""))
        self._ensure_staging_account(account_id)
        now = utc_now_iso()
        profile = StagingAnalyticsCertificationProfile(
            id=str(payload.get("id", "staging-cert-profile-1")),
            workspace_id=str(payload.get("workspace_id", "workspace-1")),
            staging_origin_reference_id=origin.id,
            analytics_account_id=account_id,
            synthetic_page_profile_id=page.id,
            expected_event_mapping_ids=tuple(payload.get("expected_event_mapping_ids", ())),
            browser_name=str(payload.get("browser_name", "chromium")),
            browser_mode=str(payload.get("browser_mode", "headless")),
            maximum_wait_seconds=min(300, int(payload.get("maximum_wait_seconds", 30))),
            initial_poll_delay_seconds=min(30, int(payload.get("initial_poll_delay_seconds", 1))),
            maximum_poll_delay_seconds=min(120, int(payload.get("maximum_poll_delay_seconds", 8))),
            polling_multiplier=min(4.0, float(payload.get("polling_multiplier", 2.0))),
            maximum_poll_attempts=min(20, int(payload.get("maximum_poll_attempts", 4))),
            correction_window=str(payload.get("correction_window", "recent_completed_periods")),
            enabled=bool(payload.get("enabled", True)),
            version=1,
            created_at=now,
            updated_at=now,
        )
        return {"profile": asdict(self.repository.save_profile(profile)), "valid": True}

    def list_profiles(self) -> dict[str, Any]:
        return {"profiles": [asdict(item) for item in self.repository.list_profiles()]}

    def profile(self, profile_id: str) -> dict[str, Any]:
        return {"profile": asdict(self.repository.get_profile(profile_id))}

    def validate_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self.repository.get_profile(profile_id)
        origin = self._validate_origin(profile.staging_origin_reference_id)
        page = self._validate_synthetic_page(profile.synthetic_page_profile_id, origin)
        self._ensure_staging_account(profile.analytics_account_id)
        return {
            "profile_id": profile_id,
            "valid": True,
            "environment": origin.environment,
            "synthetic_only": origin.synthetic_only,
            "page_path": page.page_path,
        }

    def create_run(
        self, profile_id: str, *, execute_staging: bool = False, idempotency_key: str = ""
    ) -> dict[str, Any]:
        profile = self._ensure_profile(profile_id)
        origin = self._validate_origin(profile.staging_origin_reference_id)
        page = self._validate_synthetic_page(profile.synthetic_page_profile_id, origin)
        run_id = opaque_run_id(profile.workspace_id, profile.id, idempotency_key or utc_now_iso())
        now = utc_now_iso()
        browser_config = self._browser_config(profile, run_id)
        manifest_id = str(browser_config["manifest"]["id"])
        events = tuple(
            {
                "event_name": item["event_name"],
                "event_type": f"synthetic_{item['event_type']}",
                "smm_synthetic_run_id": run_id,
                "mapping_version": "1",
            }
            for item in browser_config["events"]
            if item["event_type"] in {"cta_click", "conversion"}
        )
        checksum = stable_checksum({"profile_id": profile.id, "run_id": run_id, "events": events})
        run = StagingAnalyticsCertificationRun(
            id="stg-run-" + checksum[:16],
            workspace_id=profile.workspace_id,
            profile_id=profile.id,
            run_id=run_id,
            status="prepared" if not execute_staging else "browser_starting",
            page_url_reference=safe_url_reference(origin.page_url(page.page_path)),
            analytics_account_id=profile.analytics_account_id,
            instrumentation_manifest_id=manifest_id,
            expected_event_bindings=events,
            expected_attribution_id="attr-" + run_id[-12:],
            browser_evidence_ids=(),
            provider_observation_ids=(),
            reconciliation_status="not_started",
            started_at=now,
            browser_completed_at="",
            provider_observed_at="",
            completed_at="",
            safe_error_code="",
            checksum=checksum,
        )
        saved = self.repository.save_run(run)
        if execute_staging:
            return self.execute_browser_phase(saved.id)
        return {"run": asdict(saved), "deterministic_only": True, "staging_provider_certification_not_run": True}

    def execute_browser_phase(self, run_id: str) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        profile = self.repository.get_profile(run.profile_id)
        origin = self._validate_origin(profile.staging_origin_reference_id)
        page = self._validate_synthetic_page(profile.synthetic_page_profile_id, origin)
        config = self._browser_config(profile, run.run_id)
        result = self.browser_runner.run(
            run_id=run.run_id, origin_reference=origin, page_profile=page, browser_config=config
        )
        evidence_ids = []
        for evidence in result["evidence"]:
            self.repository.save_browser_evidence(run.workspace_id, evidence)
            evidence_ids.append(evidence.id)
        updated = self._replace_run(
            run,
            status="awaiting_provider",
            browser_evidence_ids=tuple(evidence_ids),
            browser_completed_at=utc_now_iso(),
        )
        return {
            "run": asdict(updated),
            "browser_evidence": result["evidence_payload"],
            "browser_version": result["browser_version"],
            "backend_provider_writes": 0,
            "browser_origin_events": True,
            "events": result["events"],
        }

    def reconcile_run(self, run_id: str, *, observed_events: list[dict[str, str]] | None = None) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        expected = tuple(item["event_name"] for item in run.expected_event_bindings)
        observations = observed_events if observed_events is not None else []
        result = reconcile_provider_observations(run_id=run.run_id, expected_events=expected, observations=observations)
        self.repository.save_reconciliation(run.workspace_id, result)
        status = {
            "observed": "provider_observed",
            "partially_observed": "provider_partially_observed",
            "not_observed": "awaiting_provider",
            "conflicting": "failed",
        }[result.quality_status]
        updated = self._replace_run(
            run,
            status=status,
            reconciliation_status=result.quality_status,
            provider_observation_ids=result.observation_ids,
            provider_observed_at=result.reconciled_at if result.observed_events else "",
            completed_at=result.reconciled_at if result.quality_status == "observed" else "",
        )
        report = self._build_report(updated, result)
        return {"run": asdict(updated), "reconciliation": asdict(result), "report": asdict(report)}

    def mark_uncertain(self, run_id: str) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        updated = self._replace_run(run, status="browser_mutation_uncertain", safe_error_code="browser_event_uncertain")
        return {"run": asdict(updated), "no_blind_retry": True}

    def polling_plan(self, profile_id: str, run_id: str) -> dict[str, Any]:
        profile = self.repository.get_profile(profile_id)
        run = self.repository.get_run(run_id)
        planner = StagingProviderPollingPlanner(
            initial=profile.initial_poll_delay_seconds,
            maximum=profile.maximum_poll_delay_seconds,
            multiplier=profile.polling_multiplier,
            attempts=profile.maximum_poll_attempts,
        )
        query = planner.plan_query(
            account_id=profile.analytics_account_id,
            run_id=run.run_id,
            expected_event_names=tuple(item["event_name"] for item in run.expected_event_bindings),
            page_path=self._validate_synthetic_page(
                profile.synthetic_page_profile_id, self._validate_origin(profile.staging_origin_reference_id)
            ).page_path,
            attribution_id=run.expected_attribution_id,
            period_start=run.started_at,
            period_end=window_end(run.started_at, profile.maximum_wait_seconds),
        )
        return {"delays": planner.delays, "query": asdict(query), "no_tight_loop": True}

    def list_runs(self) -> dict[str, Any]:
        return {"runs": [asdict(item) for item in self.repository.list_runs()]}

    def run(self, run_id: str) -> dict[str, Any]:
        return {"run": asdict(self.repository.get_run(run_id))}

    def evidence(self, run_id: str) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        return {"evidence": [asdict(item) for item in self.repository.list_browser_evidence(run.run_id)]}

    def report(self, run_id: str) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        return {"report": self.repository.latest_report(run.run_id) or self._not_run_report(run)}

    def operations_health(self) -> dict[str, Any]:
        return self.repository.health()

    def support_bundle(self) -> dict[str, Any]:
        health = self.operations_health()
        profiles = [item.id for item in self.repository.list_profiles()]
        runs = [
            {
                "run_id": item.run_id,
                "status": item.status,
                "reconciliation_status": item.reconciliation_status,
                "report_checksum": (self.repository.latest_report(item.run_id) or {}).get("checksum", ""),
            }
            for item in self.repository.list_runs()
        ]
        files = {
            "instrumentation.json": {
                "framework_version": STAGING_ANALYTICS_CERTIFICATION_VERSION,
                "profile_ids": profiles,
                "runs": runs,
                "health": health,
                "safe_event_names": ("SMM CTA Click", "SMM Conversion"),
                "safe_property_names": ("page_id", "publication_id", "smm_synthetic_run_id", "cta_id", "conversion_id"),
            }
        }
        return {
            "bundle": {
                "manifest": {
                    "files": {name: stable_checksum(payload) for name, payload in files.items()},
                    "forbidden_data_included": False,
                    "contains_database": False,
                    "contains_event_payload_values": False,
                },
                "files": files,
            }
        }

    def deterministic_certification(self, profile_id: str = "staging-cert-profile-1") -> dict[str, Any]:
        profile = self._ensure_profile(profile_id)
        run_payload = self.create_run(profile.id)
        browser_payload = self.execute_browser_phase(run_payload["run"]["id"])
        events = []
        for event in browser_payload["events"]:
            props = {str(key): str(value) for key, value in dict(event["props"]).items()}
            events.append({"event_name": str(event["name"]), **props})
        first = self.reconcile_run(browser_payload["run"]["id"], observed_events=[])
        delayed_status = first["reconciliation"]["quality_status"]
        final = self.reconcile_run(browser_payload["run"]["id"], observed_events=events)
        return {
            "deterministic_certification_passed": final["report"]["certification_passed"],
            "staging_provider_certification_passed": False,
            "staging_provider_certification_not_run": True,
            "delayed_status": delayed_status,
            "run": final["run"],
            "report": final["report"],
            "backend_provider_writes": 0,
            "support_bundle": self.support_bundle()["bundle"]["manifest"],
        }

    def _ensure_profile(self, profile_id: str) -> StagingAnalyticsCertificationProfile:
        try:
            return self.repository.get_profile(profile_id)
        except StagingAnalyticsError:
            self.create_profile(staging_profile_payload() | {"id": profile_id})
            return self.repository.get_profile(profile_id)

    def _validate_origin(self, origin_id: str):
        try:
            origin = get_staging_origin(origin_id)
        except KeyError as exc:
            raise StagingAnalyticsError("staging_analytics.origin", "Unknown staging origin reference.") from exc
        if origin.environment != "staging" or not origin.synthetic_only or not origin.enabled:
            raise StagingAnalyticsError(
                "staging_analytics.production_origin_blocked", "Only synthetic staging origins are allowed."
            )
        return origin

    def _validate_synthetic_page(self, page_profile_id: str, origin: Any):
        try:
            page = get_synthetic_page_profile(page_profile_id)
        except KeyError as exc:
            raise StagingAnalyticsError("staging_analytics.synthetic_page", "Unknown synthetic page profile.") from exc
        if page.page_path not in origin.allowed_page_paths or not page.page_path.startswith("/synthetic/"):
            raise StagingAnalyticsError("staging_analytics.page_path", "Synthetic page path is not allowlisted.")
        return page

    def _ensure_staging_account(self, account_id: str):
        classification = STAGING_ACCOUNT_CLASSIFICATION.get(
            account_id, {"environment": "production", "synthetic_testing_allowed": False}
        )
        if classification["environment"] != "staging" or not classification["synthetic_testing_allowed"]:
            raise StagingAnalyticsError(
                "staging_analytics.production_account_blocked", "Only staging analytics accounts are allowed."
            )
        try:
            account = self.analytics.repository.get_account(account_id)
        except Exception:
            account = self.analytics.create_account(staging_account_payload() | {"id": account_id})["account"]
        if not dict(account if isinstance(account, dict) else asdict(account)).get("enabled", True):
            raise StagingAnalyticsError("staging_analytics.account_disabled", "Staging analytics account is disabled.")
        if not self.analytics.repository.list_mappings(account_id):
            self.analytics.put_mappings(account_id, event_mappings_payload())
        return account

    def _browser_config(self, profile: StagingAnalyticsCertificationProfile, run_id: str) -> dict[str, Any]:
        config_id = "staging-instrumentation-" + profile.id
        try:
            config = self.instrumentation.config(config_id)["config"]
        except Exception:
            config = self.instrumentation.create_config(
                {
                    "id": config_id,
                    "workspace_id": profile.workspace_id,
                    "analytics_account_id": profile.analytics_account_id,
                    "profile_id": "plausible_generic",
                    "consent_mode": get_synthetic_page_profile(profile.synthetic_page_profile_id).consent_mode,
                }
            )["config"]
        manifest = build_manifest(
            self.instrumentation.repository.get_config(config["id"]),
            {
                "content_item_id": "synthetic-content",
                "content_revision_id": "synthetic-revision",
                "publication_target_id": "synthetic-target",
                "publication_attempt_id": "synthetic-attempt",
                "campaign_id": "synthetic-campaign",
                "public_url": get_staging_origin(profile.staging_origin_reference_id).page_url(
                    get_synthetic_page_profile(profile.synthetic_page_profile_id).page_path
                ),
                "cta_id": "synthetic-cta",
                "conversion_id": "synthetic-conversion",
            },
        )
        return {
            "version": WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION,
            "consentMode": manifest.consent_mode,
            "pageContext": asdict(manifest.page_context),
            "events": list(manifest.expected_events),
            "syntheticRunId": run_id,
            "manifest": asdict(manifest),
            "synthetic": {
                "cta_id": manifest.cta_bindings[0]["id"],
                "conversion_id": manifest.conversion_bindings[0]["id"],
            },
        }

    def _replace_run(self, run: StagingAnalyticsCertificationRun, **changes: Any) -> StagingAnalyticsCertificationRun:
        payload = asdict(run) | changes
        payload["checksum"] = stable_checksum({key: value for key, value in payload.items() if key != "checksum"})
        return self.repository.save_run(StagingAnalyticsCertificationRun(**payload))

    def _build_report(self, run: StagingAnalyticsCertificationRun, result) -> StagingAnalyticsCertificationReport:
        profile = self.repository.get_profile(run.profile_id)
        observed = result.quality_status == "observed"
        report = StagingAnalyticsCertificationReport(
            framework_version=STAGING_ANALYTICS_CERTIFICATION_VERSION,
            profile_id=profile.id,
            run_id=run.run_id,
            commit_sha="fixture-local",
            staging_origin_reference_id=profile.staging_origin_reference_id,
            analytics_provider_id="analytics.plausible",
            analytics_account_id=profile.analytics_account_id,
            browser_name=profile.browser_name,
            browser_version="chromium",
            browser_mode=profile.browser_mode,
            instrumentation_version=WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION,
            synthetic_marker_verified=bool(run.browser_evidence_ids),
            noindex_verified=bool(run.browser_evidence_ids),
            consent_verified=bool(run.browser_evidence_ids),
            browser_events_verified=len(run.browser_evidence_ids) >= 2,
            provider_observed_status=result.quality_status,
            observed_event_count=len(result.observed_events),
            expected_event_count=len(result.expected_events),
            mapping_status="aligned" if not result.mapping_mismatches else "mapping_mismatch",
            attribution_status=result.attribution_status,
            data_quality=result.quality_status,
            required_secrets_present=True,
            live_staging_executed=False,
            deterministic_only=True,
            started_at=run.started_at,
            completed_at=result.reconciled_at,
            safe_warnings=("staging_provider_certification_not_run",),
            certification_passed=observed and len(run.browser_evidence_ids) >= 2,
            checksum="",
        )
        saved = report_with_checksum(report)
        return self.repository.save_report(run.workspace_id, saved)

    def _not_run_report(self, run: StagingAnalyticsCertificationRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "provider_observed_status": "staging_provider_certification_not_run",
            "deterministic_only": True,
            "certification_passed": False,
            "checksum": "",
        }


def observation_from_synthetic_event(account_id: str, event: dict[str, str]) -> ProviderMetricObservation:
    now = utc_now_iso()
    return ProviderMetricObservation(
        provider_id="analytics.plausible",
        provider_account_id=account_id,
        site_identifier="staging.example.test",
        metric_key="website.conversions" if event["event_name"] == "SMM Conversion" else "website.cta_clicks",
        value=1,
        unit="count",
        period_start=now,
        period_end=now,
        dimensions=event,
        source_fingerprint=stable_checksum(event),
        provider_query_fingerprint=stable_checksum({"synthetic": event.get("smm_synthetic_run_id")}),
        collected_at=now,
        aggregation="sum",
        content_item_id="synthetic-content",
        content_revision_id="synthetic-revision",
        website_target_id="synthetic-target",
        website_attempt_id="synthetic-attempt",
        campaign_id="synthetic-campaign",
        attribution_quality="exact_attribution_id",
    )


__all__ = ["StagingAnalyticsCertificationService", "observation_from_synthetic_event"]
