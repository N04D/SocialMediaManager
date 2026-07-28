"""Plausible event/property mapping for browser instrumentation."""

from src.core.website_instrumentation.events import SMM_CONVERSION_EVENT, SMM_CTA_EVENT, SMM_OUTBOUND_EVENT

PLAUSIBLE_EVENT_MAPPING = {
    "cta_click": SMM_CTA_EVENT,
    "outbound_click": SMM_OUTBOUND_EVENT,
    "conversion": SMM_CONVERSION_EVENT,
}

PLAUSIBLE_PROPERTY_MAPPING = {
    "page_id": "page_id",
    "content_id": "content_id",
    "revision_id": "revision_id",
    "publication_id": "publication_id",
    "campaign_id": "campaign_id",
    "cta_id": "cta_id",
    "conversion_id": "conversion_id",
}
