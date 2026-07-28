"""Run state helpers for staging analytics certification."""

VALID_RUN_STATUSES = {
    "prepared",
    "browser_starting",
    "browser_running",
    "browser_events_sent",
    "awaiting_provider",
    "provider_partially_observed",
    "provider_observed",
    "timed_out",
    "failed",
    "cancelled",
    "browser_mutation_uncertain",
}

UNCERTAIN_STATES = {"event_trigger_started", "browser_request_observed", "provider_ack_unknown"}

__all__ = ["UNCERTAIN_STATES", "VALID_RUN_STATUSES"]
