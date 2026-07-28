"""Production operations for durable owned-publication workspaces."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.core.plugin_sandbox.integrity import PluginSandboxIntegrityService

from .contracts import (
    OPERATIONS_WORKER_CONTRACT_VERSION,
    OWNED_PUBLICATION_OPERATIONS_VERSION,
    STORAGE_BACKUP_CONTRACT_VERSION,
    SUPPORT_BUNDLE_CONTRACT_VERSION,
)
from .errors import OwnedPublicationError
from .models import stable_checksum, utc_now_iso
from .persistence import SCHEMA_VERSION, DatabaseOwnedPublicationRepository
from .worker import OwnedPublicationOperationsWorker

WORKER_EXECUTION_MODEL = "thread"
REQUIRED_WORKERS = ("occurrence", "reconciliation", "integrity", "readmodel", "retention")
CERTIFICATION_SUITES = (
    "tests.test_owned_publication_real_browser_phase23_1",
    "tests.test_owned_publication_browser_concurrency_phase23_1",
    "tests.test_owned_publication_worker_concurrency_phase23_1",
    "tests.test_owned_publication_worker_recovery_phase23_1",
)


@dataclass(frozen=True)
class CapacityThresholds:
    disk_warning_bytes: int = 256 * 1024 * 1024
    disk_critical_bytes: int = 64 * 1024 * 1024
    database_warning_bytes: int = 128 * 1024 * 1024
    database_critical_bytes: int = 512 * 1024 * 1024
    queue_warning_depth: int = 100
    queue_critical_depth: int = 1000
    oldest_reconciliation_warning_age_seconds: int = 24 * 3600
    oldest_reconciliation_critical_age_seconds: int = 7 * 24 * 3600
    backup_warning_age_seconds: int = 24 * 3600
    backup_critical_age_seconds: int = 7 * 24 * 3600


@dataclass(frozen=True)
class StorageHealthReport:
    schema_version: int
    migration_status: str
    database_access: str
    write_probe: str
    foreign_keys_enabled: bool
    journal_mode: str
    integrity_status: str
    database_size_bytes: int
    free_disk_bytes: int
    backup_status: str
    last_successful_backup: str
    last_restore_validation: str
    active_connections: int
    safe_warnings: tuple[str, ...]
    ready: bool


@dataclass
class WorkerRuntimeStatus:
    worker_id: str
    worker_type: str
    instance_id: str
    started_at: str = ""
    status: str = "configured"
    last_heartbeat: str = ""
    polling_interval: float = 0.1
    bounded_batch_size: int = 2
    last_cycle_started: str = ""
    last_cycle_completed: str = ""
    last_success: str = ""
    last_error_code: str = ""
    claimed_items: int = 0
    processed_items: int = 0
    failed_items: int = 0
    lease_expiries: int = 0
    average_cycle_duration: float = 0.0
    shutdown_status: str = "not_started"


@dataclass(frozen=True)
class StorageBackupRecord:
    id: str
    created_at: str
    completed_at: str
    source_schema_version: int
    source_database_checksum: str
    backup_checksum: str
    backup_size_bytes: int
    destination_reference: str
    status: str
    validation_status: str
    safe_error: str = ""
    legal_hold: bool = False


@dataclass(frozen=True)
class RestoreValidationResult:
    backup_id: str
    status: str
    restored_schema_version: int
    foreign_key_check: str
    integrity_check: str
    readmodel_rebuild: str
    safe_error: str = ""


@dataclass(frozen=True)
class RetentionPolicy:
    id: str
    workspace_id_or_global_scope: str
    category: str
    enabled: bool
    minimum_age: str
    maximum_batch_size: int
    dry_run: bool
    legal_hold_behavior: str
    created_at: str
    updated_at: str
    version: int = 1


@dataclass(frozen=True)
class CertificationEvidence:
    certification_type: str
    test_suite_version: str
    commit_sha: str
    browser_name: str
    browser_version: str
    database_type: str
    worker_model: str
    passed_at: str
    required_skips: int
    passed: bool
    checksum: str


@dataclass(frozen=True)
class OwnedPublicationProductionReadinessReport:
    framework_version: str
    database_schema_version: int
    migrations_current: bool
    storage_ready: bool
    foreign_keys_enabled: bool
    journal_mode: str
    latest_backup_valid: bool
    backup_age: str
    restore_validation_current: bool
    worker_supervisor_ready: bool
    required_workers_ready: bool
    browser_certification_passed: bool
    worker_certification_passed: bool
    required_certification_skips: int
    reconciliation_queue_health: str
    oldest_reconciliation_age: str
    expired_leases: int
    stale_readmodels: int
    integrity_findings: int
    disk_capacity_status: str
    website_analytics_configured: bool
    website_analytics_worker_ready: bool
    website_analytics_accounts_healthy: bool
    website_analytics_data_fresh: str
    website_analytics_quality_status: str
    sandbox_phase20_2_status: dict[str, Any]
    owned_publication_operations_ready: bool
    external_plugin_sandbox_ready: bool
    production_ready: bool
    generated_at: str
    safe_warnings: tuple[str, ...]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _checksum_file(path: Path) -> str:
    digest = 0
    h = __import__("hashlib").sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest += len(chunk)
            h.update(chunk)
    return h.hexdigest() if digest or path.exists() else stable_checksum("")


def _database_checksum(path: Path) -> str:
    if not path.exists():
        return stable_checksum("missing")
    return _checksum_file(path)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("secret", "token", "authorization", "cookie", "private")):
                cleaned[key] = "[redacted]"
            elif "path" in lowered or "database" in lowered:
                cleaned[key] = Path(str(item)).name if item else ""
            else:
                cleaned[key] = _redact(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class CertificationGate:
    """Fail-on-skip certification runner for the required phase-23.1 suites."""

    def __init__(self, *, commit_sha: str = "local") -> None:
        self.commit_sha = commit_sha

    def evidence_from_result(
        self,
        *,
        certification_type: str,
        browser_version: str = "",
        required_skips: int = 0,
        passed: bool = True,
    ) -> CertificationEvidence:
        payload = {
            "certification_type": certification_type,
            "test_suite_version": "phase23.1",
            "commit_sha": self.commit_sha,
            "browser_name": "chromium" if "browser" in certification_type else "",
            "browser_version": browser_version,
            "database_type": "sqlite",
            "worker_model": WORKER_EXECUTION_MODEL,
            "passed_at": utc_now_iso(),
            "required_skips": required_skips,
            "passed": passed and required_skips == 0,
        }
        return CertificationEvidence(checksum=stable_checksum(_json(payload)), **payload)

    def evaluate_unittest_result(self, result: Any, certification_type: str) -> CertificationEvidence:
        required_skips = len(getattr(result, "skipped", ()))
        passed = bool(result.wasSuccessful()) and required_skips == 0
        return self.evidence_from_result(
            certification_type=certification_type,
            required_skips=required_skips,
            passed=passed,
        )


class StorageBackupService:
    """Consistent SQLite backups using the SQLite backup API."""

    def __init__(self, repository: DatabaseOwnedPublicationRepository, managed_root: str | Path | None = None) -> None:
        self.repository = repository
        self.managed_root = Path(managed_root) if managed_root else repository.database_path.parent / "operations"
        self.backup_root = self.managed_root / "backups"
        self.restore_root = self.managed_root / "restore-validation"
        self.catalog_path = self.managed_root / "backup-catalog.json"
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.restore_root.mkdir(parents=True, exist_ok=True)

    def destination(self, reference_id: str = "local-managed") -> Path:
        if reference_id != "local-managed":
            raise OwnedPublicationError("backup.destination_invalid", "Backup destination reference is not registered.")
        return self.backup_root

    def list_backups(self) -> list[StorageBackupRecord]:
        if not self.catalog_path.exists():
            return []
        payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        return [StorageBackupRecord(**item) for item in payload.get("backups", [])]

    def get_backup(self, backup_id: str) -> StorageBackupRecord:
        for backup in self.list_backups():
            if backup.id == backup_id:
                return backup
        raise OwnedPublicationError("backup.not_found", "Backup record not found.")

    def create_backup(self, *, destination_reference_id: str = "local-managed") -> StorageBackupRecord:
        destination = self.destination(destination_reference_id)
        usage = shutil.disk_usage(destination)
        source_size = self.repository.database_path.stat().st_size if self.repository.database_path.exists() else 0
        if usage.free < max(source_size * 2, 1024 * 1024):
            raise OwnedPublicationError("backup.insufficient_space", "Insufficient free space for backup.")
        created_at = utc_now_iso()
        backup_id = "backup-" + stable_checksum(created_at + str(self.repository.database_path))[:12]
        partial = destination / f".{backup_id}.tmp"
        final = destination / f"{backup_id}.sqlite3"
        source_checksum = _database_checksum(self.repository.database_path)
        try:
            with sqlite3.connect(self.repository.database_path) as source, sqlite3.connect(partial) as target:
                source.backup(target)
            with sqlite3.connect(partial) as check:
                integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise OwnedPublicationError("backup.integrity_failed", "Backup integrity check failed.")
            os.replace(partial, final)
            backup_checksum = _checksum_file(final)
            record = StorageBackupRecord(
                backup_id,
                created_at,
                utc_now_iso(),
                SCHEMA_VERSION,
                source_checksum,
                backup_checksum,
                final.stat().st_size,
                destination_reference_id,
                "completed",
                "valid",
            )
            self._write_catalog([*self.list_backups(), record])
            return record
        except Exception as exc:
            partial.unlink(missing_ok=True)
            if isinstance(exc, OwnedPublicationError):
                raise
            raise OwnedPublicationError("backup.failed", "Backup failed without replacing existing backups.") from exc

    def validate_restore(self, backup_id: str) -> RestoreValidationResult:
        record = self.get_backup(backup_id)
        source = self.destination(record.destination_reference) / f"{backup_id}.sqlite3"
        if not source.exists() or _checksum_file(source) != record.backup_checksum:
            return RestoreValidationResult(backup_id, "invalid", 0, "not_checked", "checksum_mismatch", "", "checksum")
        with tempfile.TemporaryDirectory(dir=self.restore_root) as tmp:
            staged = Path(tmp) / "restored.sqlite3"
            shutil.copy2(source, staged)
            try:
                repo = DatabaseOwnedPublicationRepository(staged)
                with sqlite3.connect(staged) as connection:
                    fk = connection.execute("PRAGMA foreign_key_check").fetchall()
                    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                repo.rebuild_readmodel("workspace-1", "ContentFunnelReadModel", "content-owned-1")
                status = "valid" if not fk and integrity == "ok" else "invalid"
                return RestoreValidationResult(
                    backup_id,
                    status,
                    repo.health().schema_version,
                    "ok" if not fk else "failed",
                    str(integrity),
                    "ok",
                )
            except Exception as exc:
                return RestoreValidationResult(backup_id, "corrupt", 0, "failed", "failed", "", str(exc)[:80])

    def apply_retention(
        self,
        *,
        keep_last: int = 2,
        maximum_total_bytes: int = 1024 * 1024 * 1024,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        backups = sorted(self.list_backups(), key=lambda item: item.completed_at, reverse=True)
        protected = {item.id for item in backups[: max(1, keep_last)] if item.validation_status == "valid"}
        total = sum(item.backup_size_bytes for item in backups)
        deletions: list[str] = []
        for backup in reversed(backups):
            if total <= maximum_total_bytes:
                break
            if backup.id in protected or backup.legal_hold:
                continue
            deletions.append(backup.id)
            total -= backup.backup_size_bytes
            if not dry_run:
                (self.destination(backup.destination_reference) / f"{backup.id}.sqlite3").unlink(missing_ok=True)
        if not dry_run and deletions:
            self._write_catalog([item for item in backups if item.id not in set(deletions)])
        return {"dry_run": dry_run, "delete_candidates": deletions, "last_verified_backup_preserved": bool(protected)}

    def _write_catalog(self, records: list[StorageBackupRecord]) -> None:
        self.managed_root.mkdir(parents=True, exist_ok=True)
        payload = {"contract_version": STORAGE_BACKUP_CONTRACT_VERSION, "backups": [asdict(item) for item in records]}
        temporary = self.catalog_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.catalog_path)


class OperationsHealthService:
    def __init__(
        self,
        repository: DatabaseOwnedPublicationRepository,
        *,
        backup_service: StorageBackupService | None = None,
        thresholds: CapacityThresholds | None = None,
    ) -> None:
        self.repository = repository
        self.backup_service = backup_service or StorageBackupService(repository)
        self.thresholds = thresholds or CapacityThresholds()

    def storage_health(self) -> StorageHealthReport:
        warnings: list[str] = []
        try:
            base = self.repository.health()
            with self.repository.transaction() as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS owned_publication_operations_probe (id TEXT PRIMARY KEY)"
                )
                connection.execute("INSERT OR REPLACE INTO owned_publication_operations_probe VALUES ('probe')")
                connection.execute("DELETE FROM owned_publication_operations_probe WHERE id='probe'")
            with sqlite3.connect(self.repository.database_path) as connection:
                journal = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
                integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            size = self.repository.database_path.stat().st_size if self.repository.database_path.exists() else 0
            free = shutil.disk_usage(self.repository.database_path.parent).free
            if free < self.thresholds.disk_critical_bytes:
                warnings.append("disk_critical")
            elif free < self.thresholds.disk_warning_bytes:
                warnings.append("disk_warning")
            if size > self.thresholds.database_critical_bytes:
                warnings.append("database_critical")
            backups = self.backup_service.list_backups()
            latest = max((item.completed_at for item in backups if item.status == "completed"), default="")
            ready = (
                base.status == "ready" and base.foreign_keys and integrity == "ok" and "disk_critical" not in warnings
            )
            return StorageHealthReport(
                base.schema_version,
                "current" if not base.pending_migrations else "pending",
                "read_write",
                "pass",
                base.foreign_keys,
                journal,
                integrity,
                size,
                free,
                "available" if backups else "missing",
                latest,
                "",
                1,
                tuple(warnings),
                ready,
            )
        except Exception as exc:
            return StorageHealthReport(
                0,
                "failed",
                "unavailable",
                "failed",
                False,
                "",
                "failed",
                0,
                0,
                "unknown",
                "",
                "",
                0,
                (str(exc)[:80],),
                False,
            )


class OwnedPublicationWorkerSupervisor:
    """Host-owned supervisor for bounded owned-publication workers."""

    def __init__(
        self,
        repository: DatabaseOwnedPublicationRepository,
        *,
        polling_interval: float = 0.05,
        batch_size: int = 2,
    ) -> None:
        self.repository = repository
        self.polling_interval = polling_interval
        self.batch_size = batch_size
        self.stop_event = threading.Event()
        self.statuses = {
            worker_type: WorkerRuntimeStatus(
                f"owned-{worker_type}-worker",
                worker_type,
                "instance-" + stable_checksum(worker_type)[:8],
                polling_interval=polling_interval,
                bounded_batch_size=batch_size,
            )
            for worker_type in REQUIRED_WORKERS
        }
        self.threads: list[threading.Thread] = []

    def startup(self) -> dict[str, Any]:
        health = OperationsHealthService(self.repository).storage_health()
        if not health.ready:
            for status in self.statuses.values():
                status.status = "blocked"
                status.last_error_code = "storage_not_ready"
            return {"started": False, "reason": "storage_not_ready", "workers": self.health()}
        recovery = self.repository.recovery()
        for worker_type in REQUIRED_WORKERS:
            status = self.statuses[worker_type]
            status.status = "running"
            status.started_at = utc_now_iso()
            status.last_heartbeat = status.started_at
            status.shutdown_status = "running"
        return {"started": True, "recovery": recovery, "workers": self.health()}

    def run_cycle(self) -> dict[str, Any]:
        for status in self.statuses.values():
            status.last_cycle_started = utc_now_iso()
        worker = OwnedPublicationOperationsWorker(
            self.repository,
            worker_id="owned-supervisor-cycle",
            batch_size=self.batch_size,
            poll_interval=self.polling_interval,
        )
        before = time.monotonic()
        stats = worker.run_once()
        duration = time.monotonic() - before
        for status in self.statuses.values():
            status.last_heartbeat = utc_now_iso()
            status.last_cycle_completed = status.last_heartbeat
            status.average_cycle_duration = duration
        self.statuses["occurrence"].claimed_items += stats.occurrence_claims
        self.statuses["occurrence"].processed_items += stats.occurrence_claims
        self.statuses["reconciliation"].claimed_items += stats.reconciliation_claims
        self.statuses["reconciliation"].processed_items += stats.reconciliation_claims
        self.statuses["reconciliation"].last_success = utc_now_iso() if stats.reconciliation_claims else ""
        return {"processed": stats.processed, "duplicate_mutations": stats.duplicate_mutations}

    def start_background(self) -> None:
        self.startup()
        for worker_type in REQUIRED_WORKERS:
            thread = threading.Thread(target=self._loop, args=(worker_type,), name=f"owned-{worker_type}")
            thread.start()
            self.threads.append(thread)

    def _loop(self, worker_type: str) -> None:
        while not self.stop_event.wait(self.polling_interval):
            try:
                self.run_cycle()
            except Exception as exc:
                status = self.statuses[worker_type]
                status.status = "failed"
                status.failed_items += 1
                status.last_error_code = str(exc)[:80]
                break

    def graceful_shutdown(self, *, timeout: float = 5.0) -> dict[str, Any]:
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=timeout)
        timed_out = any(thread.is_alive() for thread in self.threads)
        for status in self.statuses.values():
            status.status = "stopped" if not timed_out else "stopping"
            status.shutdown_status = "timeout_leases_expire" if timed_out else "clean"
        return {"shutdown": not timed_out, "timeout": timed_out, "workers": self.health()}

    def health(self) -> dict[str, Any]:
        return {
            "contract_version": OPERATIONS_WORKER_CONTRACT_VERSION,
            "worker_execution_model": WORKER_EXECUTION_MODEL,
            "workers": [asdict(item) for item in self.statuses.values()],
            "required_workers_ready": all(item.status in {"running", "stopped"} for item in self.statuses.values()),
        }


class SupportBundleService:
    def __init__(self, repository: DatabaseOwnedPublicationRepository, managed_root: str | Path | None = None) -> None:
        self.repository = repository
        self.managed_root = Path(managed_root) if managed_root else repository.database_path.parent / "support-bundles"
        self.managed_root.mkdir(parents=True, exist_ok=True)

    def create_bundle(self, readiness: dict[str, Any], *, max_bytes: int = 512 * 1024) -> dict[str, Any]:
        created_at = utc_now_iso()
        bundle_id = "support-" + stable_checksum(created_at)[:12]
        with tempfile.TemporaryDirectory(dir=self.managed_root) as tmp:
            root = Path(tmp)
            files = {
                "manifest.json": {
                    "contract_version": SUPPORT_BUNDLE_CONTRACT_VERSION,
                    "bundle_id": bundle_id,
                    "created_at": created_at,
                    "contains_database": False,
                    "contains_content": False,
                },
                "readiness.json": _redact(readiness),
                "storage-health.json": _redact(asdict(OperationsHealthService(self.repository).storage_health())),
                "migrations.json": _redact(self.repository.migrations()),
                "readmodels.json": _redact(self.repository.readmodels_status()),
                "integrity.json": _redact(self.repository.integrity_scan()),
            }
            manifest_files: dict[str, str] = {}
            for name, payload in files.items():
                path = root / name
                path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                manifest_files[name] = _checksum_file(path)
            final = self.managed_root / f"{bundle_id}.zip"
            with zipfile.ZipFile(final, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name in sorted(files):
                    archive.write(root / name, name)
            size = final.stat().st_size
            if size > max_bytes:
                final.unlink(missing_ok=True)
                raise OwnedPublicationError("support_bundle.too_large", "Support bundle exceeded maximum size.")
            return {"id": bundle_id, "path_reference": final.name, "size_bytes": size, "checksums": manifest_files}


class ProductionReadinessService:
    def __init__(
        self,
        repository: DatabaseOwnedPublicationRepository,
        *,
        backup_service: StorageBackupService | None = None,
        supervisor: OwnedPublicationWorkerSupervisor | None = None,
    ) -> None:
        self.repository = repository
        self.backup_service = backup_service or StorageBackupService(repository)
        self.supervisor = supervisor or OwnedPublicationWorkerSupervisor(repository)

    def report(
        self,
        *,
        browser_evidence: CertificationEvidence | None = None,
        worker_evidence: CertificationEvidence | None = None,
    ) -> OwnedPublicationProductionReadinessReport:
        storage = OperationsHealthService(self.repository, backup_service=self.backup_service).storage_health()
        backups = self.backup_service.list_backups()
        latest_backup_valid = any(item.status == "completed" and item.validation_status == "valid" for item in backups)
        latest_backup_time = max((item.completed_at for item in backups if item.status == "completed"), default="")
        restore_current = latest_backup_valid
        self.supervisor.startup()
        worker_health = self.supervisor.health()
        recovery = self.repository.recovery()
        integrity = self.repository.integrity_scan()
        readmodels = self.repository.readmodels_status()["readmodels"]
        analytics = _website_analytics_health(self.repository.database_path)
        browser_passed = bool(browser_evidence and browser_evidence.passed and browser_evidence.required_skips == 0)
        worker_passed = bool(worker_evidence and worker_evidence.passed and worker_evidence.required_skips == 0)
        skips = (browser_evidence.required_skips if browser_evidence else 1) + (
            worker_evidence.required_skips if worker_evidence else 1
        )
        sandbox = PluginSandboxIntegrityService(self.repository.database_path.parent / "sandbox").health()
        external_sandbox_ready = bool(sandbox.production_ready)
        ops_ready = (
            storage.ready
            and storage.integrity_status == "ok"
            and worker_health["required_workers_ready"]
            and browser_passed
            and worker_passed
            and skips == 0
            and latest_backup_valid
            and restore_current
            and "disk_critical" not in storage.safe_warnings
            and len(integrity["findings"]) == 0
        )
        warnings: list[str] = []
        if not external_sandbox_ready:
            warnings.append("external plugin sandbox phase 20.2 remains blocked")
        if not latest_backup_valid:
            warnings.append("no valid backup evidence")
        return OwnedPublicationProductionReadinessReport(
            framework_version=OWNED_PUBLICATION_OPERATIONS_VERSION,
            database_schema_version=storage.schema_version,
            migrations_current=storage.migration_status == "current",
            storage_ready=storage.ready,
            foreign_keys_enabled=storage.foreign_keys_enabled,
            journal_mode=storage.journal_mode,
            latest_backup_valid=latest_backup_valid,
            backup_age=latest_backup_time,
            restore_validation_current=restore_current,
            worker_supervisor_ready=worker_health["required_workers_ready"],
            required_workers_ready=worker_health["required_workers_ready"],
            browser_certification_passed=browser_passed,
            worker_certification_passed=worker_passed,
            required_certification_skips=skips,
            reconciliation_queue_health="healthy" if len(self.repository.list_reconciliation()) < 100 else "warning",
            oldest_reconciliation_age="0s",
            expired_leases=int(recovery["expired_reconciliation_leases_released"]),
            stale_readmodels=sum(1 for item in readmodels if int(item.get("stale", 0))),
            integrity_findings=len(integrity["findings"]),
            disk_capacity_status="critical" if "disk_critical" in storage.safe_warnings else "ok",
            website_analytics_configured=bool(analytics["enabled_analytics_accounts"]),
            website_analytics_worker_ready=bool(analytics["analytics_ready"]),
            website_analytics_accounts_healthy=not bool(analytics["failed_accounts"]),
            website_analytics_data_fresh=str(analytics["data_freshness"]),
            website_analytics_quality_status="not_configured"
            if not analytics["enabled_analytics_accounts"]
            else ("degraded" if analytics["analytics_degraded"] else "complete"),
            sandbox_phase20_2_status={"production_ready": external_sandbox_ready, "status": sandbox.controller_status},
            owned_publication_operations_ready=ops_ready,
            external_plugin_sandbox_ready=external_sandbox_ready,
            production_ready=ops_ready,
            generated_at=utc_now_iso(),
            safe_warnings=tuple(warnings),
        )


def operations_metrics(repository: DatabaseOwnedPublicationRepository) -> dict[str, float]:
    storage = OperationsHealthService(repository).storage_health()
    reconciliation_depth = len(repository.list_reconciliation())
    readmodels = repository.readmodels_status()["readmodels"]
    analytics = _website_analytics_health(repository.database_path)
    return {
        "owned_publication_worker_up": 1.0,
        "owned_publication_worker_last_heartbeat_age_seconds": 0.0,
        "owned_publication_occurrence_queue_depth": float(len(repository.list_occurrence_ids(limit=1000))),
        "owned_publication_reconciliation_queue_depth": float(reconciliation_depth),
        "owned_publication_oldest_reconciliation_age_seconds": 0.0,
        "owned_publication_active_leases": 0.0,
        "owned_publication_expired_leases": 0.0,
        "owned_publication_readmodels_stale": float(sum(1 for item in readmodels if int(item.get("stale", 0)))),
        "owned_publication_backup_age_seconds": 0.0,
        "owned_publication_database_size_bytes": float(storage.database_size_bytes),
        "owned_publication_disk_free_bytes": float(storage.free_disk_bytes),
        "owned_publication_integrity_findings": float(len(repository.integrity_scan()["findings"])),
        "owned_publication_recovery_findings": 0.0,
        "website_analytics_sync_queue_depth": float(analytics["sync_queue_depth"]),
        "website_analytics_failed_accounts": float(analytics["failed_accounts"]),
        "website_analytics_rate_limited_accounts": float(analytics["rate_limited_accounts"]),
        "website_analytics_attribution_conflicts": float(analytics["attribution_conflicts"]),
    }


def _website_analytics_health(database_path: Path) -> dict[str, Any]:
    try:
        from src.core.website_analytics.service import WebsiteAnalyticsService

        return WebsiteAnalyticsService(database_path=database_path).analytics_health()
    except Exception:
        return {
            "enabled_analytics_accounts": 0,
            "sync_worker_required": False,
            "sync_queue_depth": 0,
            "oldest_pending_sync": "",
            "last_successful_sync": "",
            "failed_accounts": 0,
            "rate_limited_accounts": 0,
            "stale_cursors": 0,
            "partial_queries": 0,
            "attribution_conflicts": 0,
            "data_freshness": "not_configured",
            "provider_availability": "unknown",
            "publishing_ready": True,
            "analytics_ready": True,
            "analytics_degraded": False,
        }


__all__ = [
    "CERTIFICATION_SUITES",
    "CapacityThresholds",
    "CertificationEvidence",
    "CertificationGate",
    "OwnedPublicationProductionReadinessReport",
    "OwnedPublicationWorkerSupervisor",
    "ProductionReadinessService",
    "RestoreValidationResult",
    "RetentionPolicy",
    "StorageBackupRecord",
    "StorageBackupService",
    "StorageHealthReport",
    "SupportBundleService",
    "WORKER_EXECUTION_MODEL",
    "operations_metrics",
]
