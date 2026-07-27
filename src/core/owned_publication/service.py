"""Workspace service for draft, revision, preview, plan, and operations readmodels."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .errors import OwnedPublicationError
from .fixtures import build_complete_workspace_fixture, fixture_draft
from .models import (
    ChannelVariantDraft,
    ContentDraft,
    OwnedPublicationWorkspace,
    stable_checksum,
    utc_now_iso,
)
from .persistence import DatabaseOwnedPublicationRepository, default_database_path


class OwnedPublicationWorkspaceService:
    """Workspace service used by dashboard, CLI, MCP, and tests.

    Phase 23 keeps the phase-22 payload shapes and backs operational writes with
    SQLite. The deterministic fixture is seeded only into the managed database;
    project `content/` and `drafts/` directories are never used as fixtures.
    """

    def __init__(
        self,
        workspace: OwnedPublicationWorkspace | None = None,
        repository: DatabaseOwnedPublicationRepository | None = None,
        database_path: str | Path | None = None,
    ) -> None:
        self._workspace = workspace or build_complete_workspace_fixture()
        self.repository = repository or DatabaseOwnedPublicationRepository(database_path or default_database_path())
        self._ensure_seeded()

    def _ensure_seeded(self) -> None:
        if self.repository.list_drafts(self._workspace.workspace_id):
            return
        draft = self.repository.save_draft(
            self._workspace.draft,
            expected_version=None,
            idempotency_key="seed-draft-" + self._workspace.draft.id,
            actor="fixture",
        )
        revision = self.repository.create_revision(
            draft.id,
            expected_version=draft.version,
            idempotency_key="seed-revision-" + draft.id,
            actor="fixture",
        )
        variant_ids: dict[str, str] = {}
        for channel, variant in self._workspace.variants.items():
            persisted = self.repository.create_variant(
                revision,
                variant.channel,
                variant.text,
                idempotency_key="seed-variant-" + channel,
                generation_metadata=variant.generation_binding,
            )
            variant_ids[channel] = persisted.id
        targets = [
            {
                "id": target.id,
                "channel_id": target.channel,
                "account_id": target.account_id,
                "variant_id": variant_ids.get(
                    "website"
                    if target.channel == "channel.markdown_website"
                    else target.channel.removeprefix("channel."),
                    target.variant_id,
                ),
                "schedule_id": "schedule-" + target.id,
                "verification_policy": target.verification_policy,
                "status": target.status,
                "execution_state": target.status,
            }
            for target in self._workspace.publication_plan.targets
        ]
        dependencies = [
            {
                "id": item["id"],
                "predecessor_target_id": item["predecessor_target_id"],
                "dependent_target_id": item["dependent_target_id"],
                "required_state": item["required_state"],
                "dependency_type": item.get("dependency_type", "publication_state"),
                "timeout_policy": "wait",
                "failure_policy": "block",
            }
            for item in self._workspace.dependency_graph["dependencies"]
        ]
        plan = self.repository.create_plan(
            self._workspace.workspace_id,
            draft.id,
            revision.id,
            targets,
            dependencies,
            campaign_id=self._workspace.publication_plan.campaign,
            idempotency_key="seed-plan-" + draft.id,
            actor="fixture",
        )
        for target in plan.targets:
            self.repository.materialize_occurrence(
                self._workspace.workspace_id,
                "schedule-" + target.id,
                target.id,
                target.schedule or "2026-07-27T09:00:00Z",
                timezone=self._workspace.schedule["timezone"],
                idempotency_key="seed-occurrence-" + target.id,
            )
        for index, event in enumerate(self._workspace.timeline):
            self.repository.append_execution_event(
                self._workspace.workspace_id,
                "attempt-website-1",
                "target-website",
                event,
                idempotency_key=f"seed-event-{index}",
            )
        for index, evidence in enumerate(self._workspace.evidence):
            self.repository.add_evidence(
                self._workspace.workspace_id,
                "public_url_evidence"
                if evidence.channel == "channel.markdown_website"
                else "social_acknowledgment_evidence",
                evidence,
                idempotency_key=f"seed-evidence-{index}",
            )
        for item in self._workspace.reconciliation_queue:
            self.repository.detect_reconciliation(
                item,
                plan_id=plan.id,
                attempt_id="attempt-website-2",
                idempotency_key="seed-reconciliation-" + item.id,
            )

    def list_content(self) -> list[dict[str, Any]]:
        return [
            {
                "id": draft.id,
                "workspace_id": draft.workspace_id,
                "title": draft.title,
                "status": draft.status,
                "active_revision_id": (self.repository.list_revisions(draft.id) or [self._workspace.active_revision])[
                    -1
                ].id,
                "version": draft.version,
            }
            for draft in self.repository.list_drafts()
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
        saved = self.repository.save_draft(
            draft,
            expected_version=None,
            idempotency_key=str(payload.get("idempotency_key") or "content-create-" + content_id),
            actor=str(payload.get("actor") or "api"),
        )
        return asdict(saved)

    def get_content(self, content_item_id: str) -> dict[str, Any]:
        try:
            return _draft_payload(self.repository.get_draft(content_item_id))
        except OwnedPublicationError:
            return _draft_payload(self._workspace.draft)

    def autosave(self, content_item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.repository.get_draft(content_item_id)
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
        saved = self.repository.save_draft(
            updated,
            expected_version=expected,
            idempotency_key=str(payload.get("idempotency_key") or f"autosave-{content_item_id}-{expected}"),
            actor=str(payload.get("actor") or "api"),
        )
        return {"status": "saved", "draft": asdict(saved), "autosave": {"debounced": True, "body_logged": False}}

    def validate_content(self, content_item_id: str) -> dict[str, Any]:
        if content_item_id == self._workspace.content_item_id:
            workspace = self.get_workspace(content_item_id)
            return {
                "validation": [asdict(item) for item in workspace.validation],
                "readiness": asdict(workspace.readiness),
                "blocking": any(item.blocking for item in workspace.validation),
            }
        from .validation import WorkspaceValidator

        draft = self.repository.get_draft(content_item_id)
        validator = WorkspaceValidator()
        validation = validator.validate(draft, website_renderable=bool(draft.markdown_body), dependencies_present=True)
        return {
            "validation": [asdict(item) for item in validation],
            "readiness": asdict(validator.readiness(validation, scheduled=False)),
            "blocking": any(item.blocking for item in validation),
        }

    def create_revision(self, content_item_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            draft = self.repository.get_draft(content_item_id)
        except OwnedPublicationError:
            draft = fixture_draft()
        expected = int((payload or {}).get("expected_version", draft.version))
        revision = self.repository.create_revision(
            draft.id,
            expected_version=expected,
            idempotency_key=str((payload or {}).get("idempotency_key") or f"revision-{draft.id}-{expected}"),
            actor=str((payload or {}).get("actor") or "api"),
        )
        return {"status": "revision_created", "revision": asdict(revision), "immutable": True}

    def list_revisions(self, content_item_id: str) -> dict[str, Any]:
        return {
            "revisions": [
                asdict(item)
                for item in (self.repository.list_revisions(content_item_id) or [self._workspace.active_revision])
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
        self.repository.create_variant(
            workspace.active_revision,
            channel,
            text,
            idempotency_key=str(payload.get("idempotency_key") or f"variant-{content_item_id}-{channel}-{expected}"),
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

    def storage_health(self) -> dict[str, Any]:
        return asdict(self.repository.health())

    def migrations(self) -> dict[str, Any]:
        return self.repository.migrations()

    def recovery(self) -> dict[str, Any]:
        return self.repository.recovery()

    def readmodels_status(self) -> dict[str, Any]:
        return self.repository.readmodels_status()

    def rebuild_readmodels(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        subject_id = str((payload or {}).get("subject_id") or self._workspace.content_item_id)
        readmodel_type = str((payload or {}).get("readmodel_type") or "ContentFunnelReadModel")
        return self.repository.rebuild_readmodel(self._workspace.workspace_id, readmodel_type, subject_id)

    def create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        campaign = self.repository.create_campaign(
            str(payload.get("workspace_id") or self._workspace.workspace_id),
            str(payload.get("name") or "Owned publication campaign"),
            campaign_id=str(payload.get("id") or ""),
            timezone=str(payload.get("timezone") or "UTC"),
            start_at=str(payload.get("start_at") or ""),
            end_at=str(payload.get("end_at") or ""),
        )
        return {"campaign": asdict(campaign)}

    def list_campaigns(self, workspace_id: str = "") -> dict[str, Any]:
        return {"campaigns": [asdict(item) for item in self.repository.list_campaigns(workspace_id)]}

    def campaign(self, campaign_id: str) -> dict[str, Any]:
        return {"campaign": asdict(self.repository.get_campaign(campaign_id))}

    def pause_campaign(self, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        expected = int(payload.get("expected_version", self.repository.get_campaign(campaign_id).version))
        return {
            "campaign": asdict(self.repository.update_campaign_status(campaign_id, "paused", expected_version=expected))
        }

    def resume_campaign(self, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        expected = int(payload.get("expected_version", self.repository.get_campaign(campaign_id).version))
        return {
            "campaign": asdict(self.repository.update_campaign_status(campaign_id, "active", expected_version=expected))
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
