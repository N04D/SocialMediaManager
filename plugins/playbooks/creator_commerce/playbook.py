from __future__ import annotations

from dataclasses import asdict
from typing import Any

import channel_store
from src.core.content import Campaign, Entity, Outcome, Playbook, PolicyRule, TimelineSegment, TransformationContract

PLAYBOOK_ID = "playbook.creator_commerce_repurpose"


class CreatorCommerceRepurposePlaybook:
    playbook = Playbook(
        id=PLAYBOOK_ID,
        name="Creator Commerce Repurpose",
        intent_id="educate",
        required_capabilities=(
            "source.video",
            "source.transcript",
            "transformation.clip_candidates",
            "variant.social_text",
            "commerce.product_catalog",
            "entity.product",
        ),
        optional_capabilities=(
            "asset.short_video",
            "variant.article",
            "channel.linkedin",
            "channel.markdown_website",
            "channel.mastodon",
            "outcome.product_click",
            "outcome.sale",
        ),
        workflow_stages=(
            "load_primary_source",
            "resolve_canonical_transcript",
            "generate_clip_candidates",
            "generate_derived_variants",
            "query_product_catalog",
            "match_relevant_product",
            "create_relationships",
            "generate_commercial_cta",
            "bind_outcome_contracts",
        ),
        policies=(
            "policy.never_invent_discounts",
            "policy.only_promote_available_products",
            "policy.commercial_cta_requires_confirmation",
            "policy.do_not_publish_automatically",
        ),
        success_metrics=("video_view", "social_view", "product_click", "purchase", "revenue"),
    )

    policies = (
        PolicyRule("policy.never_invent_discounts", "Never invent discounts", effect="deny"),
        PolicyRule("policy.only_promote_available_products", "Only promote available products", effect="deny"),
        PolicyRule(
            "policy.commercial_cta_requires_confirmation",
            "Commercial CTA requires explicit user confirmation before external publication",
            effect="require_confirmation",
        ),
        PolicyRule("policy.do_not_publish_automatically", "Do not publish automatically", effect="deny"),
    )

    def __init__(self, *, runtime, content_service) -> None:
        self.runtime = runtime
        self.content_service = content_service

    def resolve_capabilities(self) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for capability in self.playbook.required_capabilities:
            providers = self.runtime.registry.providers_for(capability)
            if not providers:
                raise RuntimeError(f"Missing required capability: {capability}")
            resolved[capability] = providers[0].id
        for capability in self.playbook.optional_capabilities:
            providers = self.runtime.registry.providers_for(capability)
            if providers:
                resolved[capability] = providers[0].id
        return resolved

    def run_sabr_scenario(self, *, workspace_id: str = "creator-commerce") -> dict[str, Any]:
        from plugins.sources.youtube.fixtures import (
            SABR_CHANNEL,
            SABR_LANGUAGE,
            SABR_TITLE,
            SABR_TRANSCRIPT,
            SABR_VIDEO_URL,
        )

        resolved = self.resolve_capabilities()
        source_service = self._service_for(resolved["source.video"], "source_service")
        transform_service = self._service_for(resolved["transformation.clip_candidates"], "transformation_service")
        catalog_service = self._service_for(resolved["commerce.product_catalog"], "commerce_service")
        source_result = source_service.import_source(
            content_service=self.content_service,
            workspace_id=workspace_id,
            url=SABR_VIDEO_URL,
            title=SABR_TITLE,
            transcript=SABR_TRANSCRIPT,
            channel_name=SABR_CHANNEL,
            duration=106,
            language=SABR_LANGUAGE,
            actor=PLAYBOOK_ID,
        )
        timeline: list[TimelineSegment] = source_result["canonical"]["timeline"]
        candidates = transform_service.clip_candidates(timeline, max_candidates=3)
        selected = candidates[0]
        short_video = transform_service.short_video_asset_contract(
            selected=selected,
            source_asset_id=f"asset.video.{source_result['entity'].external_ref}",
            synthetic_video_available=False,
        )
        social_variant = transform_service.social_text_variant(selected=selected, title=SABR_TITLE)
        article_variant = transform_service.article_variant(selected=selected, title=SABR_TITLE)
        products = catalog_service.list_products(include_unavailable=True)
        selected_product = self._match_product(selected.transcript_excerpt, products)
        cta_variant = transform_service.commercial_cta_variant(selected=selected, product_title=selected_product.title)
        graph = self.content_service.graph_service
        for product_entity in catalog_service.product_entities():
            graph.save_entity(product_entity)
        social_entity = graph.save_entity(
            Entity(
                id=f"entity.{social_variant.asset_id}",
                entity_type="variant.social_text",
                source_plugin=resolved["transformation.clip_candidates"],
                external_ref=social_variant.asset_id,
                title="Sabr social text variant",
                metadata={"text": social_variant.text, **social_variant.metadata},
                created_at=channel_store.now_iso(),
                updated_at=channel_store.now_iso(),
            )
        )
        article_entity = graph.save_entity(
            Entity(
                id=f"entity.{article_variant.asset_id}",
                entity_type="variant.article",
                source_plugin=resolved["transformation.clip_candidates"],
                external_ref=article_variant.asset_id,
                title="Sabr article variant",
                metadata={"text": article_variant.text, **article_variant.metadata},
                created_at=channel_store.now_iso(),
                updated_at=channel_store.now_iso(),
            )
        )
        cta_entity = graph.save_entity(
            Entity(
                id=f"entity.{cta_variant.asset_id}",
                entity_type="variant.commercial_cta",
                source_plugin=resolved["transformation.clip_candidates"],
                external_ref=cta_variant.asset_id,
                title="Sabr commercial CTA",
                metadata={"text": cta_variant.text, **cta_variant.metadata},
                created_at=channel_store.now_iso(),
                updated_at=channel_store.now_iso(),
            )
        )
        product_entity_id = f"entity.product.{selected_product.product_id}"
        transformation = TransformationContract(
            id="transformation.video_repurpose.sabr",
            plugin_id=resolved["transformation.clip_candidates"],
            accepts=("timeline.transcript",),
            produces=(
                "transformation.clip_candidates",
                "variant.social_text",
                "variant.article",
                "variant.commercial_cta",
            ),
        )
        run = graph.record_transformation_run(
            workspace_id=workspace_id,
            transformation=transformation,
            input_refs=(source_result["entity"].id,),
            output_refs=(selected.candidate_id, social_entity.id, article_entity.id, cta_entity.id),
            evidence={
                "selected_candidate": selected.candidate_id,
                "candidate_count": len(candidates),
                "short_video_status": short_video["status"],
            },
        )
        graph.add_relationship(
            workspace_id=workspace_id,
            from_entity_id=source_result["entity"].id,
            relationship_type="transcribed_to",
            to_entity_id=f"entity.transcript.{source_result['entity'].external_ref}",
            metadata={"canonical_text": source_result["canonical"]["text"]},
            provenance={
                "actor_type": "plugin",
                "plugin_id": resolved["source.video"],
                "provider": resolved["source.video"],
            },
        )
        graph.save_entity(
            Entity(
                id=f"entity.transcript.{source_result['entity'].external_ref}",
                entity_type="transcript",
                source_plugin=resolved["source.video"],
                external_ref=source_result["entity"].external_ref,
                title="Sabr transcript",
                metadata={
                    "timeline_segments_json": source_result["canonical"]["metadata"].get("timeline_segments_json", "")
                },
            )
        )
        graph.add_relationship(
            workspace_id=workspace_id,
            from_entity_id=f"entity.transcript.{source_result['entity'].external_ref}",
            relationship_type="transformed_into",
            to_entity_id=social_entity.id,
            metadata={"transformation_run_id": run.id, "candidate_id": selected.candidate_id},
            provenance={"actor_type": "plugin", "plugin_id": resolved["transformation.clip_candidates"]},
        )
        graph.add_relationship(
            workspace_id=workspace_id,
            from_entity_id=source_result["entity"].id,
            relationship_type="semantically_related_to",
            to_entity_id=product_entity_id,
            metadata={"reason": "Matched to topic: Sabr", "matched_by": PLAYBOOK_ID},
            provenance={"actor_type": "agent", "provider": PLAYBOOK_ID},
        )
        graph.add_relationship(
            workspace_id=workspace_id,
            from_entity_id=cta_entity.id,
            relationship_type="promotes",
            to_entity_id=product_entity_id,
            metadata={"requires_confirmation": True, "no_discount_claim": True},
            provenance={"actor_type": "agent", "provider": PLAYBOOK_ID},
        )
        campaign = graph.save_campaign(
            Campaign(
                id="campaign.creator_commerce.sabr",
                workspace_id=workspace_id,
                intent_id="educate",
                name="Creator Commerce Repurpose: Sabr",
                source_entity_ids=(source_result["entity"].id, product_entity_id),
                selected_plugin_ids=tuple(sorted(set(resolved.values()))),
                transformation_run_ids=(run.id,),
                variant_ids=(social_entity.id, article_entity.id, cta_entity.id),
                outcome_ids=(
                    "outcome.video_view.sabr",
                    "outcome.social_view.sabr",
                    "outcome.product_click.sabr",
                    "outcome.purchase.sabr",
                    "outcome.revenue.sabr",
                ),
                metadata={"secondary_intent": "sell_product", "playbook_id": PLAYBOOK_ID},
            )
        )
        outcomes = [
            graph.save_outcome(
                Outcome(
                    id="outcome.video_view.sabr",
                    workspace_id=workspace_id,
                    outcome_type="video_view",
                    subject_entity_id=source_result["entity"].id,
                    source_ref=source_result["entity"].id,
                    value=1500,
                    metadata={"primary_source_entity_id": source_result["entity"].id},
                )
            ),
            graph.save_outcome(
                Outcome(
                    id="outcome.social_view.sabr",
                    workspace_id=workspace_id,
                    outcome_type="social_view",
                    subject_entity_id=social_entity.id,
                    source_ref=social_entity.id,
                    value=1000,
                    metadata={"primary_source_entity_id": source_result["entity"].id, "transformation_run_id": run.id},
                )
            ),
            graph.save_outcome(
                Outcome(
                    id="outcome.product_click.sabr",
                    workspace_id=workspace_id,
                    outcome_type="product_click",
                    subject_entity_id=product_entity_id,
                    source_ref=cta_entity.id,
                    value=25,
                    metadata={
                        "primary_source_entity_id": source_result["entity"].id,
                        "variant_entity_id": cta_entity.id,
                    },
                )
            ),
            graph.save_outcome(
                Outcome(
                    id="outcome.purchase.sabr",
                    workspace_id=workspace_id,
                    outcome_type="purchase",
                    subject_entity_id=product_entity_id,
                    source_ref=cta_entity.id,
                    value=3,
                    metadata={
                        "primary_source_entity_id": source_result["entity"].id,
                        "variant_entity_id": cta_entity.id,
                    },
                )
            ),
            graph.save_outcome(
                Outcome(
                    id="outcome.revenue.sabr",
                    workspace_id=workspace_id,
                    outcome_type="revenue",
                    subject_entity_id=product_entity_id,
                    source_ref=cta_entity.id,
                    value=87,
                    currency="EUR",
                    metadata={
                        "primary_source_entity_id": source_result["entity"].id,
                        "variant_entity_id": cta_entity.id,
                    },
                )
            ),
        ]
        graph.save_playbook(self.playbook)
        for policy in self.policies:
            graph.save_policy(policy)
        context = graph.agent_context(workspace_id=workspace_id, content_service=self.content_service)
        return {
            "resolved_capabilities": resolved,
            "source": source_result,
            "candidates": candidates,
            "selected_candidate": selected,
            "short_video": short_video,
            "social_variant": social_variant,
            "article_variant": article_variant,
            "cta_variant": cta_variant,
            "product": selected_product,
            "campaign": campaign,
            "outcomes": outcomes,
            "agent_context": context,
            "reverse_purchase_source": self.source_for_outcome("outcome.purchase.sabr", context),
            "product_for_variant": self.product_for_variant(cta_entity.id, context),
            "transformations_for_variant": self.transformations_for_variant(social_entity.id, context),
        }

    def source_for_outcome(self, outcome_id: str, context: dict[str, Any]) -> str:
        for outcome in context["outcomes"]:
            if outcome["id"] == outcome_id:
                return str(outcome["metadata"].get("primary_source_entity_id", ""))
        return ""

    def product_for_variant(self, variant_entity_id: str, context: dict[str, Any]) -> str:
        for relationship in context["relationships"]:
            if relationship["from_entity_id"] == variant_entity_id and relationship["relationship_type"] == "promotes":
                return str(relationship["to_entity_id"])
        return ""

    def transformations_for_variant(self, variant_entity_id: str, context: dict[str, Any]) -> list[str]:
        matches: list[str] = []
        for relationship in context["relationships"]:
            if relationship["to_entity_id"] == variant_entity_id:
                run_id = relationship["metadata"].get("transformation_run_id")
                if run_id:
                    matches.append(str(run_id))
        return matches

    def _service_for(self, plugin_id: str, service_name: str):
        runtime = self.runtime.runtimes[plugin_id]
        service = runtime.service(service_name)
        if service is None:
            raise RuntimeError(f"Plugin {plugin_id} does not expose {service_name}")
        return service

    @staticmethod
    def _match_product(text: str, products: list[Any]):
        terms = {term.strip(".,:;!?").lower() for term in text.split()}
        scored = []
        for product in products:
            if product.availability != "in_stock":
                continue
            score = len(terms.intersection(set(product.tags))) + len(terms.intersection(product.title.lower().split()))
            scored.append((score, product.title, product))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if not scored or scored[0][0] <= 0:
            raise RuntimeError("No available relevant product found")
        return scored[0][2]


def serializable_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "resolved_capabilities": result["resolved_capabilities"],
        "selected_candidate": asdict(result["selected_candidate"]),
        "short_video": result["short_video"],
        "product": asdict(result["product"]),
        "social_variant": asdict(result["social_variant"]),
        "article_variant": asdict(result["article_variant"]),
        "cta_variant": asdict(result["cta_variant"]),
    }
