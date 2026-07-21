from __future__ import annotations

from dataclasses import asdict
from typing import Any


def analytics_list_metrics(runtime, config, *, channel_plugin_id: str = "") -> dict[str, Any]:
    bundle = runtime.analytics_bundle(config)
    definitions = bundle.metric_registry.list_definitions(channel_plugin_id)
    return {
        "tool": "analytics.list_metrics",
        "read_only": True,
        "definitions": [asdict(item) for item in definitions],
        "definition_versions": {item.metric_key: item.version for item in definitions},
    }


def analytics_get_publication_performance(runtime, config, publication_id: str) -> dict[str, Any]:
    service = runtime.analytics_read_model_service(config)
    payload = service.publication_performance(publication_id)
    payload.update({"tool": "analytics.get_publication_performance", "read_only": True})
    return payload


def analytics_get_content_performance(
    runtime, config, content_item_id: str, *, workspace_id: str = ""
) -> dict[str, Any]:
    service = runtime.analytics_read_model_service(config)
    payload = service.content_performance(content_item_id, workspace_id=workspace_id)
    payload.update({"tool": "analytics.get_content_performance", "read_only": True})
    return payload


def analytics_compare_revisions(runtime, config, content_item_id: str, *, workspace_id: str = "") -> dict[str, Any]:
    service = runtime.analytics_read_model_service(config)
    payload = service.revision_performance(content_item_id, workspace_id=workspace_id)
    payload.update({"tool": "analytics.compare_revisions", "read_only": True})
    return payload


def analytics_compare_variants(runtime, config, content_item_id: str, *, workspace_id: str = "") -> dict[str, Any]:
    service = runtime.analytics_read_model_service(config)
    payload = service.variant_performance(content_item_id, workspace_id=workspace_id)
    payload.update({"tool": "analytics.compare_variants", "read_only": True})
    return payload


def analytics_get_media_performance(runtime, config, asset_id: str, *, workspace_id: str = "") -> dict[str, Any]:
    service = runtime.analytics_read_model_service(config)
    payload = service.media_performance(asset_id, workspace_id=workspace_id)
    payload.update({"tool": "analytics.get_media_performance", "read_only": True})
    return payload


def analytics_get_campaign_performance(runtime, config, campaign_id: str, *, workspace_id: str = "") -> dict[str, Any]:
    service = runtime.analytics_read_model_service(config)
    payload = service.campaign_performance(campaign_id, workspace_id=workspace_id)
    payload.update({"tool": "analytics.get_campaign_performance", "read_only": True})
    return payload


def analytics_get_channel_performance(
    runtime,
    config,
    *,
    workspace_id: str = "",
    channel_plugin_id: str = "",
    channel_account_id: str = "",
) -> dict[str, Any]:
    service = runtime.analytics_read_model_service(config)
    payload = service.channel_performance(
        workspace_id=workspace_id,
        channel_plugin_id=channel_plugin_id,
        channel_account_id=channel_account_id,
    )
    payload.update({"tool": "analytics.get_channel_performance", "read_only": True})
    return payload


def analytics_get_freshness(runtime, config, *, workspace_id: str = "") -> dict[str, Any]:
    service = runtime.analytics_read_model_service(config)
    observations = service.observation_repository.list_all(workspace_id=workspace_id)
    payload = {
        "tool": "analytics.get_freshness",
        "read_only": True,
        "freshness": service.health_check(),
        "observation_count": len(observations),
        "definition_versions": {item.metric_key: item.version for item in service.metric_registry.list_definitions()},
    }
    return payload
