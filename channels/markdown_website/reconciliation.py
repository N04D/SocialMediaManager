"""Read-only reconciliation for Markdown Website publications."""

from __future__ import annotations

from dataclasses import dataclass

from .git_publisher import sha256_path
from .models import WebsitePublicationEvidence, WebsiteRepositoryReference
from .paths import ensure_under


@dataclass(frozen=True)
class ReconciliationResult:
    status: str
    findings: tuple[str, ...] = ()
    safe_repairs: tuple[str, ...] = ()


class MarkdownWebsiteReconciliationService:
    def reconcile(
        self, evidence: WebsitePublicationEvidence, repository: WebsiteRepositoryReference
    ) -> ReconciliationResult:
        findings: list[str] = []
        path = ensure_under(repository.managed_checkout_root, evidence.markdown_relative_path)
        if not path.exists():
            findings.append("publication_file_missing")
        elif sha256_path(path) != evidence.rendered_markdown_checksum:
            findings.append("website_content_drift")
        if findings:
            return ReconciliationResult("manual_review_required", tuple(findings), ("derived_health_rebuild",))
        return ReconciliationResult("reconciled")
