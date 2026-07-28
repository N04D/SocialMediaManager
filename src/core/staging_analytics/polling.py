"""Bounded provider polling plans for staging certification."""

from __future__ import annotations

from .models import SyntheticProviderObservationQuery, bounded_poll_schedule


class StagingProviderPollingPlanner:
    def __init__(self, *, initial: int, maximum: int, multiplier: float, attempts: int) -> None:
        self.delays = bounded_poll_schedule(initial, maximum, multiplier, attempts)

    def plan_query(
        self,
        *,
        account_id: str,
        run_id: str,
        expected_event_names: tuple[str, ...],
        page_path: str,
        attribution_id: str,
        period_start: str,
        period_end: str,
    ) -> SyntheticProviderObservationQuery:
        return SyntheticProviderObservationQuery(
            account_id=account_id,
            run_id=run_id,
            expected_event_names=expected_event_names,
            expected_property_filters={"smm_synthetic_run_id": run_id},
            period_start=period_start,
            period_end=period_end,
            page_path=page_path,
            attribution_id=attribution_id,
        )


__all__ = ["StagingProviderPollingPlanner"]
