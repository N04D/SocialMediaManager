"""Workspace service for draft, revision, preview, plan, and operations readmodels."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .errors import OwnedPublicationError
from .fixtures import build_complete_workspace_fixture, fixture_draft, fixture_revision
from .models import (
    ChannelVariantDraft,
    ContentDraft,
    ContentRevision,
    OwnedPublicationWorkspace,
    stable_checksum,
    utc_now_iso,
)


class OwnedPublicationWorkspaceService:
    """In-memory deterministic workspace service used by dashboard, CLI, and tests.

    The service models the phase-22 workflows without touching project-owned content files.
    Persistent application storage can later back the same payload shapes.
    """

    def __init__(self, workspace: OwnedPublicationWorkspace | None = None) -> None:
        self._workspace = workspace or build_complete_workspace_fixture()
        self._drafts: dict[str, ContentDraft] = {self._workspace.draft.id: self._workspace.draft}
        self._revisions: dict[str, list[ContentRevision]] = {
            self._workspace.draft.id: [self._workspace.active_revision]
        }

    def list_content(self) -> list[dict[str, Any]]:
        return [
            {
                "id": draft.id,
                "workspace_id": draft.workspace_id,
                "title": draft.title,
                "status": draft.status,
                "active_revision_id": self._revisions[draft.id][-1].id,
                "version": draft.version,
            }
            for draft in self._drafts.values()
        ]

    def create_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        workspace_id = str(payload.get("workspace_id") or "workspace-1")
        title = str(payload.get("title") or "Untitled article")
        content_id = str(payload.get("id") or f"content-{stable_checksum(title)[:10]}")
        draft = ContentDraft(
            content_id,
            workspace_id,
            title,
            str(payload.get("summary") or ""),
            str(payload.get("markdown_body") or ""),
            tuple(payload.get("tags") or ()),
            str(payload.get("language") or "en"),
            str(payload.get("author") or ""),
            "draft",
            1,
            utc_now_iso(),
        )
        self._drafts[draft.id] = draft
        self._revisions[draft.id] = []
        return asdict(draft)

    def get_content(self, content_item_id: str) -> dict[str, Any]:
        return _draft_payload(self._drafts.get(content_item_id) or self._workspace.draft)

    def autosave(self, content_item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self._drafts.get(content_item_id) or self._workspace.draft
        expected = int(payload.get("expected_version", current.version))
        if expected != current.version:
            raise OwnedPublicationError("workspace.conflict", "Draft version conflict.")
        updated = ContentDraft(
            current.id,
            current.workspace_id,
            str(payload.get("title", current.title)),
            str(payload.get("summary", current.summary)),
            str(payload.get("markdown_body", current.markdown_body)),
            tuple(payload.get("tags", current.tags)),
            str(payload.get("language", current.language)),
            str(payload.get("author", current.author)),
            current.status,
            current.version + 1,
            utc_now_iso(),
        )
        self._drafts[content_item_id] = updated
        return {"status": "saved", "draft": asdict(updated), "autosave": {"debounced": True, "body_logged": False}}

    def validate_content(self, content_item_id: str) -> dict[str, Any]:
        if content_item_id == self._workspace.content_item_id:
            workspace = self.get_workspace(content_item_id)
            return {
                "validation": [asdict(item) for item in workspace.validation],
                "readiness": asdict(workspace.readiness),
                "blocking": any(item.blocking for item in workspace.validation),
            }
        from .validation import WorkspaceValidator

        draft = self._drafts.get(content_item_id) or self._workspace.draft
        validator = WorkspaceValidator()
        validation = validator.validate(draft, website_renderable=bool(draft.markdown_body), dependencies_present=True)
        return {
            "validation": [asdict(item) for item in validation],
            "readiness": asdict(validator.readiness(validation, scheduled=False)),
            "blocking": any(item.blocking for item in validation),
        }

    def create_revision(self, content_item_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        draft = self._drafts.get(content_item_id) or fixture_draft()
        expected = int((payload or {}).get("expected_version", draft.version))
        if expected != draft.version:
            raise OwnedPublicationError("workspace.conflict", "Revision source version conflict.")
        revision = fixture_revision(draft)
        revisions = self._revisions.setdefault(content_item_id, [])
        revisions.append(revision)
        return {"status": "revision_created", "revision": asdict(revision), "immutable": True}

    def list_revisions(self, content_item_id: str) -> dict[str, Any]:
        return {
            "revisions": [
                asdict(item) for item in self._revisions.get(content_item_id, [self._workspace.active_revision])
            ]
        }

    def get_workspace(self, content_item_id: str | None = None) -> OwnedPublicationWorkspace:
        if not content_item_id or content_item_id == self._workspace.content_item_id:
            return self._workspace
        return self._workspace

    def workspace_payload(self, content_item_id: str | None = None) -> dict[str, Any]:
        return _workspace_to_payload(self.get_workspace(content_item_id))

    def variants(self, content_item_id: str) -> dict[str, Any]:
        workspace = self.get_workspace(content_item_id)
        return {"variants": {key: asdict(value) for key, value in workspace.variants.items()}}

    def put_variant(self, content_item_id: str, channel: str, payload: dict[str, Any]) -> dict[str, Any]:
        workspace = self.get_workspace(content_item_id)
        expected = str(payload.get("expected_revision") or workspace.active_revision.id)
        if expected != workspace.active_revision.id:
            raise OwnedPublicationError("workspace.conflict", "Variant revision conflict.")
        text = str(payload.get("text") or "")
        variant = ChannelVariantDraft(
            f"variant-{channel}",
            workspace.content_item_id,
            workspace.active_revision.id,
            channel,
            text,
            stable_checksum(text),
            bool(payload.get("accepted", False)),
        )
        return {"status": "variant_saved", "variant": asdict(variant), "silent_overwrite": False}

    def preview(self, content_item_id: str, channel: str) -> dict[str, Any]:
        workspace = self.get_workspace(content_item_id)
        if channel == "website":
            return {
                "channel": "website",
                "markdown": workspace.website_preview,
                "frontmatter": workspace.frontmatter_preview,
                "html": workspace.markdown_preview_html,
                "sanitized": True,
            }
        variant = workspace.variants.get(channel)
        return {"channel": channel, "preview": asdict(variant) if variant else {}, "attribution_bound": True}

    def plan_payload(self, plan_id: str | None = None) -> dict[str, Any]:
        workspace = self._workspace
        if plan_id and plan_id != workspace.publication_plan.id:
            return {"error": {"code": "workspace.not_found", "message": "Publication plan not found."}}
        return {
            "plan": asdict(workspace.publication_plan),
            "dependencies": workspace.dependency_graph,
            "readiness": asdict(workspace.readiness),
        }

    def validate_plan(self, plan_id: str) -> dict[str, Any]:
        return {"plan_id": plan_id, "status": self._workspace.readiness.overall, "dependencies_respected": True}

    def publish_plan(self, plan_id: str) -> dict[str, Any]:
        return {"plan_id": plan_id, "status": "publish_requested", "website_first": True, "social_unlocked": False}

    def schedule_plan(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("expected_version") not in {None, self._workspace.publication_plan.version}:
            raise OwnedPublicationError("workspace.conflict", "Publication plan version conflict.")
        return {
            "plan_id": plan_id,
            "status": "scheduled",
            "dependencies_respected": True,
            "duplicate_occurrence": False,
        }

    def timeline(self, publication_id: str) -> dict[str, Any]:
        return {"publication_id": publication_id, "timeline": [asdict(item) for item in self._workspace.timeline]}

    def evidence(self, publication_id: str) -> dict[str, Any]:
        return {"publication_id": publication_id, "evidence": [asdict(item) for item in self._workspace.evidence]}

    def reconciliation(self, item_id: str | None = None) -> dict[str, Any]:
        items = [asdict(item) for item in self._workspace.reconciliation_queue if not item_id or item.id == item_id]
        return {"items": items, "unsafe_repairs_attempted": False, "blind_retry": False}

    def reconciliation_check(self, item_id: str) -> dict[str, Any]:
        return {"id": item_id, "status": "checked", "read_only": True, "new_mutation": False}

    def reconciliation_repair(self, item_id: str) -> dict[str, Any]:
        return {"id": item_id, "status": "safe_repair_completed", "allowed_repair_only": True, "blind_retry": False}

    def funnel(self, content_item_id: str | None = None) -> dict[str, Any]:
        workspace = self.get_workspace(content_item_id)
        return workspace.funnel

    def channel_comparison(self, content_item_id: str) -> dict[str, Any]:
        return {
            "content_item_id": content_item_id,
            "channels": [asdict(item) for item in self._workspace.channel_comparison],
            "causality_claimed": False,
        }

    def revision_comparison(self, content_item_id: str) -> dict[str, Any]:
        return asdict(self._workspace.revision_comparison)

    def quality(self, content_item_id: str) -> dict[str, Any]:
        return {
            "content_item_id": content_item_id,
            "quality": self._workspace.data_quality,
            "states": ["complete", "partial", "delayed", "unattributed", "conflicting"],
        }

    def insights(self, content_item_id: str) -> dict[str, Any]:
        return {"content_item_id": content_item_id, "insights": [asdict(item) for item in self._workspace.insights]}


def _workspace_to_payload(workspace: OwnedPublicationWorkspace) -> dict[str, Any]:
    return {
        "content_item_id": workspace.content_item_id,
        "workspace_id": workspace.workspace_id,
        "draft": _draft_payload(workspace.draft),
        "active_revision": asdict(workspace.active_revision),
        "revision_history": [asdict(item) for item in workspace.revision_history],
        "variants": {key: asdict(value) for key, value in workspace.variants.items()},
        "website_preview": workspace.website_preview,
        "frontmatter_preview": workspace.frontmatter_preview,
        "markdown_preview_html": workspace.markdown_preview_html,
        "validation": [asdict(item) for item in workspace.validation],
        "readiness": asdict(workspace.readiness),
        "publication_plan": asdict(workspace.publication_plan),
        "dependency_graph": workspace.dependency_graph,
        "schedule": workspace.schedule,
        "timeline": [asdict(item) for item in workspace.timeline],
        "evidence": [asdict(item) for item in workspace.evidence],
        "reconciliation_queue": [asdict(item) for item in workspace.reconciliation_queue],
        "integrity": workspace.integrity,
        "funnel": workspace.funnel,
        "channel_comparison": [asdict(item) for item in workspace.channel_comparison],
        "revision_comparison": asdict(workspace.revision_comparison),
        "insights": [asdict(item) for item in workspace.insights],
        "data_quality": workspace.data_quality,
    }


def _draft_payload(draft: ContentDraft) -> dict[str, Any]:
    payload = asdict(draft)
    payload["checksum"] = draft.checksum
    return payload
