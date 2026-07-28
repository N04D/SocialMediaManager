"""Event schema and property allowlist."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .errors import WebsiteInstrumentationError
from .models import WebsiteInstrumentationEvent

SMM_CTA_EVENT = "SMM CTA Click"
SMM_OUTBOUND_EVENT = "SMM Outbound Click"
SMM_CONVERSION_EVENT = "SMM Conversion"


@dataclass(frozen=True)
class EventPropertyRule:
    name: str
    type: str
    maximum_length: int
    required: bool
    allowed_values: tuple[str, ...] = ()
    redaction_policy: str = "drop_unknown"
    provider_mapping: str = ""


PROPERTY_RULES: dict[str, EventPropertyRule] = {
    "page_id": EventPropertyRule("page_id", "string", 80, True, provider_mapping="page_id"),
    "content_id": EventPropertyRule("content_id", "string", 80, True, provider_mapping="content_id"),
    "revision_id": EventPropertyRule("revision_id", "string", 80, True, provider_mapping="revision_id"),
    "publication_id": EventPropertyRule("publication_id", "string", 80, True, provider_mapping="publication_id"),
    "campaign_id": EventPropertyRule("campaign_id", "string", 80, False, provider_mapping="campaign_id"),
    "cta_id": EventPropertyRule("cta_id", "string", 80, False, provider_mapping="cta_id"),
    "cta_type": EventPropertyRule(
        "cta_type", "enum", 32, False, ("internal", "external", "contact", "signup", "download", "custom")
    ),
    "placement": EventPropertyRule("placement", "string", 80, False),
    "destination_origin_class": EventPropertyRule(
        "destination_origin_class", "enum", 32, False, ("same_origin", "allowed_external", "unknown")
    ),
    "conversion_id": EventPropertyRule("conversion_id", "string", 80, False),
    "conversion_type": EventPropertyRule(
        "conversion_type", "enum", 32, False, ("signup", "contact", "download", "purchase", "custom")
    ),
    "outcome": EventPropertyRule("outcome", "enum", 32, False, ("started", "completed", "failed", "custom")),
    "smm_attribution_id": EventPropertyRule("smm_attribution_id", "string", 120, False),
    "utm_source": EventPropertyRule("utm_source", "string", 80, False),
    "utm_medium": EventPropertyRule("utm_medium", "string", 80, False),
    "utm_campaign": EventPropertyRule("utm_campaign", "string", 120, False),
    "utm_content": EventPropertyRule("utm_content", "string", 120, False),
    "smm_synthetic_run_id": EventPropertyRule("smm_synthetic_run_id", "string", 80, False),
}


def allowed_provider_properties(event: WebsiteInstrumentationEvent) -> dict[str, str]:
    values = {
        "page_id": event.page_context.page_id,
        "content_id": event.page_context.content_id,
        "revision_id": event.page_context.revision_id,
        "publication_id": event.page_context.publication_id,
        "campaign_id": event.page_context.campaign_id,
        **event.event_context,
        **event.attribution_context,
    }
    cleaned: dict[str, str] = {}
    for key, value in values.items():
        rule = PROPERTY_RULES.get(key)
        if not rule:
            continue
        text = str(value)
        if len(text) > rule.maximum_length:
            text = text[: rule.maximum_length]
        if rule.allowed_values and text not in rule.allowed_values:
            raise WebsiteInstrumentationError("website_instrumentation.property_enum", "Invalid property value.")
        cleaned[key] = text
    for key, rule in PROPERTY_RULES.items():
        if rule.required and not cleaned.get(key):
            raise WebsiteInstrumentationError("website_instrumentation.property_required", f"Missing {key}.")
    return cleaned


def property_schema_payload() -> list[dict[str, Any]]:
    return [asdict(item) for item in PROPERTY_RULES.values()]


__all__ = [
    "PROPERTY_RULES",
    "SMM_CONVERSION_EVENT",
    "SMM_CTA_EVENT",
    "SMM_OUTBOUND_EVENT",
    "allowed_provider_properties",
    "property_schema_payload",
]
