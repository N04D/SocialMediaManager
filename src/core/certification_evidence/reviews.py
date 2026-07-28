"""Operator review defaults."""

from __future__ import annotations

from .models import CertificationEvidenceReview, stable_checksum, utc_now_iso


def build_review(
    *,
    workspace_id: str,
    evidence_id: str,
    evidence_checksum: str,
    decision: str,
    reviewer_id: str,
    safe_comment: str = "",
) -> CertificationEvidenceReview:
    if decision not in {"approved", "rejected", "needs_follow_up", "acknowledged_stale"}:
        raise ValueError("Unsupported certification review decision.")
    if any(marker in safe_comment.lower() for marker in ("secret", "token", "authorization", "cookie")):
        raise ValueError("Certification review comment contains forbidden data.")
    seed = stable_checksum(
        {"evidence_id": evidence_id, "decision": decision, "reviewer_id": reviewer_id, "comment": safe_comment}
    )
    return CertificationEvidenceReview(
        id="cert-review-" + seed[:16],
        workspace_id=workspace_id,
        evidence_id=evidence_id,
        reviewer_id=reviewer_id,
        decision=decision,
        safe_comment=safe_comment[:500],
        reviewed_at=utc_now_iso(),
        evidence_checksum=evidence_checksum,
    )


__all__ = ["build_review"]
