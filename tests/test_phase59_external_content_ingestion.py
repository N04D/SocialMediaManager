from __future__ import annotations

from pathlib import Path
import pytest

from src.core.content.models import ContentCompleteness
from src.core.content.repository import InMemoryContentRepository, SqliteContentRepository
from src.core.content.resources import ExternalResourceSnapshot, ResourceRef
from src.core.runtime.errors import PlaybookExecutionError


def test_resource_ref_construction_and_canonicalization():
    ref = ResourceRef(provider="youtube", resource_type="video", external_id="vid-abc")
    assert ref.canonical_ref == "youtube:video:vid-abc"
    assert ref.to_dict()["canonical_ref"] == "youtube:video:vid-abc"

    ref_reconstructed = ResourceRef.from_dict(ref.to_dict())
    assert ref_reconstructed == ref


def test_external_resource_snapshot_creation_and_serialization():
    ref = ResourceRef(provider="youtube", resource_type="video", external_id="vid-abc")
    snapshot = ExternalResourceSnapshot(
        resource_ref=ref,
        provider_revision="etag-1",
        fields={"title": "Test Title", "description": "Test Description"},
    )
    serialized = snapshot.to_dict()
    deserialized = ExternalResourceSnapshot.from_dict(serialized)
    assert deserialized.resource_ref == ref
    assert deserialized.fields["title"] == "Test Title"


def test_inmemory_repository_initial_ingestion():
    repo = InMemoryContentRepository()
    ref = ResourceRef(provider="youtube", resource_type="video", external_id="vid-101")
    snapshot = ExternalResourceSnapshot(
        resource_ref=ref,
        fields={"title": "Original Title", "description": "Desc", "completeness": ContentCompleteness.METADATA_ONLY.value},
    )
    provenance = {"source_event_id": "evt-001", "execution_id": "exec-001", "workspace_id": "ws-001"}

    item, rev, created = repo.upsert_external_resource(snapshot=snapshot, provenance=provenance)
    assert created is True
    assert item.title == "Original Title"
    assert item.primary_source_ref == "youtube:video:vid-101"
    assert rev.revision_number == 1
    assert rev.checksum != ""
    assert item.metadata["completeness"] == "metadata_only"


def test_inmemory_repository_idempotent_reingestion():
    repo = InMemoryContentRepository()
    ref = ResourceRef(provider="youtube", resource_type="video", external_id="vid-101")
    snapshot = ExternalResourceSnapshot(
        resource_ref=ref,
        fields={"title": "Original Title", "description": "Desc"},
    )
    provenance = {"source_event_id": "evt-001", "execution_id": "exec-001"}

    item1, rev1, created1 = repo.upsert_external_resource(snapshot=snapshot, provenance=provenance)
    item2, rev2, created2 = repo.upsert_external_resource(snapshot=snapshot, provenance=provenance)

    assert created1 is True
    assert created2 is False  # Replay/reread without changes creates no duplicate revision
    assert item1.id == item2.id
    assert rev1.id == rev2.id
    assert len(repo.list_revisions(item1.id)) == 1


def test_inmemory_repository_metadata_change_creates_new_revision():
    repo = InMemoryContentRepository()
    ref = ResourceRef(provider="youtube", resource_type="video", external_id="vid-101")
    snap1 = ExternalResourceSnapshot(resource_ref=ref, fields={"title": "Title A", "description": "Desc"})
    snap2 = ExternalResourceSnapshot(resource_ref=ref, fields={"title": "Title B", "description": "Desc"})
    prov = {"execution_id": "exec-001"}

    item1, rev1, created1 = repo.upsert_external_resource(snapshot=snap1, provenance=prov)
    item2, rev2, created2 = repo.upsert_external_resource(snapshot=snap2, provenance=prov)

    assert created1 is True
    assert created2 is True  # Metadata change creates new revision
    assert item1.id == item2.id
    assert rev2.revision_number == 2
    assert item2.title == "Title B"

    revs = repo.list_revisions(item1.id)
    assert len(revs) == 2
    assert revs[0].title == "Title A"
    assert revs[1].title == "Title B"


def test_sqlite_repository_persistence_and_provenance(tmp_path: Path):
    db_path = tmp_path / "content.db"
    repo = SqliteContentRepository(db_path)
    ref = ResourceRef(provider="youtube", resource_type="video", external_id="vid-sqlite-1")
    snapshot = ExternalResourceSnapshot(
        resource_ref=ref,
        fields={"title": "Persisted Title", "description": "Persisted Desc"},
    )
    provenance = {"source_event_id": "evt-sql-1", "execution_id": "exec-sql-1", "workspace_id": "ws-001"}

    item, rev, created = repo.upsert_external_resource(snapshot=snapshot, provenance=provenance)
    assert created is True

    # Reload from fresh DB instance
    repo2 = SqliteContentRepository(db_path)
    reloaded_item = repo2.get_content_item(item.id)
    assert reloaded_item is not None
    assert reloaded_item.title == "Persisted Title"
    assert reloaded_item.source_provenance["source_event_id"] == "evt-sql-1"

    revs = repo2.list_revisions(item.id)
    assert len(revs) == 1
    assert revs[0].title == "Persisted Title"


def test_different_videos_create_distinct_entities():
    repo = InMemoryContentRepository()
    ref_a = ResourceRef(provider="youtube", resource_type="video", external_id="vid-A")
    ref_b = ResourceRef(provider="youtube", resource_type="video", external_id="vid-B")
    snap_a = ExternalResourceSnapshot(resource_ref=ref_a, fields={"title": "Video A"})
    snap_b = ExternalResourceSnapshot(resource_ref=ref_b, fields={"title": "Video B"})

    item_a, _, _ = repo.upsert_external_resource(snapshot=snap_a, provenance={})
    item_b, _, _ = repo.upsert_external_resource(snapshot=snap_b, provenance={})

    assert item_a.id != item_b.id
    assert item_a.primary_source_ref == "youtube:video:vid-A"
    assert item_b.primary_source_ref == "youtube:video:vid-B"


def test_secret_canary_rejection_in_repository():
    repo = InMemoryContentRepository()
    ref = ResourceRef(provider="youtube", resource_type="video", external_id="vid-canary")
    snap = ExternalResourceSnapshot(
        resource_ref=ref,
        fields={"title": "Canary", "access_token": "secret-token-canary-123"},
    )
    with pytest.raises(PlaybookExecutionError):
        repo.upsert_external_resource(snapshot=snap, provenance={})
