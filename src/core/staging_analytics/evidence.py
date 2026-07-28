"""Evidence redaction helpers."""

from __future__ import annotations

from .models import StagingBrowserRequestEvidence


def evidence_public_payload(evidence: StagingBrowserRequestEvidence) -> dict[str, object]:
    return {
        "id": evidence.id,
        "run_id": evidence.run_id,
        "event_type": evidence.event_type,
        "event_name": evidence.event_name,
        "destination_origin_reference": evidence.destination_origin_reference,
        "method": evidence.method,
        "safe_property_names": evidence.safe_property_names,
        "safe_property_fingerprint": evidence.safe_property_fingerprint,
        "instrumentation_version": evidence.instrumentation_version,
        "occurred_at": evidence.occurred_at,
        "accepted_by_browser_runtime": evidence.accepted_by_browser_runtime,
        "checksum": evidence.checksum,
    }


__all__ = ["evidence_public_payload"]
