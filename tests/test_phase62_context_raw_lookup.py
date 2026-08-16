from __future__ import annotations

import json

import pytest

from src.core.content.publications import PublicationGraphError

from tests.test_phase62_content_performance_context import _build_context_fixture


def test_explicit_raw_metrics_lookup_returns_payload_but_context_does_not(tmp_path):
    item, service, youtube_publication = _build_context_fixture(tmp_path)
    context_payload = service.get_context(item.id).to_dict()
    youtube_context = [
        publication
        for publication in context_payload["publications"]
        if publication["publication_id"] == youtube_publication.publication_id
    ][0]
    snapshot_id = youtube_context["metrics_history"][0]["snapshot_id"]

    raw = service.get_raw_metrics_snapshot(snapshot_id)

    assert "raw_metrics_payload" not in json.dumps(context_payload, sort_keys=True)
    assert raw["snapshot_id"] == snapshot_id
    assert raw["raw_metrics_payload"]["statistics"]["viewCount"] == "100"
    assert raw["raw_metrics_payload"]["debug_canary"] == "SECRET_CANARY"
    assert raw["redaction"] == {
        "provider_headers_included": False,
        "raw_metrics_included": True,
        "raw_transcript_included": False,
        "secrets_included": False,
    }


def test_missing_raw_metrics_snapshot_returns_structured_error(tmp_path):
    _, service, _ = _build_context_fixture(tmp_path)

    with pytest.raises(PublicationGraphError) as error:
        service.get_raw_metrics_snapshot("metrics_snapshot_missing")

    assert error.value.code == "METRICS_NOT_AVAILABLE"
