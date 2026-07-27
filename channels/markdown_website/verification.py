"""Public URL verification for Markdown Website publications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlparse

from .errors import MarkdownWebsiteVerificationError
from .models import WebsitePublicationEvidence


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    url: str
    headers: dict[str, str]
    text: str


class SafeHttpFetcher(Protocol):
    def __call__(self, url: str) -> HttpResponse: ...


@dataclass(frozen=True)
class WebsiteVerificationResult:
    status: str
    public_url: str
    verified_at: str
    warnings: tuple[str, ...] = ()
    safe_error_code: str = ""


class WebsitePublicationVerifier:
    def __init__(self, fetcher: SafeHttpFetcher) -> None:
        self.fetcher = fetcher

    def verify(self, evidence: WebsitePublicationEvidence) -> WebsiteVerificationResult:
        response = self.fetcher(evidence.public_url)
        expected_host = urlparse(evidence.public_url).hostname
        actual_host = urlparse(response.url).hostname
        if actual_host != expected_host:
            raise MarkdownWebsiteVerificationError(
                "markdown_website.verify.origin", "Verification left the allowed origin."
            )
        if response.status_code not in {200, 203}:
            return WebsiteVerificationResult(
                "deployment_pending", evidence.public_url, "", safe_error_code="http_not_ready"
            )
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type and "text" not in content_type:
            raise MarkdownWebsiteVerificationError("markdown_website.verify.content_type", "Unexpected content type.")
        for value in [
            evidence.revision_binding["content_revision_id"],
            evidence.revision_binding["publication_target_id"],
            evidence.snapshot_checksum,
        ]:
            if value not in response.text:
                return WebsiteVerificationResult(
                    "verification_failed", evidence.public_url, "", safe_error_code="marker_missing"
                )
        return WebsiteVerificationResult("publication_verified", evidence.public_url, datetime.now(UTC).isoformat())
