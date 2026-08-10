from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.runtime.candidates import ExternalSourceCandidate
from src.core.runtime.components import ComponentManifest
from src.core.runtime.installs import Install

YOUTUBE_UPLOADS_COMPONENT_ID = "youtube-data-api-uploads"
YOUTUBE_VIDEO_PUBLISHED_EVENT = "youtube.video.published"


@dataclass(frozen=True)
class ExternalSourceAdmissionResult:
    source_id: str
    component_id: str
    status: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def admitted(self) -> bool:
        return self.status == "ADMITTED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "metadata": dict(self.metadata),
            "reasons": list(self.reasons),
            "source_id": self.source_id,
            "status": self.status,
        }


def youtube_upload_source_admission(
    *,
    component: ComponentManifest | Any,
    install: Install | Any = None,
    candidate: ExternalSourceCandidate,
) -> ExternalSourceAdmissionResult:
    reasons: list[str] = []

    if candidate.component_id != YOUTUBE_UPLOADS_COMPONENT_ID:
        reasons.append("BLOCKED_COMPONENT_ID_MISMATCH")

    if not candidate.read_only:
        reasons.append("BLOCKED_NOT_READ_ONLY")

    if candidate.event_type != YOUTUBE_VIDEO_PUBLISHED_EVENT:
        reasons.append("BLOCKED_INVALID_EVENT_TYPE")

    if not candidate.bounded_polling or candidate.page_size_limit > 50 or candidate.max_pages_limit > 10:
        reasons.append("BLOCKED_UNBOUNDED_POLLING")

    if candidate.first_poll_policy != "FROM_NOW":
        reasons.append("BLOCKED_INVALID_FIRST_POLL_POLICY")

    if not candidate.gap_detection:
        reasons.append("BLOCKED_NO_GAP_DETECTION")

    if not candidate.stable_external_identity:
        reasons.append("BLOCKED_NO_STABLE_IDENTITY")

    if not candidate.checkpoint_support:
        reasons.append("BLOCKED_NO_CHECKPOINT_SUPPORT")

    # Inspect Install permissions / egress if provided
    if install is not None:
        granted_destinations = set()
        if hasattr(install, "grants") and hasattr(install.grants, "permission_grants"):
            network = getattr(install.grants.permission_grants, "network", None)
            egress_list = getattr(network, "egress", ()) if network else ()
            for rule in egress_list:
                if hasattr(rule, "host") and hasattr(rule, "port"):
                    granted_destinations.add(f"{rule.host}:{rule.port}")
                elif isinstance(rule, str):
                    granted_destinations.add(rule)
        elif hasattr(install, "permissions") and install.permissions is not None:
            perms = install.permissions
            network = getattr(perms, "network", None)
            egress_list = getattr(network, "egress", ()) if network else getattr(perms, "network_egress", ())
            for rule in egress_list:
                if hasattr(rule, "host") and hasattr(rule, "port"):
                    granted_destinations.add(f"{rule.host}:{rule.port}")
                elif isinstance(rule, str):
                    granted_destinations.add(rule)

        for required_dest in candidate.required_egress:
            if required_dest not in granted_destinations:
                reasons.append(f"BLOCKED_REQUIRED_EGRESS_DENIED:{required_dest}")

        granted_secrets = set()
        if hasattr(install, "secret_refs"):
            if isinstance(install.secret_refs, (list, tuple, set)):
                granted_secrets = set(install.secret_refs)
            elif isinstance(install.secret_refs, dict):
                granted_secrets = set(install.secret_refs.keys())
        for secret_ref in candidate.required_secrets:
            if secret_ref not in granted_secrets:
                reasons.append(f"BLOCKED_MISSING_SECRET_REF:{secret_ref}")

    if reasons:
        return ExternalSourceAdmissionResult(
            source_id=candidate.source_id,
            component_id=candidate.component_id,
            status="BLOCKED",
            reasons=tuple(reasons),
            metadata={"reasons_count": len(reasons)},
        )

    return ExternalSourceAdmissionResult(
        source_id=candidate.source_id,
        component_id=candidate.component_id,
        status="ADMITTED",
        reasons=(),
        metadata={
            "read_only": True,
            "bounded_polling": True,
            "first_poll_policy": "FROM_NOW",
            "gap_detection": True,
        },
    )
