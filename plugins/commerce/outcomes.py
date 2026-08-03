"""Generic commerce outcome projection and currency-aware read models."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from src.core.content import Entity, Outcome

from .attribution import attribute_order


def order_outcomes(
    order: Any,
    *,
    workspace_id: str,
    click_bindings: dict[str, dict[str, str]] | None = None,
    campaign_bindings: dict[str, dict[str, str]] | None = None,
    allow_inferred: bool = False,
) -> list[Outcome]:
    """Project one provider-neutral order into stable purchase/revenue outcomes."""
    if not order.recognized_sale:
        return []
    purchase_decision = attribute_order(
        order_id=order.order_id,
        product_id="",
        metadata=order.attribution_metadata,
        click_bindings=click_bindings,
        campaign_bindings=campaign_bindings,
        allow_inferred=allow_inferred,
        observed_at=order.created_at,
    )
    outcomes = [
        Outcome(
            id=f"outcome.purchase.{order.external_ref}",
            workspace_id=workspace_id,
            outcome_type="purchase",
            source_ref=order.external_ref,
            value=1,
            currency=order.currency,
            metadata={
                "order_external_ref": order.external_ref,
                "attribution_confidence": purchase_decision.confidence,
                "attribution_reason": purchase_decision.reason,
                "attribution_evidence": [item.as_dict() for item in purchase_decision.evidence],
                "approved_tracking_metadata": dict(order.attribution_metadata),
                "attribution_id": purchase_decision.attribution_id,
                "campaign_id": purchase_decision.campaign_id,
                "variant_entity_id": purchase_decision.variant_id,
            },
        )
    ]
    for line in order.line_items:
        if line.total is None or not line.product_id:
            continue
        decision = attribute_order(
            order_id=order.order_id,
            product_id=line.product_id,
            metadata=order.attribution_metadata,
            click_bindings=click_bindings,
            campaign_bindings=campaign_bindings,
            allow_inferred=allow_inferred,
            observed_at=order.created_at,
        )
        outcomes.append(
            Outcome(
                id=f"outcome.revenue.{order.external_ref}:line:{line.line_id}",
                workspace_id=workspace_id,
                outcome_type="revenue",
                subject_entity_id=line.product_id,
                source_ref=order.external_ref,
                value=line.total,
                currency=order.currency,
                metadata={
                    "order_external_ref": order.external_ref,
                    "line_item_id": line.line_id,
                    "quantity": line.quantity,
                    "attribution_confidence": decision.confidence,
                    "attribution_reason": decision.reason,
                    "attribution_evidence": [item.as_dict() for item in decision.evidence],
                    "approved_tracking_metadata": dict(order.attribution_metadata),
                    "attribution_id": decision.attribution_id,
                    "campaign_id": decision.campaign_id,
                    "variant_entity_id": decision.variant_id,
                },
            )
        )
    return outcomes


def record_order_outcomes(
    graph: Any,
    order: Any,
    *,
    workspace_id: str,
    click_bindings: dict[str, dict[str, str]] | None = None,
    campaign_bindings: dict[str, dict[str, str]] | None = None,
    allow_inferred: bool = False,
) -> list[Outcome]:
    """Persist generic outcomes and evidence links without provider-specific graph types."""
    outcomes = order_outcomes(
        order,
        workspace_id=workspace_id,
        click_bindings=click_bindings,
        campaign_bindings=campaign_bindings,
        allow_inferred=allow_inferred,
    )
    for outcome in outcomes:
        graph.save_outcome(outcome)
        outcome_entity_id = f"entity.{outcome.id}"
        graph.save_entity(
            Entity(
                id=outcome_entity_id,
                entity_type=outcome.outcome_type,
                source_plugin="commerce.outcomes",
                external_ref=str(outcome.metadata.get("order_external_ref") or outcome.id),
                title=outcome.outcome_type,
                metadata={"trust_boundary": "external_untrusted_commerce_data"},
            )
        )
        if outcome.subject_entity_id:
            graph.add_relationship(
                workspace_id=workspace_id,
                from_entity_id=outcome_entity_id,
                relationship_type="outcome_for_product",
                to_entity_id=outcome.subject_entity_id,
                metadata={"attribution_confidence": outcome.metadata.get("attribution_confidence", "unknown")},
                provenance={"actor_type": "plugin", "plugin_id": "commerce.outcomes"},
            )
        variant_id = str(outcome.metadata.get("variant_entity_id") or "")
        if variant_id:
            graph.add_relationship(
                workspace_id=workspace_id,
                from_entity_id=outcome_entity_id,
                relationship_type="attributed_to_variant",
                to_entity_id=variant_id,
                metadata={"attribution_confidence": outcome.metadata.get("attribution_confidence", "unknown")},
                provenance={"actor_type": "plugin", "plugin_id": "commerce.outcomes"},
            )
    return outcomes


def outcome_summary(outcomes: Iterable[Outcome]) -> dict[str, Any]:
    purchases = [item for item in outcomes if item.outcome_type == "purchase"]
    revenue = [item for item in outcomes if item.outcome_type == "revenue"]
    by_currency: dict[str, dict[str, float]] = {}
    for item in revenue:
        currency = item.currency.upper()
        bucket = by_currency.setdefault(currency, {"direct": 0.0, "strong": 0.0, "inferred": 0.0, "unknown": 0.0})
        confidence = str(item.metadata.get("attribution_confidence") or "unknown")
        if confidence not in bucket:
            confidence = "unknown"
        bucket[confidence] += float(item.value or 0)
    return {
        "purchases": len(purchases),
        "revenue": by_currency,
        "outcomes": [asdict(item) for item in outcomes],
    }


__all__ = ["order_outcomes", "outcome_summary", "record_order_outcomes"]
