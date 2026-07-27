from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.core.owned_publication import (
    CAMPAIGN_WORKSPACE_CONTRACT_VERSION,
    FUNNEL_READMODEL_CONTRACT_VERSION,
    OWNED_PUBLICATION_MIGRATION_CONTRACT_VERSION,
    OWNED_PUBLICATION_PERSISTENCE_VERSION,
    OWNED_PUBLICATION_STORAGE_CONTRACT_VERSION,
    PUBLICATION_EVIDENCE_STORAGE_CONTRACT_VERSION,
    RECONCILIATION_LEASE_CONTRACT_VERSION,
)
from src.core.owned_publication.errors import OwnedPublicationError
from src.core.owned_publication.fixtures import fixture_draft
from src.core.owned_publication.persistence import DatabaseOwnedPublicationRepository


class OwnedPublicationPersistencePhase23Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "owned.sqlite3"
        self.repo = DatabaseOwnedPublicationRepository(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_storage_health_migrations_and_schema_tables(self) -> None:
        self.assertEqual(OWNED_PUBLICATION_PERSISTENCE_VERSION, "0.1.0")
        self.assertEqual(OWNED_PUBLICATION_STORAGE_CONTRACT_VERSION, "1.0")
        self.assertEqual(OWNED_PUBLICATION_MIGRATION_CONTRACT_VERSION, "1.0")
        self.assertEqual(RECONCILIATION_LEASE_CONTRACT_VERSION, "1.0")
        self.assertEqual(PUBLICATION_EVIDENCE_STORAGE_CONTRACT_VERSION, "1.0")
        self.assertEqual(CAMPAIGN_WORKSPACE_CONTRACT_VERSION, "1.0")
        self.assertEqual(FUNNEL_READMODEL_CONTRACT_VERSION, "1.0")
        health = self.repo.health()
        self.assertEqual(health.status, "ready")
        self.assertEqual(health.schema_version, 1)
        self.assertTrue(health.foreign_keys)
        self.assertEqual(health.production_source, "database-backed")
        migrations = self.repo.migrations()
        self.assertEqual(migrations["migrations"][0]["status"], "applied")
        with sqlite3.connect(self.db) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("owned_publication_drafts", tables)

    def test_draft_save_reload_conflict_and_idempotency(self) -> None:
        draft = fixture_draft()
        saved = self.repo.save_draft(draft, expected_version=None, idempotency_key="draft-1")
        self.assertEqual(saved.id, draft.id)
        self.assertEqual(self.repo.get_draft(draft.id).title, draft.title)
        retried = self.repo.save_draft(draft, expected_version=None, idempotency_key="draft-1")
        self.assertEqual(retried.id, saved.id)
        changed = fixture_draft()
        changed = type(changed)(**{**changed.__dict__, "title": "Changed"})
        with self.assertRaises(OwnedPublicationError):
            self.repo.save_draft(changed, expected_version=99, idempotency_key="draft-2")
        with self.assertRaises(OwnedPublicationError):
            self.repo.save_draft(changed, expected_version=None, idempotency_key="draft-1")

    def test_revisions_variants_snapshots_and_plans_are_durable(self) -> None:
        draft = self.repo.save_draft(fixture_draft(), expected_version=None, idempotency_key="draft")
        revision = self.repo.create_revision(draft.id, expected_version=draft.version, idempotency_key="revision")
        self.assertEqual(
            self.repo.create_revision(draft.id, expected_version=draft.version, idempotency_key="revision"), revision
        )
        variant = self.repo.create_variant(
            revision, "channel.markdown_website", revision.markdown_body, idempotency_key="variant"
        )
        plan = self.repo.create_plan(
            revision.workspace_id,
            revision.content_item_id,
            revision.id,
            [
                {
                    "id": "target-website",
                    "channel_id": "channel.markdown_website",
                    "account_id": "account",
                    "variant_id": variant.id,
                    "verification_policy": "public_url",
                    "status": "draft",
                    "execution_state": "not_started",
                }
            ],
            [],
            idempotency_key="plan",
        )
        reloaded = DatabaseOwnedPublicationRepository(self.db)
        self.assertEqual(reloaded.get_revision(revision.id).checksum, revision.checksum)
        self.assertEqual(reloaded.get_variant(variant.id).content_revision_id, revision.id)
        self.assertEqual(reloaded.get_plan(plan.id).targets[0].id, "target-website")

    def test_immutable_update_is_blocked_by_no_update_api(self) -> None:
        public_methods = {name for name in dir(self.repo) if not name.startswith("_")}
        self.assertNotIn("update_revision", public_methods)
        self.assertNotIn("update_evidence", public_methods)
        self.assertNotIn("delete_revision", public_methods)


if __name__ == "__main__":
    unittest.main()
