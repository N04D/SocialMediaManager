"""Read-only MCP-style query surface for owned-publication funnels."""

from __future__ import annotations

from typing import Any

from .service import OwnedPublicationWorkspaceService


class OwnedPublicationMCP:
    def __init__(self, service: OwnedPublicationWorkspaceService | None = None) -> None:
        self.service = service or OwnedPublicationWorkspaceService()

    def get_owned_publication_workspace(self, content_item_id: str) -> dict[str, Any]:
        payload = self.service.workspace_payload(content_item_id)
        payload.update({"tool": "owned_publication.get_owned_publication_workspace", "read_only": True})
        return payload

    def get_article_with_channel_variants(self, content_item_id: str) -> dict[str, Any]:
        workspace = self.service.workspace_payload(content_item_id)
        return {
            "tool": "owned_publication.get_article_with_channel_variants",
            "read_only": True,
            "article": workspace["active_revision"],
            "variants": workspace["variants"],
            "exact_binding": _binding(workspace),
        }

    def get_publication_plan(self, plan_id: str) -> dict[str, Any]:
        payload = self.service.plan_payload(plan_id)
        payload.update({"tool": "owned_publication.get_publication_plan", "read_only": True})
        return payload

    def get_publication_dependencies(self, plan_id: str) -> dict[str, Any]:
        payload = self.service.plan_payload(plan_id)
        return {
            "tool": "owned_publication.get_publication_dependencies",
            "read_only": True,
            "dependencies": payload["dependencies"],
            "exact_binding": {"publication_plan_id": plan_id},
        }

    def get_publication_execution_timeline(self, publication_id: str) -> dict[str, Any]:
        payload = self.service.timeline(publication_id)
        payload.update({"tool": "owned_publication.get_publication_execution_timeline", "read_only": True})
        return payload

    def get_publication_evidence(self, publication_id: str) -> dict[str, Any]:
        payload = self.service.evidence(publication_id)
        payload.update({"tool": "owned_publication.get_publication_evidence", "read_only": True})
        return payload

    def get_reconciliation_queue(self) -> dict[str, Any]:
        payload = self.service.reconciliation()
        payload.update({"tool": "owned_publication.get_reconciliation_queue", "read_only": True})
        return payload

    def get_content_funnel(self, content_item_id: str) -> dict[str, Any]:
        payload = self.service.funnel(content_item_id)
        return {"tool": "owned_publication.get_content_funnel", "read_only": True, "funnel": payload}

    def compare_channel_performance(self, content_item_id: str) -> dict[str, Any]:
        payload = self.service.channel_comparison(content_item_id)
        payload.update({"tool": "owned_publication.compare_channel_performance", "read_only": True})
        return payload

    def compare_content_revisions(self, content_item_id: str) -> dict[str, Any]:
        payload = self.service.revision_comparison(content_item_id)
        payload.update({"tool": "owned_publication.compare_content_revisions", "read_only": True})
        return payload

    def get_funnel_dropoffs(self, content_item_id: str) -> dict[str, Any]:
        steps = self.service.funnel(content_item_id)["steps"]
        dropoffs = [
            {"from": steps[index - 1]["name"], "to": step["name"], "dropoff": steps[index - 1]["count"] - step["count"]}
            for index, step in enumerate(steps)
            if index > 0
        ]
        return {"tool": "owned_publication.get_funnel_dropoffs", "read_only": True, "dropoffs": dropoffs}

    def get_cta_performance(self, content_item_id: str) -> dict[str, Any]:
        funnel = self.service.funnel(content_item_id)["model"]
        return {
            "tool": "owned_publication.get_cta_performance",
            "read_only": True,
            "content_item_id": content_item_id,
            "cta_clicks": funnel["cta_clicks"],
            "conversions": funnel["conversions"],
            "conversion_rate": funnel["conversion_rate"],
        }

    def get_attribution_quality(self, content_item_id: str) -> dict[str, Any]:
        return {
            "tool": "owned_publication.get_attribution_quality",
            "read_only": True,
            **self.service.quality(content_item_id),
        }


def _binding(workspace: dict[str, Any]) -> dict[str, str]:
    return {
        "content_item_id": workspace["content_item_id"],
        "content_revision_id": workspace["active_revision"]["id"],
        "channel_variant_id": workspace["variants"]["website"]["id"],
        "publication_target_id": "target-website",
        "publication_attempt_id": "attempt-website-1",
        "campaign": workspace["publication_plan"]["campaign"],
        "analytics_time_window": workspace["funnel"]["model"].get("time_window", ""),
    }
