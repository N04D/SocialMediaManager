"""Provider-observed reconciliation for synthetic staging runs."""

from __future__ import annotations

from .models import ProviderObservedReconciliationResult, utc_now_iso


def reconcile_provider_observations(
    *, run_id: str, expected_events: tuple[str, ...], observations: list[dict[str, str]]
) -> ProviderObservedReconciliationResult:
    observed = tuple(
        sorted({item.get("event_name", "") for item in observations if item.get("smm_synthetic_run_id") == run_id})
    )
    missing = tuple(sorted(set(expected_events) - set(observed)))
    duplicate = []
    seen: set[tuple[str, str]] = set()
    for item in observations:
        key = (item.get("event_name", ""), item.get("smm_synthetic_run_id", ""))
        if key in seen:
            duplicate.append(item.get("event_name", ""))
        seen.add(key)
    status = "observed"
    if duplicate:
        status = "conflicting"
    elif missing and observed:
        status = "partially_observed"
    elif missing:
        status = "not_observed"
    return ProviderObservedReconciliationResult(
        run_id=run_id,
        expected_events=expected_events,
        observed_events=observed,
        missing_events=missing,
        conflicting_events=(),
        duplicate_events=tuple(sorted(set(duplicate))),
        delayed_events=missing if status == "not_observed" else (),
        mapping_mismatches=(),
        observation_ids=tuple(
            "stg-obs-" + item.get("event_name", "").lower().replace(" ", "-")
            for item in observations
            if item.get("smm_synthetic_run_id") == run_id
        ),
        attribution_status="exact_run_id" if observed else "browser_verified_provider_pending",
        quality_status=status,
        reconciled_at=utc_now_iso(),
    )


__all__ = ["reconcile_provider_observations"]
