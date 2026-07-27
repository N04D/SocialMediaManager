"""Host-owned fake deployment verifier for tests."""

from channels.markdown_website.verification import HttpResponse


def verified_page(url: str, *, revision_id: str, target_id: str, snapshot_checksum: str) -> HttpResponse:
    body = (
        f"<meta name='smm-content-revision' content='{revision_id}'>"
        f"<meta name='smm-publication-target' content='{target_id}'>"
        f"<meta name='smm-snapshot-checksum' content='{snapshot_checksum}'>"
    )
    return HttpResponse(200, url, {"content-type": "text/html"}, body)
