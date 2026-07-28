"""Application service for website instrumentation."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from integrations.website_instrumentation.scenarios import default_snapshot_payload
from src.core.website_analytics.service import WebsiteAnalyticsService

from .consent import VALID_CONSENT_MODES
from .contracts import WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION
from .errors import WebsiteInstrumentationError
from .events import SMM_CONVERSION_EVENT, SMM_CTA_EVENT, SMM_OUTBOUND_EVENT, property_schema_payload
from .manifests import build_manifest, manifest_payload
from .models import WebsiteInstrumentationConfig, utc_now_iso
from .persistence import DatabaseWebsiteInstrumentationRepository
from .profiles import get_profile, list_profiles
from .quality import build_quality_report
from .renderer import render_frontmatter_binding, render_sidecar_bytes, render_static_page
from .verification import WebsiteInstrumentationVerifier, provider_observed_status, verification_payload


class WebsiteInstrumentationService:
    def __init__(self, *, database_path: Path | None = None) -> None:
        self.repository = DatabaseWebsiteInstrumentationRepository(database_path)
        self.analytics = WebsiteAnalyticsService(database_path=database_path)
        self.verifier = WebsiteInstrumentationVerifier()
        for profile in list_profiles():
            self.repository.save_profile(asdict(profile))

    def profiles_payload(self, profile_id: str = "") -> dict[str, Any]:
        profiles = [asdict(item) for item in list_profiles() if not profile_id or item.id == profile_id]
        return {
            "framework_version": WEBSITE_ANALYTICS_INSTRUMENTATION_VERSION,
            "profiles": profiles,
            "property_schema": property_schema_payload(),
        }

    def create_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(payload.get("profile_id", "plausible_generic"))
        get_profile(profile_id)
        consent_mode = str(payload.get("consent_mode", "after_external_consent"))
        if consent_mode not in VALID_CONSENT_MODES:
            raise WebsiteInstrumentationError("website_instrumentation.consent", "Invalid consent mode.")
        if str(payload.get("expected_script_origin_reference", "smm-managed-assets")) not in {"smm-managed-assets"}:
            raise WebsiteInstrumentationError(
                "website_instrumentation.script_origin", "Script origin is not allowlisted."
            )
        now = utc_now_iso()
        config = WebsiteInstrumentationConfig(
            id=str(payload.get("id", "instrumentation-config-owned-1")),
            workspace_id=str(payload.get("workspace_id", "workspace-1")),
            website_account_id=str(payload.get("website_account_id", "mw-account-owned-1")),
            analytics_account_id=str(payload.get("analytics_account_id", "analytics-account-plausible")),
            profile_id=profile_id,
            consent_mode=consent_mode,
            enabled=bool(payload.get("enabled", True)),
            cta_event_name=str(payload.get("cta_event_name", SMM_CTA_EVENT)),
            outbound_event_name=str(payload.get("outbound_event_name", SMM_OUTBOUND_EVENT)),
            conversion_event_name=str(payload.get("conversion_event_name", SMM_CONVERSION_EVENT)),
            attribution_policy=str(payload.get("attribution_policy", "current_page_allowed_params")),
            script_delivery_mode=str(payload.get("script_delivery_mode", "external_reference")),
            expected_script_origin_reference=str(payload.get("expected_script_origin_reference", "smm-managed-assets")),
            version=1,
            created_at=now,
            updated_at=now,
        )
        return {"config": asdict(self.repository.create_config(config))}

    def list_configs(self) -> dict[str, Any]:
        return {"configs": [asdict(item) for item in self.repository.list_configs()]}

    def config(self, config_id: str) -> dict[str, Any]:
        return {"config": asdict(self.repository.get_config(config_id))}

    def update_config(self, config_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "config": asdict(
                self.repository.update_config(
                    config_id, payload, expected_version=int(payload.get("expected_version", 0))
                )
            )
        }

    def preview_manifest(
        self, config_id: str = "instrumentation-config-owned-1", snapshot: dict[str, str] | None = None
    ) -> dict:
        config = self._ensure_config(config_id)
        manifest = build_manifest(config, snapshot or default_snapshot_payload())
        self.repository.save_manifest(config.id, manifest)
        return {
            "manifest": manifest_payload(manifest),
            "frontmatter": render_frontmatter_binding(manifest),
            "sidecar_checksum": manifest.checksum,
            "sidecar_bytes": render_sidecar_bytes(manifest).decode("utf-8"),
        }

    def manifest(self, manifest_id: str) -> dict[str, Any]:
        return {"manifest": self.repository.get_manifest(manifest_id)}

    def verify(self, config_id: str, *, html: str | None = None) -> dict[str, Any]:
        config = self._ensure_config(config_id)
        manifest = build_manifest(config, default_snapshot_payload())
        self.repository.save_manifest(config.id, manifest)
        page = html or render_static_page(manifest)
        static = self.verifier.verify_static_page(manifest, page)
        try:
            mappings = tuple(self.analytics.mappings(config.analytics_account_id).get("mappings", []))
        except Exception:
            mappings = ()
        drift = self.verifier.mapping_drift(config.id, manifest.expected_events, mappings, manifest.profile_id)
        provider_status = provider_observed_status(manifest.expected_events, set())
        quality = build_quality_report(
            manifest,
            static_status=static["status"],
            browser_status="not_run",
            provider_status=provider_status,
            drift_status=drift.status,
            rendered_ctas=1 if "cta_binding" not in static["missing"] else 0,
            rendered_conversions=1,
        )
        self.repository.save_record(
            "website_instrumentation_verifications",
            config.workspace_id,
            config.id,
            manifest.id,
            static["status"],
            static,
        )
        self.repository.save_record(
            "website_instrumentation_mapping_drift",
            config.workspace_id,
            config.id,
            manifest.id,
            drift.status,
            verification_payload(drift),
        )
        self.repository.save_record(
            "website_instrumentation_quality_reports",
            config.workspace_id,
            config.id,
            manifest.id,
            quality.overall_status,
            asdict(quality),
        )
        return {
            "manifest": manifest_payload(manifest),
            "verification": static,
            "drift": verification_payload(drift),
            "quality": asdict(quality),
            "backend_provider_writes": 0,
        }

    def quality(self, config_id: str) -> dict[str, Any]:
        return self.verify(config_id)["quality"]

    def drift(self, config_id: str) -> dict[str, Any]:
        return self.verify(config_id)["drift"]

    def templates(self, profile_id: str = "") -> dict[str, Any]:
        from .templates import template_payload

        return template_payload(profile_id)

    def operations_health(self) -> dict[str, Any]:
        return self.repository.health()

    def _ensure_config(self, config_id: str) -> WebsiteInstrumentationConfig:
        try:
            return self.repository.get_config(config_id)
        except WebsiteInstrumentationError:
            self.create_config({"id": config_id})
            return self.repository.get_config(config_id)


__all__ = ["WebsiteInstrumentationService"]
