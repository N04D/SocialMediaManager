"""Static HTML fixtures for instrumentation verification."""

from src.core.website_instrumentation.renderer import render_static_page
from src.core.website_instrumentation.service import WebsiteInstrumentationService


def rendered_fixture_page() -> str:
    service = WebsiteInstrumentationService()
    config = service.create_config({"id": "instrumentation-config-owned-1"})["config"]
    manifest = service.preview_manifest(config["id"])["manifest"]
    return render_static_page(_manifest_from_payload(service, manifest["id"]))


def _manifest_from_payload(service: WebsiteInstrumentationService, manifest_id: str):
    from src.core.website_instrumentation.manifests import build_manifest

    return build_manifest(service.repository.get_config("instrumentation-config-owned-1"), {})


__all__ = ["rendered_fixture_page"]
