from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.content import AssetContract, ProvenanceRecord, TimelineSegment, TransformationContract

PLUGIN_ID = "plugin.video_repurpose"


@dataclass(frozen=True)
class RepurposeCandidate:
    candidate_id: str
    start_time: float
    end_time: float
    duration: float
    transcript_excerpt: str
    score: float
    reason: str
    topic: str
    hook: str
    provenance: dict[str, Any] = field(default_factory=dict)


class VideoRepurposePlugin:
    capabilities = (
        "transformation.clip_candidates",
        "transformation.accepts.asset.video",
        "transformation.accepts.timeline.transcript",
        "transformation.accepts.canonical.text",
        "transformation.produces.transformation.clip_candidates",
        "transformation.produces.asset.short_video",
        "transformation.produces.variant.social_text",
        "transformation.produces.variant.article",
        "asset.short_video",
        "variant.social_text",
        "variant.article",
    )
    contract = TransformationContract(
        id="transformation.video_repurpose.v0",
        plugin_id=PLUGIN_ID,
        accepts=("asset.video", "timeline.transcript", "canonical.text"),
        produces=("transformation.clip_candidates", "asset.short_video", "variant.social_text", "variant.article"),
    )

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "plugin_id": PLUGIN_ID,
            "network_required": False,
            "shell": "not_used",
            "short_video_rendering": "rendering capability not configured",
        }

    def clip_candidates(self, segments: list[TimelineSegment], *, max_candidates: int = 3) -> list[RepurposeCandidate]:
        candidates: list[RepurposeCandidate] = []
        for index, segment in enumerate(segments, start=1):
            text = segment.text.strip()
            duration = round(float(segment.end_time) - float(segment.start_time), 3)
            if not text or duration <= 0:
                continue
            lowered = text.lower()
            hook_score = 0.22 if self._has_strong_opening(text) else 0.0
            question_score = 0.14 if "?" in text else 0.0
            statement_score = 0.14 if any(word in lowered for word in ["means", "is", "are", "why"]) else 0.0
            story_score = 0.12 if any(word in lowered for word in ["when", "you", "daily", "simple"]) else 0.0
            duration_score = max(0.0, 1.0 - abs(duration - 28.0) / 40.0)
            completeness_score = min(len(text.split()) / 24.0, 1.0) * 0.24
            score = round(
                duration_score * 0.28
                + completeness_score
                + hook_score
                + question_score
                + statement_score
                + story_score,
                4,
            )
            topic = segment.semantic_topic or self._topic(text)
            candidates.append(
                RepurposeCandidate(
                    candidate_id=f"clip-candidate-{index}",
                    start_time=float(segment.start_time),
                    end_time=float(segment.end_time),
                    duration=duration,
                    transcript_excerpt=text[:320],
                    score=score,
                    reason="duration+hook+statement+story+completeness",
                    topic=topic,
                    hook=self._hook(text),
                    provenance={"plugin_id": PLUGIN_ID, "strategy": "deterministic_v0"},
                )
            )
        return sorted(candidates, key=lambda candidate: (-candidate.score, candidate.start_time))[:max_candidates]

    def short_video_asset_contract(
        self,
        *,
        selected: RepurposeCandidate,
        source_asset_id: str = "",
        synthetic_video_available: bool = False,
    ) -> dict[str, Any]:
        status = "available" if synthetic_video_available and source_asset_id else "rendering capability not configured"
        asset_id = f"short-video-{selected.candidate_id}"
        return {
            "asset_id": asset_id,
            "asset_type": "short_video",
            "status": status,
            "source_asset_id": source_asset_id,
            "start": selected.start_time,
            "end": selected.end_time,
            "duration": selected.duration,
            "format": "mp4",
            "aspect_ratio": "9:16",
            "provenance": {"plugin_id": PLUGIN_ID, "candidate_id": selected.candidate_id},
        }

    def social_text_variant(self, *, selected: RepurposeCandidate, title: str = "") -> AssetContract:
        text = (
            f"{selected.hook}\n\n{selected.transcript_excerpt}\n\nA short reflection from the source material."
        ).strip()
        return AssetContract(
            asset_id=f"variant-social-{selected.candidate_id}",
            asset_type="variant.social_text",
            text=text,
            metadata={"title": title, "candidate_id": selected.candidate_id, "topic": selected.topic},
            provenance=ProvenanceRecord(plugin_id=PLUGIN_ID, actor_type="plugin"),
        )

    def article_variant(self, *, selected: RepurposeCandidate, title: str = "") -> AssetContract:
        text = (
            f"# {title or selected.topic.title()}\n\n"
            f"{selected.transcript_excerpt}\n\n"
            "This article variant expands the selected segment into a concise website draft."
        ).strip()
        return AssetContract(
            asset_id=f"variant-article-{selected.candidate_id}",
            asset_type="variant.article",
            text=text,
            metadata={"title": title, "candidate_id": selected.candidate_id, "topic": selected.topic},
            provenance=ProvenanceRecord(plugin_id=PLUGIN_ID, actor_type="plugin"),
        )

    def commercial_cta_variant(self, *, selected: RepurposeCandidate, product_title: str) -> AssetContract:
        return AssetContract(
            asset_id=f"variant-cta-{selected.candidate_id}",
            asset_type="variant.commercial_cta",
            text=f"Explore the related {product_title} design.",
            metadata={"candidate_id": selected.candidate_id, "product_title": product_title, "no_discount_claim": True},
            provenance=ProvenanceRecord(plugin_id=PLUGIN_ID, actor_type="plugin"),
        )

    @staticmethod
    def _has_strong_opening(text: str) -> bool:
        lowered = text.lower()
        return lowered.startswith(("when ", "why ", "what ", "a simple", "the strongest"))

    @staticmethod
    def _topic(text: str) -> str:
        lowered = text.lower()
        for keyword in ["sabr", "patience", "reflection", "daily life", "endurance"]:
            if keyword in lowered:
                return keyword
        return "source segment"

    @staticmethod
    def _hook(text: str) -> str:
        first = text.split(".", maxsplit=1)[0].strip()
        return first if first else "A useful idea from the source"
