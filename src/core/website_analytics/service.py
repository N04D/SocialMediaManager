"""Application service for website analytics accounts, sync, attribution, and quality."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from integrations.website_analytics.fixtures import plausible_fixture_responses
from src.providers.analytics.plausible.provider import PlausibleWebsiteAnalyticsProvider, plausible_origin_reference

from .attribution import WebsiteAnalyticsAttributionService
from .errors import WebsiteAnalyticsError
from .models import (
    AnalyticsProviderOriginReference,
    ProviderCapability,
    WebsiteAnalyticsAccount,
    WebsiteAnalyticsEventMapping,
    stable_checksum,
    utc_now_iso,
)
from .persistence import DatabaseWebsiteAnalyticsRepository
from .provider import InMemorySafeHttpFacade
from .quality import WebsiteAnalyticsQualityService


class InMemorySecretReferenceService:
    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self.secrets = secrets or {"secret-plausible-fixture": "fixture-token"}

    def exists(self, reference_id: str) -> bool:
        return reference_id in self.secrets and not self.secrets[reference_id].startswith("raw:")


class ManagedSecretReferenceService:
    def __init__(self, facade) -> None:  # noqa: ANN001
        self.facade = facade

    def exists(self, reference_id: str) -> bool:
        if not reference_id.startswith("secretref:"):
            return False
        try:
            reference = self.facade.repository.get_reference(reference_id)
        except KeyError:
            return False
        return (
            reference.get("secret_type") in {"analytics_api_token", "generic_api_token"}
            and "plausible_stats_read" in reference.get("purpose_allowlist", ())
            and reference.get("status") in {"pending_approval", "active"}
        )


class WebsiteAnalyticsService:
    def __init__(
        self,
        *,
        database_path: Path | None = None,
        http_facade: InMemorySafeHttpFacade | None = None,
        secret_service: InMemorySecretReferenceService | ManagedSecretReferenceService | None = None,
    ) -> None:
        self.repository = DatabaseWebsiteAnalyticsRepository(database_path)
        managed_facade = None
        if secret_service is None and os.environ.get("SMM_MANAGED_SECRET_BACKEND"):
            from src.core.managed_secrets.service import PurposeBoundSecretReader, configured_managed_secret_facade

            managed_facade = configured_managed_secret_facade(database_path=database_path)
            secret_service = ManagedSecretReferenceService(managed_facade)
            plausible_secret_reader = PurposeBoundSecretReader(
                managed_facade, purpose="plausible_stats_read", consumer="plausible_stats_api"
            )
        else:
            plausible_secret_reader = None
        self.secret_service = secret_service or InMemorySecretReferenceService()
        self.origins = {plausible_origin_reference().id: plausible_origin_reference()}
        self.providers = {
            "analytics.plausible": PlausibleWebsiteAnalyticsProvider(
                http_facade=http_facade or InMemorySafeHttpFacade(plausible_fixture_responses()),
                secret_reader=plausible_secret_reader,
            )
        }
        self.attribution = WebsiteAnalyticsAttributionService()
        self.quality = WebsiteAnalyticsQualityService()

    def providers_payload(self, provider_id: str = "") -> dict[str, Any]:
        providers = []
        for provider in self.providers.values():
            if provider_id and provider.provider_id != provider_id:
                continue
            providers.append(
                {
                    "provider_id": provider.provider_id,
                    "provider_version": provider.provider_version,
                    "provider_family": provider.provider_family,
                    "execution_mode": provider.execution_mode,
                    "data_access": provider.data_access,
                    "capabilities": [asdict(item) for item in provider.capabilities()],
                }
            )
        return {"providers": providers, "read_only": True, "distribution_path": "built_in_in_process"}

    def origin_registry(self) -> dict[str, Any]:
        return {"origins": [asdict(origin) for origin in self.origins.values()], "host_owned": True}

    def create_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        origin_id = str(payload.get("origin_reference_id", "plausible-cloud"))
        origin = self._origin(origin_id)
        provider_id = str(payload.get("provider_id", "analytics.plausible"))
        if provider_id != origin.provider_id or provider_id not in self.providers:
            raise WebsiteAnalyticsError("website_analytics.provider_mismatch", "Provider and origin do not match.")
        secret_reference_id = str(payload.get("secret_reference_id", ""))
        if not self.secret_service.exists(secret_reference_id):
            raise WebsiteAnalyticsError("website_analytics.secret_reference_invalid", "Secret reference is invalid.")
        site = str(payload.get("site_identifier", "")).strip()
        if not site or "://" in site or "/" in site:
            raise WebsiteAnalyticsError("website_analytics.invalid_site", "Site identifier must be provider site ID.")
        now = utc_now_iso()
        account = WebsiteAnalyticsAccount(
            id=str(payload.get("id") or "analytics-account-" + stable_checksum(site + now)[:12]),
            workspace_id=str(payload.get("workspace_id", "workspace-1")),
            provider_id=provider_id,
            display_name=str(payload.get("display_name") or site),
            origin_reference_id=origin_id,
            site_identifier=site,
            secret_reference_id=secret_reference_id,
            timezone=str(payload.get("timezone", "UTC")),
            default_date_granularity=str(payload.get("default_date_granularity", "day")),
            enabled=bool(payload.get("enabled", True)),
            status="enabled" if payload.get("enabled", True) else "disabled",
            created_at=now,
            updated_at=now,
            version=1,
        )
        saved = self.repository.create_account(account)
        self.repository.ensure_sync_state(saved, "daily")
        return {"account": self._safe_account(saved), "origin": asdict(origin)}

    def list_accounts(self, workspace_id: str = "") -> dict[str, Any]:
        return {"accounts": [self._safe_account(item) for item in self.repository.list_accounts(workspace_id)]}

    def account(self, account_id: str) -> dict[str, Any]:
        return {"account": self._safe_account(self.repository.get_account(account_id))}

    def enable(self, account_id: str, *, enabled: bool, expected_version: int) -> dict[str, Any]:
        return {
            "account": self._safe_account(
                self.repository.update_account_status(account_id, enabled, expected_version=expected_version)
            )
        }

    def validate(self, account_id: str) -> dict[str, Any]:
        account = self.repository.get_account(account_id)
        provider = self.providers[account.provider_id]
        return provider.validate_account(account)

    def doctor(self, account_id: str) -> dict[str, Any]:
        account = self.repository.get_account(account_id)
        validation = self.validate(account_id)
        syncs = self.repository.list_sync_states(account.id)
        return {
            "account_id": account_id,
            "checks": [
                {"name": "credential reference", "status": "PASS" if account.secret_reference_id else "FAIL"},
                {"name": "origin", "status": "PASS" if account.origin_reference_id in self.origins else "FAIL"},
                {
                    "name": "HTTPS",
                    "status": "PASS" if self._origin(account.origin_reference_id).scheme == "https" else "WARN",
                },
                {"name": "authentication", "status": "PASS" if validation["valid"] else "FAIL"},
                {"name": "site access", "status": "PASS" if validation["site_access"] else "FAIL"},
                {"name": "response schema", "status": "PASS" if validation["schema"] == "valid" else "FAIL"},
                {"name": "supported metrics", "status": "PASS"},
                {"name": "attribution dimensions", "status": "PASS"},
                {"name": "event mappings", "status": "PASS" if self.repository.list_mappings(account_id) else "WARN"},
                {"name": "cursor", "status": "PASS" if syncs else "WARN"},
                {"name": "last sync", "status": "PASS" if any(item.last_successful_at for item in syncs) else "WARN"},
                {"name": "rate limit state", "status": "PASS"},
                {
                    "name": "data freshness",
                    "status": "PASS" if self.quality_report(account_id)["quality"]["status"] != "failed" else "FAIL",
                },
            ],
            "read_only": True,
        }

    def mappings(self, account_id: str) -> dict[str, Any]:
        return {"mappings": [asdict(item) for item in self.repository.list_mappings(account_id)]}

    def put_mappings(self, account_id: str, mappings: list[dict[str, Any]]) -> dict[str, Any]:
        account = self.repository.get_account(account_id)
        records = [
            WebsiteAnalyticsEventMapping(
                id=str(item.get("id") or f"mapping-{stable_checksum(account_id + str(index))[:8]}"),
                workspace_id=account.workspace_id,
                account_id=account_id,
                provider_event_name=str(item.get("provider_event_name", "")),
                provider_property_filters=dict(item.get("provider_property_filters", {})),
                internal_event_type=str(item.get("internal_event_type", "custom")),
                cta_id=str(item.get("cta_id", "")),
                conversion_type=str(item.get("conversion_type", "")),
                conversion_value_policy=str(item.get("conversion_value_policy", "none")),
                enabled=bool(item.get("enabled", True)),
                version=int(item.get("version", 1)),
            )
            for index, item in enumerate(mappings)
        ]
        return {
            "mappings": [
                asdict(item) for item in self.repository.put_mappings(account_id, account.workspace_id, records)
            ]
        }

    def sync(self, account_id: str, *, worker_id: str = "manual-sync", claim: bool = True) -> dict[str, Any]:
        account = self.repository.get_account(account_id)
        if not account.enabled:
            raise WebsiteAnalyticsError("website_analytics.account_disabled", "Analytics account is disabled.")
        state = self.repository.ensure_sync_state(account, "daily")
        if claim:
            state = self.repository.schedule_manual_sync(state.id)
        if claim and not self.repository.claim_sync_state(state.id, worker_id, utc_now_iso()):
            raise WebsiteAnalyticsError("website_analytics.sync_busy", "Analytics sync is already claimed.")
        provider = self.providers[account.provider_id]
        all_observations = []
        ingested = []
        provider_warnings: list[str] = []
        try:
            for query in provider.plan_sync(account, "incremental"):
                observations, meta = provider.collect(account, query)
                provider_warnings.extend(meta.get("warnings", ()))
                for observation in observations:
                    observation = observation.__class__(
                        **{
                            **asdict(observation),
                            "attribution_quality": self.attribution.attribute(
                                "pending", observation, self._known_bindings()
                            ).quality_status,
                        }
                    )
                    attribution = self.attribution.attribute("pending", observation, self._known_bindings())
                    result = self.repository.ingest_provider_observation(
                        account.workspace_id, account.id, observation, attribution
                    )
                    ingested.append(result)
                    all_observations.append(observation)
            quality = self.quality.build_report(
                account.id, account.site_identifier, all_observations, provider_warnings=tuple(provider_warnings)
            )
            self.repository.save_quality_report(account.workspace_id, quality)
            high_watermark = max((item.period_end for item in all_observations), default=utc_now_iso())
            self.repository.complete_sync_state(state.id, worker_id, cursor="completed", high_watermark=high_watermark)
        except WebsiteAnalyticsError as exc:
            self.repository.complete_sync_state(
                state.id,
                worker_id,
                cursor=state.cursor,
                high_watermark=state.high_watermark,
                status="failed",
                error_code=exc.code,
            )
            raise
        return {
            "account_id": account_id,
            "status": "completed",
            "observations": ingested,
            "corrections": len([item for item in ingested if item["correction"]]),
            "provider_writes": 0,
        }

    def sync_status(self, account_id: str) -> dict[str, Any]:
        return {"sync_states": [asdict(item) for item in self.repository.list_sync_states(account_id)]}

    def quality_report(self, account_id: str) -> dict[str, Any]:
        account = self.repository.get_account(account_id)
        report = self.repository.latest_quality(account_id) or self.quality.build_report(
            account.id, account.site_identifier, []
        )
        return {"quality": asdict(report)}

    def provider_breakdown(self, content_item_id: str) -> dict[str, Any]:
        return {
            "content_item_id": content_item_id,
            "provider": "analytics.plausible",
            "readmodel": self.repository.owned_repository.rebuild_readmodel(
                "workspace-1", "ContentFunnelReadModel", content_item_id
            )["payload"],
            "data_quality": "provider-backed",
            "causality_claimed": False,
        }

    def analytics_health(self) -> dict[str, Any]:
        health = self.repository.analytics_health()
        health["publishing_ready"] = True
        health["analytics_ready"] = health["data_freshness"] in {"fresh", "not_configured"}
        health["analytics_degraded"] = health["provider_availability"] == "degraded"
        return health

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return self.providers["analytics.plausible"].capabilities()

    def _origin(self, origin_id: str) -> AnalyticsProviderOriginReference:
        origin = self.origins.get(origin_id)
        if not origin or not origin.enabled:
            raise WebsiteAnalyticsError("website_analytics.origin_not_allowed", "Analytics origin is not allowlisted.")
        if origin.scheme != "https" and origin.host not in {"127.0.0.1", "localhost"}:
            raise WebsiteAnalyticsError("website_analytics.https_required", "Analytics origin must use HTTPS.")
        return origin

    def _safe_account(self, account: WebsiteAnalyticsAccount) -> dict[str, Any]:
        payload = asdict(account)
        payload["secret_reference_id"] = account.secret_reference_id
        payload["has_secret_reference"] = bool(account.secret_reference_id)
        return payload

    def _known_bindings(self) -> dict[str, dict[str, str]]:
        return {
            "attr-social-a-owned-1": {
                "website_target_id": "target-website-owned-1",
                "website_attempt_id": "attempt-website-owned-1",
                "content_item_id": "content-owned-1",
                "content_revision_id": "revision-owned-1",
                "campaign_id": "campaign-owned-1",
                "source_social_target_id": "target-social-a-owned-1",
            },
            "attr-social-b-owned-1": {
                "website_target_id": "target-website-owned-1",
                "website_attempt_id": "attempt-website-owned-1",
                "content_item_id": "content-owned-1",
                "content_revision_id": "revision-owned-1",
                "campaign_id": "campaign-owned-1",
                "source_social_target_id": "target-social-b-owned-1",
            },
        }


__all__ = ["InMemorySecretReferenceService", "WebsiteAnalyticsService"]
