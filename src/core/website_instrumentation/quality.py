"""Instrumentation quality reports."""

from __future__ import annotations

from .models import WebsiteInstrumentationManifest, WebsiteInstrumentationQualityReport, utc_now_iso


def build_quality_report(
    manifest: WebsiteInstrumentationManifest,
    *,
    static_status: str,
    browser_status: str,
    provider_status: str,
    drift_status: str,
    rendered_ctas: int = 0,
    observed_ctas: int = 0,
    rendered_conversions: int = 0,
    observed_conversions: int = 0,
    warnings: tuple[str, ...] = (),
) -> WebsiteInstrumentationQualityReport:
    cta_total = len(manifest.cta_bindings)
    conversion_total = len(manifest.conversion_bindings)
    overall = "complete"
    if "unsafe" in warnings:
        overall = "unsafe"
    elif "drift" in drift_status or static_status != "complete" or browser_status not in {"complete", "not_run"}:
        overall = "partial"
    elif provider_status not in {"observed", "insufficient_data"}:
        overall = "not_observed"
    return WebsiteInstrumentationQualityReport(
        website_account_id=manifest.website_account_id,
        analytics_account_id=manifest.analytics_account_id,
        publication_target_id=manifest.publication_target_id,
        manifest_status="complete",
        static_page_status=static_status,
        browser_runtime_status=browser_status,
        provider_observed_status=provider_status,
        mapping_drift_status=drift_status,
        consent_mode=manifest.consent_mode,
        page_context_status="complete",
        cta_coverage={
            "configured": cta_total,
            "rendered": rendered_ctas,
            "runtime_verifiable": rendered_ctas,
            "provider_mapped": cta_total if drift_status == "aligned" else 0,
            "provider_observed": observed_ctas,
        },
        conversion_coverage={
            "configured": conversion_total,
            "rendered": rendered_conversions,
            "runtime_verifiable": rendered_conversions,
            "provider_mapped": conversion_total if drift_status == "aligned" else 0,
            "provider_observed": observed_conversions,
        },
        attribution_parameter_status="complete",
        duplicate_runtime_status="complete",
        pii_risk_status="complete" if "unsafe" not in warnings else "unsafe",
        last_verified_at=utc_now_iso(),
        safe_warnings=warnings,
        overall_status=overall,
    )


__all__ = ["build_quality_report"]
