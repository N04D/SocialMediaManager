"""Provider-neutral, evidence-based commerce attribution helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

CONFIDENCE_LEVELS = ("direct", "strong", "inferred", "unknown")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class AttributionEvidence:
    evidence_type: str
    source: str
    reference: str = ""
    value: str = ""
    observed_at: str = ""
    confidence: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AttributionDecision:
    confidence: str
    reason: str
    attribution_id: str = ""
    campaign_id: str = ""
    variant_id: str = ""
    product_id: str = ""
    evidence: tuple[AttributionEvidence, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"evidence": [item.as_dict() for item in self.evidence]}


def approved_metadata(
    raw: dict[str, Any],
    *,
    attribution_id_keys: Iterable[str] = (),
    campaign_keys: Iterable[str] = (),
    content_keys: Iterable[str] = (),
    utm_keys: Iterable[str] = (),
) -> dict[str, str]:
    """Keep only explicitly approved attribution metadata, never arbitrary order meta."""
    groups = {
        "attribution_id": {str(key) for key in attribution_id_keys},
        "campaign_id": {str(key) for key in campaign_keys},
        "content_id": {str(key) for key in content_keys},
        "utm": {str(key) for key in utm_keys},
    }
    result: dict[str, str] = {}
    for key, value in raw.items():
        key_text = str(key)
        for group, allowed in groups.items():
            if key_text in allowed and value not in (None, ""):
                result[group] = str(value)[:512]
    return result


def attribute_order(
    *,
    order_id: str,
    product_id: str,
    metadata: dict[str, str],
    click_bindings: dict[str, dict[str, str]] | None = None,
    campaign_bindings: dict[str, dict[str, str]] | None = None,
    allow_inferred: bool = False,
    observed_at: str = "",
) -> AttributionDecision:
    """Choose one conservative confidence level; never double-count alternatives."""
    click_bindings = click_bindings or {}
    campaign_bindings = campaign_bindings or {}
    observed_at = observed_at or now_iso()
    attribution_id = metadata.get("attribution_id", "")
    campaign_id = metadata.get("campaign_id", "")
    content_id = metadata.get("content_id", "")
    evidence: list[AttributionEvidence] = []

    if attribution_id and attribution_id in click_bindings:
        binding = click_bindings[attribution_id]
        if not product_id or not binding.get("product_id") or binding.get("product_id") == product_id:
            evidence.append(
                AttributionEvidence(
                    "click_id_match", "commerce.order_metadata", attribution_id, attribution_id, observed_at, "direct"
                )
            )
            return AttributionDecision(
                "direct",
                "The order contained the same attribution ID as the tracked product click.",
                attribution_id,
                binding.get("campaign_id", campaign_id),
                binding.get("variant_id", content_id),
                product_id,
                tuple(evidence),
            )

    if campaign_id and content_id and campaign_id in campaign_bindings:
        binding = campaign_bindings[campaign_id]
        if (not product_id or not binding.get("product_id") or binding.get("product_id") == product_id) and (
            binding.get("content_id") == content_id
        ):
            evidence.extend(
                [
                    AttributionEvidence(
                        "campaign_match", "commerce.order_metadata", campaign_id, campaign_id, observed_at, "strong"
                    ),
                    AttributionEvidence(
                        "content_match", "commerce.order_metadata", content_id, content_id, observed_at, "strong"
                    ),
                ]
            )
            return AttributionDecision(
                "strong",
                "Campaign and content tracking metadata matched the order.",
                attribution_id,
                campaign_id,
                binding.get("variant_id", content_id),
                product_id,
                tuple(evidence),
            )

    if allow_inferred and campaign_id and campaign_id in campaign_bindings:
        binding = campaign_bindings[campaign_id]
        if binding.get("product_id") == product_id:
            evidence.append(
                AttributionEvidence(
                    "product_campaign_correlation", "attribution_rule", campaign_id, product_id, observed_at, "inferred"
                )
            )
            return AttributionDecision(
                "inferred",
                "Product and campaign matched, but no direct click identity was available.",
                attribution_id,
                campaign_id,
                binding.get("variant_id", content_id),
                product_id,
                tuple(evidence),
            )

    return AttributionDecision(
        "unknown",
        "No approved click, campaign, or content evidence linked this order to content.",
        attribution_id,
        campaign_id,
        content_id,
        product_id,
        tuple(evidence),
    )


def aggregate_revenue(outcomes: Iterable[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Aggregate by currency and confidence; never combine currencies."""
    totals: dict[str, dict[str, float]] = {}
    for outcome in outcomes:
        currency = str(outcome.get("currency") or "").upper()
        if not currency:
            continue
        bucket = totals.setdefault(currency, {level: 0.0 for level in CONFIDENCE_LEVELS})
        confidence = str(outcome.get("metadata", {}).get("attribution_confidence") or "unknown")
        if confidence not in CONFIDENCE_LEVELS:
            confidence = "unknown"
        value = float(outcome.get("value") or 0)
        bucket[confidence] += value
    return totals


__all__ = [
    "AttributionDecision",
    "AttributionEvidence",
    "CONFIDENCE_LEVELS",
    "aggregate_revenue",
    "approved_metadata",
    "attribute_order",
]
