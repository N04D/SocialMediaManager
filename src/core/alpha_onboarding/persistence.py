"""SQLite persistence for alpha onboarding sessions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.core.owned_publication.persistence import default_database_path

from .errors import AlphaOnboardingError
from .models import (
    AlphaGuidedRecovery,
    AlphaOnboardingEvent,
    AlphaOnboardingFinding,
    AlphaOnboardingSession,
    FirstPublicationReadmodel,
    stable_checksum,
    utc_now_iso,
)

SCHEMA_VERSION = 1
MIGRATION_ID = "001_alpha_onboarding"
MIGRATION_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS alpha_onboarding_schema_migrations (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alpha_onboarding_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    current_step TEXT NOT NULL,
    completed_steps_json TEXT NOT NULL,
    skipped_optional_steps_json TEXT NOT NULL,
    blocking_findings_json TEXT NOT NULL,
    warning_findings_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    version INTEGER NOT NULL,
    contract_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alpha_onboarding_steps (
    session_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    validation_state TEXT NOT NULL,
    completion_state TEXT NOT NULL,
    resource_bindings_json TEXT NOT NULL,
    stale_reason TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY (session_id, step_id)
);
CREATE TABLE IF NOT EXISTS alpha_onboarding_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    safe_status TEXT NOT NULL,
    safe_error_code TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alpha_onboarding_resource_bindings (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    resource_checksum TEXT NOT NULL,
    safe_metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, step_id, resource_type, resource_id)
);
CREATE TABLE IF NOT EXISTS alpha_onboarding_findings (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    explanation TEXT NOT NULL,
    status TEXT NOT NULL,
    related_resource_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alpha_onboarding_recovery_actions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    finding_code TEXT NOT NULL,
    safe_actions_json TEXT NOT NULL,
    blocked_actions_json TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    executed_at TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alpha_first_publication_readmodels (
    session_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    content_item_id TEXT NOT NULL,
    content_revision_id TEXT NOT NULL,
    website_account_id TEXT NOT NULL,
    publication_plan_id TEXT NOT NULL,
    execution_request_id TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    analytics_sync_status TEXT NOT NULL,
    funnel_status TEXT NOT NULL,
    public_url TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    mutation_summary_json TEXT NOT NULL,
    checksum_bindings_json TEXT NOT NULL,
    timeline_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _tuple(value: str) -> tuple[str, ...]:
    return tuple(json.loads(value or "[]"))


class DatabaseAlphaOnboardingRepository:
    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = Path(database_path or default_database_path())
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def migrate(self) -> None:
        checksum = stable_checksum(MIGRATION_SQL)
        with self.connect() as conn:
            conn.executescript(MIGRATION_SQL)
            conn.execute(
                """
                INSERT OR REPLACE INTO alpha_onboarding_schema_migrations
                (id, version, checksum, applied_at, status) VALUES (?, ?, ?, ?, ?)
                """,
                (MIGRATION_ID, SCHEMA_VERSION, checksum, utc_now_iso(), "applied"),
            )

    def create_session(self, session: AlphaOnboardingSession) -> AlphaOnboardingSession:
        with self.connect() as conn:
            active = conn.execute(
                """
                SELECT id FROM alpha_onboarding_sessions
                WHERE workspace_id = ? AND status NOT IN ('completed', 'cancelled', 'failed')
                """,
                (session.workspace_id,),
            ).fetchone()
            if active:
                raise AlphaOnboardingError(
                    "alpha_onboarding.duplicate_active_session",
                    "Workspace already has an active onboarding session.",
                    status_code=409,
                )
            conn.execute(
                """
                INSERT INTO alpha_onboarding_sessions
                (id, workspace_id, mode, status, current_step, completed_steps_json, skipped_optional_steps_json,
                 blocking_findings_json, warning_findings_json, created_by, created_at, updated_at, completed_at,
                 version, contract_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _session_params(session),
            )
        return session

    def save_session(
        self, session: AlphaOnboardingSession, *, expected_version: int | None = None
    ) -> AlphaOnboardingSession:
        current = self.get_session(session.id)
        if expected_version is not None and current.version != expected_version:
            raise AlphaOnboardingError(
                "alpha_onboarding.version_conflict", "Onboarding session version conflict.", status_code=409
            )
        updated = AlphaOnboardingSession(
            **{**asdict(session), "version": current.version + 1, "updated_at": utc_now_iso()}
        )
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE alpha_onboarding_sessions
                SET workspace_id=?, mode=?, status=?, current_step=?, completed_steps_json=?,
                    skipped_optional_steps_json=?, blocking_findings_json=?, warning_findings_json=?,
                    created_by=?, created_at=?, updated_at=?, completed_at=?, version=?, contract_version=?
                WHERE id=?
                """,
                (
                    updated.workspace_id,
                    updated.mode,
                    updated.status,
                    updated.current_step,
                    _json(updated.completed_steps),
                    _json(updated.skipped_optional_steps),
                    _json(updated.blocking_findings),
                    _json(updated.warning_findings),
                    updated.created_by,
                    updated.created_at,
                    updated.updated_at,
                    updated.completed_at,
                    updated.version,
                    updated.contract_version,
                    updated.id,
                ),
            )
        return updated

    def get_session(self, session_id: str) -> AlphaOnboardingSession:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM alpha_onboarding_sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            raise AlphaOnboardingError(
                "alpha_onboarding.session_not_found", "Onboarding session not found.", status_code=404
            )
        return _session_from_row(row)

    def list_sessions(self) -> list[AlphaOnboardingSession]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM alpha_onboarding_sessions ORDER BY created_at DESC").fetchall()
        return [_session_from_row(row) for row in rows]

    def upsert_step_state(
        self,
        session_id: str,
        step_id: str,
        *,
        validation_state: str,
        completion_state: str,
        resource_bindings: dict[str, str] | None = None,
        stale_reason: str = "",
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self.connect() as conn:
            current = conn.execute(
                "SELECT version FROM alpha_onboarding_steps WHERE session_id=? AND step_id=?",
                (session_id, step_id),
            ).fetchone()
            version = int(current["version"]) + 1 if current else 1
            conn.execute(
                """
                INSERT OR REPLACE INTO alpha_onboarding_steps
                (session_id, step_id, validation_state, completion_state, resource_bindings_json, stale_reason, updated_at, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    step_id,
                    validation_state,
                    completion_state,
                    _json(resource_bindings or {}),
                    stale_reason,
                    now,
                    version,
                ),
            )
        return self.get_step_state(session_id, step_id)

    def get_step_state(self, session_id: str, step_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM alpha_onboarding_steps WHERE session_id=? AND step_id=?",
                (session_id, step_id),
            ).fetchone()
        if not row:
            return {
                "session_id": session_id,
                "step_id": step_id,
                "validation_state": "not_run",
                "completion_state": "not_started",
                "resource_bindings": {},
                "stale_reason": "",
                "version": 0,
            }
        return {
            "session_id": row["session_id"],
            "step_id": row["step_id"],
            "validation_state": row["validation_state"],
            "completion_state": row["completion_state"],
            "resource_bindings": json.loads(row["resource_bindings_json"]),
            "stale_reason": row["stale_reason"],
            "updated_at": row["updated_at"],
            "version": row["version"],
        }

    def list_step_states(self, session_id: str) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM alpha_onboarding_steps WHERE session_id=?", (session_id,)).fetchall()
        return {row["step_id"]: self.get_step_state(session_id, row["step_id"]) for row in rows}

    def bind_resource(
        self,
        session_id: str,
        step_id: str,
        workspace_id: str,
        resource_type: str,
        resource_id: str,
        safe_metadata: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        checksum = stable_checksum(
            {"resource_type": resource_type, "resource_id": resource_id, "metadata": safe_metadata or {}}
        )
        binding_id = "alpha-binding-" + stable_checksum([session_id, step_id, resource_type, resource_id])[:20]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO alpha_onboarding_resource_bindings
                (id, session_id, step_id, workspace_id, resource_type, resource_id, resource_checksum, safe_metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    binding_id,
                    session_id,
                    step_id,
                    workspace_id,
                    resource_type,
                    resource_id,
                    checksum,
                    _json(safe_metadata or {}),
                    utc_now_iso(),
                ),
            )
        return {
            "id": binding_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "resource_checksum": checksum,
        }

    def list_bindings(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM alpha_onboarding_resource_bindings WHERE session_id=? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "step_id": row["step_id"],
                "workspace_id": row["workspace_id"],
                "resource_type": row["resource_type"],
                "resource_id": row["resource_id"],
                "resource_checksum": row["resource_checksum"],
                "safe_metadata": json.loads(row["safe_metadata_json"]),
            }
            for row in rows
        ]

    def append_event(self, event: AlphaOnboardingEvent) -> AlphaOnboardingEvent:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO alpha_onboarding_events
                (id, session_id, step_id, event_type, resource_type, resource_id, safe_status, safe_error_code, actor_id, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.session_id,
                    event.step_id,
                    event.event_type,
                    event.resource_type,
                    event.resource_id,
                    event.safe_status,
                    event.safe_error_code,
                    event.actor_id,
                    event.occurred_at,
                ),
            )
        return event

    def events(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM alpha_onboarding_events WHERE session_id=? ORDER BY occurred_at, id",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_findings(self, session_id: str, findings: list[AlphaOnboardingFinding]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM alpha_onboarding_findings WHERE session_id=?", (session_id,))
            for finding in findings:
                conn.execute(
                    """
                    INSERT INTO alpha_onboarding_findings
                    (id, session_id, step_id, code, severity, explanation, status, related_resource_ids_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding.id,
                        finding.session_id,
                        finding.step_id,
                        finding.code,
                        finding.severity,
                        finding.explanation,
                        finding.status,
                        _json(finding.related_resource_ids),
                        finding.created_at or utc_now_iso(),
                    ),
                )

    def findings(self, session_id: str) -> list[AlphaOnboardingFinding]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM alpha_onboarding_findings WHERE session_id=? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        return [
            AlphaOnboardingFinding(
                id=row["id"],
                session_id=row["session_id"],
                step_id=row["step_id"],
                code=row["code"],
                severity=row["severity"],
                explanation=row["explanation"],
                status=row["status"],
                related_resource_ids=_tuple(row["related_resource_ids_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def save_recovery(
        self, recovery: AlphaGuidedRecovery, *, status: str = "available", result: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        action_id = "alpha-recovery-" + stable_checksum(asdict(recovery))[:20]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO alpha_onboarding_recovery_actions
                (id, session_id, step_id, finding_code, safe_actions_json, blocked_actions_json, execution_status, executed_at, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    recovery.session_id,
                    recovery.step_id,
                    recovery.finding_code,
                    _json(recovery.safe_actions),
                    _json(recovery.blocked_actions),
                    status,
                    utc_now_iso() if status != "available" else "",
                    _json(result or {}),
                ),
            )
        return {"id": action_id, "status": status}

    def save_first_publication(self, readmodel: FirstPublicationReadmodel) -> FirstPublicationReadmodel:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO alpha_first_publication_readmodels
                (session_id, workspace_id, content_item_id, content_revision_id, website_account_id, publication_plan_id,
                 execution_request_id, verification_status, analytics_sync_status, funnel_status, public_url,
                 evidence_ids_json, mutation_summary_json, checksum_bindings_json, timeline_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    readmodel.session_id,
                    readmodel.workspace_id,
                    readmodel.content_item_id,
                    readmodel.content_revision_id,
                    readmodel.website_account_id,
                    readmodel.publication_plan_id,
                    readmodel.execution_request_id,
                    readmodel.verification_status,
                    readmodel.analytics_sync_status,
                    readmodel.funnel_status,
                    readmodel.public_url,
                    _json(readmodel.evidence_ids),
                    _json(readmodel.mutation_summary),
                    _json(readmodel.checksum_bindings),
                    _json(readmodel.timeline),
                    readmodel.updated_at or utc_now_iso(),
                ),
            )
        return readmodel

    def first_publication(self, session_id: str) -> FirstPublicationReadmodel:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM alpha_first_publication_readmodels WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if not row:
            session = self.get_session(session_id)
            return FirstPublicationReadmodel(
                session_id=session.id, workspace_id=session.workspace_id, updated_at=utc_now_iso()
            )
        return FirstPublicationReadmodel(
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            content_item_id=row["content_item_id"],
            content_revision_id=row["content_revision_id"],
            website_account_id=row["website_account_id"],
            publication_plan_id=row["publication_plan_id"],
            execution_request_id=row["execution_request_id"],
            verification_status=row["verification_status"],
            analytics_sync_status=row["analytics_sync_status"],
            funnel_status=row["funnel_status"],
            public_url=row["public_url"],
            evidence_ids=_tuple(row["evidence_ids_json"]),
            mutation_summary=_tuple(row["mutation_summary_json"]),
            checksum_bindings=json.loads(row["checksum_bindings_json"]),
            timeline=tuple(json.loads(row["timeline_json"])),
            updated_at=row["updated_at"],
        )


def _session_params(session: AlphaOnboardingSession) -> tuple[Any, ...]:
    return (
        session.id,
        session.workspace_id,
        session.mode,
        session.status,
        session.current_step,
        _json(session.completed_steps),
        _json(session.skipped_optional_steps),
        _json(session.blocking_findings),
        _json(session.warning_findings),
        session.created_by,
        session.created_at,
        session.updated_at,
        session.completed_at,
        session.version,
        session.contract_version,
    )


def _session_from_row(row: sqlite3.Row) -> AlphaOnboardingSession:
    return AlphaOnboardingSession(
        id=row["id"],
        workspace_id=row["workspace_id"],
        mode=row["mode"],
        status=row["status"],
        current_step=row["current_step"],
        completed_steps=_tuple(row["completed_steps_json"]),
        skipped_optional_steps=_tuple(row["skipped_optional_steps_json"]),
        blocking_findings=_tuple(row["blocking_findings_json"]),
        warning_findings=_tuple(row["warning_findings_json"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        version=row["version"],
        contract_version=row["contract_version"],
    )
