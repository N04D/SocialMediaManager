from __future__ import annotations

from src.core.content.models import ContentCompleteness, Publication, PublicationState
from src.core.content.publications import (
    InMemoryPublicationRepository,
    publication_identity,
    reconcile_publication_for_external_content,
)
from src.core.content.repository import InMemoryContentRepository
from src.core.content.resources import ExternalResourceSnapshot, ResourceRef


def _snapshot(video_id: str = "vid-61", *, title: str = "Title A") -> ExternalResourceSnapshot:
    return ExternalResourceSnapshot(
        resource_ref=ResourceRef(provider="youtube", resource_type="video", external_id=video_id, install_id="yt"),
        fields={
            "completeness": ContentCompleteness.METADATA_ONLY.value,
            "description": "Video body",
            "published_at": "2026-08-10T00:00:00Z",
            "title": title,
            "video_id": video_id,
        },
    )


def test_create_and_reconcile_youtube_publication_dedupes_same_external_video():
    content_repo = InMemoryContentRepository()
    item, revision, _ = content_repo.upsert_external_resource(
        snapshot=_snapshot(), provenance={"workspace_id": "ws", "execution_id": "exec-1"}
    )
    publications = InMemoryPublicationRepository()

    first, first_created = reconcile_publication_for_external_content(
        content_repository=content_repo,
        publication_repository=publications,
        canonical_ref=item.primary_source_ref,
        install_id="yt-install",
        provenance={"source_execution_id": "exec-1", "source_event_id": "evt-1"},
    )
    second, second_created = reconcile_publication_for_external_content(
        content_repository=content_repo,
        publication_repository=publications,
        canonical_ref=item.primary_source_ref,
        install_id="yt-install",
        provenance={"source_execution_id": "exec-2"},
    )

    assert first_created is True
    assert second_created is False
    assert first.publication_id == second.publication_id
    assert first.content_entity_id == item.id
    assert first.content_revision_id == revision.id
    assert first.provider == "youtube"
    assert len(publications.list_by_content(item.id)) == 1


def test_changed_metadata_keeps_same_publication_and_updates_revision_relation():
    content_repo = InMemoryContentRepository()
    item, _revision1, _ = content_repo.upsert_external_resource(
        snapshot=_snapshot(title="Title A"), provenance={"workspace_id": "ws"}
    )
    publications = InMemoryPublicationRepository()
    first, _ = reconcile_publication_for_external_content(
        content_repository=content_repo,
        publication_repository=publications,
        canonical_ref=item.primary_source_ref,
        install_id="yt-install",
    )

    updated, revision2, changed = content_repo.upsert_external_resource(
        snapshot=_snapshot(title="Title B"), provenance={"workspace_id": "ws", "execution_id": "exec-2"}
    )
    second, created = reconcile_publication_for_external_content(
        content_repository=content_repo,
        publication_repository=publications,
        canonical_ref=updated.primary_source_ref,
        install_id="yt-install",
        content_revision_id=revision2.id,
    )

    assert changed is True
    assert created is False
    assert second.publication_id == first.publication_id
    assert second.content_revision_id == revision2.id
    assert len(publications.list_by_content(updated.id)) == 1


def test_multiple_publications_for_one_content_entity_are_independent():
    content_repo = InMemoryContentRepository()
    item, revision, _ = content_repo.upsert_external_resource(
        snapshot=_snapshot(), provenance={"workspace_id": "ws"}
    )
    publications = InMemoryPublicationRepository()
    yt, _ = reconcile_publication_for_external_content(
        content_repository=content_repo,
        publication_repository=publications,
        canonical_ref=item.primary_source_ref,
        install_id="yt-install",
    )
    web_ref = {"provider": "website", "resource_type": "article", "external_id": "article-1", "canonical_ref": "website:article:article-1"}
    website = Publication(
        publication_id=publication_identity(provider="website", install_id="web-install", external_ref=web_ref),
        content_entity_id=item.id,
        content_revision_id=revision.id,
        provider="website",
        install_id="web-install",
        external_ref=web_ref,
        published_at="2026-08-11T00:00:00Z",
        observed_at="2026-08-11T00:01:00Z",
        state=PublicationState.PUBLISHED.value,
        provenance={"content_entity_id": item.id, "content_revision_id": revision.id},
    )
    saved_website, created = publications.save(website)

    assert created is True
    assert yt.publication_id != saved_website.publication_id
    assert {item.provider for item in publications.list_by_content(item.id)} == {"youtube", "website"}
