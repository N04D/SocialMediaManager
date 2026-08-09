from __future__ import annotations

import calendar
import hashlib
from collections.abc import Callable
from dataclasses import asdict, fields
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import channel_store
from channel_storage import locked_json_store
from publication_execution import Clock
from publication_planning import PublicationPlanningService
from src.core.content import PublicationPlanStatus, PublicationTargetStatus
from src.core.scheduling import (
    CAMPAIGN_CONTRACT_VERSION,
    EXECUTION_CALENDAR_CONTRACT_VERSION,
    PUBLICATION_SCHEDULE_CONTRACT_VERSION,
    RECURRENCE_RULE_CONTRACT_VERSION,
    SCHEDULE_AUTHORIZATION_CONTRACT_VERSION,
    SCHEDULE_OCCURRENCE_CONTRACT_VERSION,
    SCHEDULE_POLICY_CONTRACT_VERSION,
    SCHEDULING_FRAMEWORK_VERSION,
    CalendarEntry,
    Campaign,
    CampaignCoordinationPolicy,
    CampaignMember,
    CampaignStatus,
    PublicationSchedule,
    PublicationScheduleStatus,
    RecurrenceFrequency,
    RecurrenceRule,
    ScheduleAuthorization,
    ScheduleExclusion,
    ScheduleOccurrence,
    ScheduleOccurrenceStatus,
    SchedulePolicy,
    ScheduleTargetTemplate,
    ScheduleTemplateSnapshot,
)

T = TypeVar("T")

TERMINAL_TARGET_STATUSES = {
    PublicationTargetStatus.PUBLISHED.value,
    PublicationTargetStatus.FAILED.value,
    PublicationTargetStatus.CANCELLED.value,
}
ACTIVE_OVERLAP_STATUSES = {
    PublicationTargetStatus.QUEUED.value,
    PublicationTargetStatus.RUNNING.value,
    PublicationTargetStatus.UNCERTAIN.value,
    "reconciling",
    "blocked",
}
SAFE_PLAN_TEMPLATE_STATUSES = {
    PublicationPlanStatus.READY.value,
    PublicationPlanStatus.SCHEDULED.value,
    PublicationPlanStatus.QUEUED.value,
    PublicationPlanStatus.PARTIALLY_QUEUED.value,
}


def schedules_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_schedules.json"


def recurrence_rules_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_recurrence_rules.json"


def schedule_policies_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_schedule_policies.json"


def schedule_snapshots_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_schedule_template_snapshots.json"


def schedule_occurrences_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_schedule_occurrences.json"


def schedule_exclusions_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_schedule_exclusions.json"


def schedule_authorizations_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_schedule_authorizations.json"


def campaigns_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_campaigns.json"


def campaign_members_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_campaign_members.json"


def campaign_policies_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_campaign_policies.json"


def scheduling_events_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_scheduling_events.json"


def scheduling_audit_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_scheduling_audit.json"


def scheduling_state_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_scheduling_state.json"


def scheduling_integrity_path() -> Path:
    return channel_store.STUDIO_DATA_DIR / "publication_scheduling_integrity_last_scan.json"


def _list_store(path: Path):
    return locked_json_store(path, default_factory=list, expect_type=list, lock_dir=channel_store.LOCKS_DIR)


def _dict_store(path: Path):
    return locked_json_store(path, default_factory=dict, expect_type=dict, lock_dir=channel_store.LOCKS_DIR)


def _fields(cls: type) -> set[str]:
    return {field.name for field in fields(cls)}


def _load_records(path: Path, cls: type[T]) -> list[T]:  # noqa: UP047
    with _list_store(path) as store:
        payload = store.read()
    allowed = _fields(cls)
    records: list[T] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            records.append(cls(**{key: value for key, value in item.items() if key in allowed}))
        except TypeError:
            continue
    return records


def _mutate_records(path: Path, cls: type[T], mutator: Callable[[list[T]], tuple[bool, Any]]) -> Any:  # noqa: UP047
    with _list_store(path) as store:
        payload = store.read()
        allowed = _fields(cls)
        records: list[T] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                records.append(cls(**{key: value for key, value in item.items() if key in allowed}))
            except TypeError:
                continue
        changed, result = mutator(records)
        if changed:
            store.write([asdict(record) for record in records])
        return result


def _canonical_json(data: Any) -> str:
    import json

    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _checksum(data: Any) -> str:
    return hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_local_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _now_iso() -> str:
    return channel_store.now_iso()


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    blocked = {
        "storage_reference",
        "storage_path",
        "local_path",
        "materialized_path",
        "browser_session_id",
        "provider_secret",
        "confirmation_token",
        "token",
    }
    return {key: value for key, value in dict(metadata or {}).items() if key not in blocked}


class SchedulingValidationError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class JsonRepository:
    cls: type

    @property
    def path(self) -> Path:
        raise NotImplementedError

    def create(self, record):
        def mutate(records):
            if any(item.id == record.id for item in records):
                raise SchedulingValidationError("scheduling.record_exists", "Record already exists.")
            records.append(record)
            return True, record

        return _mutate_records(self.path, self.cls, mutate)

    def save(self, record):
        def mutate(records):
            for index, existing in enumerate(records):
                if existing.id == record.id:
                    records[index] = record
                    return True, record
            records.append(record)
            return True, record

        return _mutate_records(self.path, self.cls, mutate)

    def get(self, record_id: str):
        return next((record for record in self.list_all() if record.id == record_id), None)

    def list_all(self, *, workspace_id: str = ""):
        records = _load_records(self.path, self.cls)
        if workspace_id:
            records = [record for record in records if getattr(record, "workspace_id", "") == workspace_id]
        return records


class PublicationScheduleRepository(JsonRepository):
    cls = PublicationSchedule

    @property
    def path(self) -> Path:
        return schedules_path()

    def list_all(self, *, workspace_id: str = "") -> list[PublicationSchedule]:
        records = super().list_all(workspace_id=workspace_id)
        return sorted(records, key=lambda item: (item.created_at, item.id))


class RecurrenceRuleRepository(JsonRepository):
    cls = RecurrenceRule

    @property
    def path(self) -> Path:
        return recurrence_rules_path()


class SchedulePolicyRepository(JsonRepository):
    cls = SchedulePolicy

    @property
    def path(self) -> Path:
        return schedule_policies_path()


class ScheduleTemplateSnapshotRepository(JsonRepository):
    cls = ScheduleTemplateSnapshot

    @property
    def path(self) -> Path:
        return schedule_snapshots_path()


class ScheduleOccurrenceRepository(JsonRepository):
    cls = ScheduleOccurrence

    @property
    def path(self) -> Path:
        return schedule_occurrences_path()

    def create(self, record: ScheduleOccurrence) -> ScheduleOccurrence:
        def mutate(records: list[ScheduleOccurrence]):
            current = next((item for item in records if item.occurrence_key == record.occurrence_key), None)
            if current is not None:
                return False, current
            records.append(record)
            return True, record

        return _mutate_records(self.path, self.cls, mutate)

    def remove_created_occurrence(
        self,
        *,
        occurrence_id: str,
        mutation_id: str,
        expected_state_fingerprint: str,
    ) -> ScheduleOccurrence:
        def mutate(records: list[ScheduleOccurrence]):
            for index, occurrence in enumerate(records):
                if occurrence.id != occurrence_id:
                    continue
                metadata = dict(occurrence.metadata or {})
                if metadata.get("created_by") != "generic-runtime":
                    raise SchedulingValidationError(
                        "calendar.compensation_not_runtime_created",
                        "Only runtime-created occurrences can be compensated.",
                    )
                if metadata.get("created_by_mutation_id") != mutation_id:
                    raise SchedulingValidationError(
                        "calendar.compensation_ownership_mismatch",
                        "Occurrence was not created by the requested mutation.",
                    )
                if metadata.get("created_state_fingerprint") != expected_state_fingerprint:
                    raise SchedulingValidationError(
                        "calendar.compensation_receipt_mismatch",
                        "Mutation receipt does not match occurrence provenance.",
                    )
                if _occurrence_state_fingerprint(occurrence) != expected_state_fingerprint:
                    raise SchedulingValidationError(
                        "calendar.compensation_resource_changed",
                        "Occurrence changed after creation and cannot be safely compensated.",
                    )
                removed = records.pop(index)
                return True, removed
            raise SchedulingValidationError(
                "calendar.compensation_resource_missing",
                "Occurrence is already absent or does not exist.",
            )

        return _mutate_records(self.path, self.cls, mutate)

    def find_by_key(self, key: str) -> ScheduleOccurrence | None:
        return next((item for item in self.list_all() if item.occurrence_key == key), None)

    def list_by_schedule(self, schedule_id: str) -> list[ScheduleOccurrence]:
        records = [item for item in self.list_all() if item.schedule_id == schedule_id]
        return sorted(records, key=lambda item: (item.scheduled_at_utc, item.sequence_number, item.id))


def _occurrence_state_fingerprint(occurrence: ScheduleOccurrence) -> str:
    payload = asdict(occurrence)
    metadata = dict(payload.get("metadata") or {})
    metadata.pop("created_state_fingerprint", None)
    payload["metadata"] = metadata
    return _checksum(payload)


class ScheduleExclusionRepository(JsonRepository):
    cls = ScheduleExclusion

    @property
    def path(self) -> Path:
        return schedule_exclusions_path()

    def list_by_schedule(self, schedule_id: str) -> list[ScheduleExclusion]:
        return [item for item in self.list_all() if item.schedule_id == schedule_id]


class ScheduleAuthorizationRepository(JsonRepository):
    cls = ScheduleAuthorization

    @property
    def path(self) -> Path:
        return schedule_authorizations_path()

    def consume_once(self, authorization_id: str, *, occurrence_id: str, now: datetime) -> ScheduleAuthorization:
        def mutate(records: list[ScheduleAuthorization]):
            for record in records:
                if record.id != authorization_id:
                    continue
                consumed = set(record.metadata.get("consumed_occurrence_ids") or [])
                if occurrence_id in consumed:
                    return False, record
                if record.status != "active":
                    raise SchedulingValidationError("schedule.authorization_inactive", "Authorization is not active.")
                if record.maximum_occurrences and record.consumed_occurrences >= record.maximum_occurrences:
                    record.status = "exhausted"
                    raise SchedulingValidationError(
                        "schedule.authorization_exhausted", "Authorization has no remaining occurrences."
                    )
                valid_until = _parse_datetime(record.valid_until)
                if valid_until is not None and valid_until <= now:
                    record.status = "expired"
                    raise SchedulingValidationError("schedule.authorization_expired", "Authorization expired.")
                consumed.add(occurrence_id)
                record.consumed_occurrences += 1
                if record.maximum_occurrences and record.consumed_occurrences >= record.maximum_occurrences:
                    record.status = "exhausted"
                record.metadata = {**record.metadata, "consumed_occurrence_ids": sorted(consumed)}
                return True, record
            raise SchedulingValidationError("schedule.authorization_missing", "Authorization is missing.")

        return _mutate_records(self.path, self.cls, mutate)


class CampaignRepository(JsonRepository):
    cls = Campaign

    @property
    def path(self) -> Path:
        return campaigns_path()


class CampaignMemberRepository(JsonRepository):
    cls = CampaignMember

    @property
    def path(self) -> Path:
        return campaign_members_path()

    def add(self, member: CampaignMember) -> CampaignMember:
        def mutate(records: list[CampaignMember]):
            if any(
                item.campaign_id == member.campaign_id
                and item.member_type == member.member_type
                and item.member_id == member.member_id
                and item.active
                for item in records
            ):
                raise SchedulingValidationError("campaign.member_duplicate", "Campaign member already exists.")
            records.append(member)
            return True, member

        return _mutate_records(self.path, self.cls, mutate)

    def list_by_campaign(self, campaign_id: str) -> list[CampaignMember]:
        records = [item for item in self.list_all() if item.campaign_id == campaign_id and item.active]
        return sorted(records, key=lambda item: (item.position, item.id))


class CampaignPolicyRepository(JsonRepository):
    cls = CampaignCoordinationPolicy

    @property
    def path(self) -> Path:
        return campaign_policies_path()


class RecurrenceEngine:
    def normalize_rule(self, rule: RecurrenceRule) -> RecurrenceRule:
        if rule.frequency not in {item.value for item in RecurrenceFrequency}:
            raise SchedulingValidationError("recurrence.unsupported_frequency", "Unsupported recurrence frequency.")
        if rule.interval <= 0:
            raise SchedulingValidationError("recurrence.invalid_interval", "Interval must be greater than zero.")
        if rule.frequency == RecurrenceFrequency.WEEKLY.value and not rule.by_weekday:
            raise SchedulingValidationError("recurrence.weekday_required", "Weekly recurrence needs weekdays.")
        invalid_days = [day for day in rule.by_month_day if day < 1 or day > 31]
        if invalid_days:
            raise SchedulingValidationError("recurrence.invalid_month_day", "Month days must be between 1 and 31.")
        normalized = {
            "frequency": rule.frequency,
            "interval": int(rule.interval),
            "by_weekday": sorted({int(day) for day in rule.by_weekday}),
            "by_month_day": sorted({int(day) for day in rule.by_month_day}),
            "count": max(int(rule.count or 0), 0),
            "until_local": rule.until_local,
            "until_utc": rule.until_utc,
            "week_start": int(rule.week_start or 0),
            "contract_version": RECURRENCE_RULE_CONTRACT_VERSION,
        }
        rule.normalized_rule = normalized
        rule.checksum = _checksum(normalized)
        return rule

    def preview(
        self,
        *,
        starts_at_local: str,
        timezone: str,
        rule: RecurrenceRule,
        policy: SchedulePolicy,
        maximum: int = 20,
    ) -> list[dict[str, Any]]:
        normalized = self.normalize_rule(rule)
        zone = self._zone(timezone)
        start = _parse_local_datetime(starts_at_local)
        maximum = max(0, min(int(maximum or 20), 100))
        if normalized.frequency == RecurrenceFrequency.MONTHLY.value:
            return self._preview_monthly(
                start=start, timezone=timezone, zone=zone, rule=normalized, policy=policy, maximum=maximum
            )
        occurrences: list[dict[str, Any]] = []
        sequence = 0
        candidates_checked = 0
        cursor = start
        until_utc = _parse_datetime(normalized.until_utc) if normalized.until_utc else None
        if normalized.until_local and until_utc is None:
            until_resolution = self.resolve_local(normalized.until_local, timezone, policy)
            until_utc = until_resolution.get("utc")
        while len(occurrences) < maximum and candidates_checked < 500:
            candidates_checked += 1
            if self._matches(start, cursor, normalized):
                resolution = self.resolve_naive(cursor, zone, policy)
                if resolution["valid"] and (until_utc is None or resolution["utc"] <= until_utc):
                    sequence += 1
                    if normalized.count and sequence > normalized.count:
                        break
                    occurrences.append(
                        {
                            "sequence": sequence,
                            "scheduled_at_local": cursor.isoformat(timespec="seconds"),
                            "timezone": timezone,
                            "scheduled_at_utc": _iso_utc(resolution["utc"]),
                            "dst_status": resolution["dst_status"],
                            "validity": "valid",
                            "exclusion": False,
                            "warnings": list(resolution["warnings"]),
                        }
                    )
                elif resolution["dst_status"] == "nonexistent" and policy.dst_nonexistent_policy == "require_review":
                    occurrences.append(
                        {
                            "sequence": sequence + 1,
                            "scheduled_at_local": cursor.isoformat(timespec="seconds"),
                            "timezone": timezone,
                            "scheduled_at_utc": "",
                            "dst_status": "nonexistent",
                            "validity": "requires_review",
                            "exclusion": False,
                            "warnings": ["dst_nonexistent_requires_review"],
                        }
                    )
                    break
                if until_utc is not None and resolution.get("utc") and resolution["utc"] > until_utc:
                    break
            cursor = self._next_cursor(start, cursor, normalized)
        return occurrences

    def _preview_monthly(
        self,
        *,
        start: datetime,
        timezone: str,
        zone: ZoneInfo,
        rule: RecurrenceRule,
        policy: SchedulePolicy,
        maximum: int,
    ) -> list[dict[str, Any]]:
        occurrences: list[dict[str, Any]] = []
        sequence = 0
        months_checked = 0
        until_utc = _parse_datetime(rule.until_utc) if rule.until_utc else None
        month_index = 0
        days = sorted(set(rule.by_month_day or [start.day]))
        while len(occurrences) < maximum and months_checked < 240:
            absolute_month = (start.month - 1) + month_index
            year = start.year + absolute_month // 12
            month = absolute_month % 12 + 1
            if month_index % rule.interval != 0:
                month_index += 1
                months_checked += 1
                continue
            last_day = calendar.monthrange(year, month)[1]
            candidate_days = []
            for day in days:
                if day <= last_day:
                    candidate_days.append(day)
                elif policy.monthly_invalid_date_policy == "last_valid_day":
                    candidate_days.append(last_day)
            for day in sorted(set(candidate_days)):
                candidate = datetime.combine(date(year, month, day), time(start.hour, start.minute, start.second))
                if candidate < start:
                    continue
                resolution = self.resolve_naive(candidate, zone, policy)
                if not resolution["valid"]:
                    if resolution["dst_status"] == "nonexistent" and policy.dst_nonexistent_policy == "require_review":
                        occurrences.append(
                            {
                                "sequence": sequence + 1,
                                "scheduled_at_local": candidate.isoformat(timespec="seconds"),
                                "timezone": timezone,
                                "scheduled_at_utc": "",
                                "dst_status": "nonexistent",
                                "validity": "requires_review",
                                "exclusion": False,
                                "warnings": ["dst_nonexistent_requires_review"],
                            }
                        )
                        return occurrences
                    continue
                if until_utc is not None and resolution["utc"] > until_utc:
                    return occurrences
                sequence += 1
                if rule.count and sequence > rule.count:
                    return occurrences
                occurrences.append(
                    {
                        "sequence": sequence,
                        "scheduled_at_local": candidate.isoformat(timespec="seconds"),
                        "timezone": timezone,
                        "scheduled_at_utc": _iso_utc(resolution["utc"]),
                        "dst_status": resolution["dst_status"],
                        "validity": "valid",
                        "exclusion": False,
                        "warnings": list(resolution["warnings"]),
                    }
                )
                if len(occurrences) >= maximum:
                    return occurrences
            month_index += 1
            months_checked += 1
        return occurrences

    def resolve_local(self, value: str, timezone: str, policy: SchedulePolicy) -> dict[str, Any]:
        return self.resolve_naive(_parse_local_datetime(value), self._zone(timezone), policy)

    def resolve_naive(self, naive: datetime, zone: ZoneInfo, policy: SchedulePolicy) -> dict[str, Any]:
        aware0 = naive.replace(tzinfo=zone, fold=0)
        aware1 = naive.replace(tzinfo=zone, fold=1)
        round0 = aware0.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
        round1 = aware1.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
        match0 = round0 == naive
        match1 = round1 == naive
        warnings: list[str] = []
        if match0 and match1 and aware0.utcoffset() != aware1.utcoffset():
            if policy.dst_ambiguous_policy == "second_occurrence":
                chosen = aware1
            elif policy.dst_ambiguous_policy == "first_occurrence":
                chosen = aware0
            else:
                return {
                    "valid": False,
                    "utc": None,
                    "dst_status": "ambiguous",
                    "warnings": ["dst_ambiguous_requires_review"],
                }
            return {
                "valid": True,
                "utc": chosen.astimezone(UTC),
                "dst_status": "ambiguous",
                "warnings": warnings,
            }
        if not match0 and not match1:
            if policy.dst_nonexistent_policy == "skip":
                return {"valid": False, "utc": None, "dst_status": "nonexistent", "warnings": ["dst_nonexistent_skip"]}
            if policy.dst_nonexistent_policy == "shift_forward":
                shifted = naive
                for _ in range(180):
                    shifted += timedelta(minutes=1)
                    shifted_result = self.resolve_naive(shifted, zone, SchedulePolicy(id="", workspace_id=""))
                    if shifted_result["valid"]:
                        shifted_result["dst_status"] = "nonexistent_shifted"
                        shifted_result["warnings"] = ["dst_nonexistent_shifted_forward"]
                        return shifted_result
            return {
                "valid": False,
                "utc": None,
                "dst_status": "nonexistent",
                "warnings": ["dst_nonexistent_requires_review"],
            }
        return {"valid": True, "utc": aware0.astimezone(UTC), "dst_status": "normal", "warnings": warnings}

    def _zone(self, timezone: str) -> ZoneInfo:
        if not timezone:
            raise SchedulingValidationError("schedule.timezone_required", "Timezone is required.")
        try:
            return ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise SchedulingValidationError("schedule.invalid_timezone", "Invalid IANA timezone.") from exc

    def _matches(self, start: datetime, candidate: datetime, rule: RecurrenceRule) -> bool:
        if candidate < start:
            return False
        if rule.frequency == RecurrenceFrequency.ONCE.value:
            return candidate == start
        if rule.frequency == RecurrenceFrequency.DAILY.value:
            return (candidate.date() - start.date()).days % rule.interval == 0
        if rule.frequency == RecurrenceFrequency.WEEKLY.value:
            weeks = (candidate.date() - start.date()).days // 7
            return weeks % rule.interval == 0 and candidate.weekday() in set(rule.by_weekday)
        if rule.frequency == RecurrenceFrequency.MONTHLY.value:
            months = (candidate.year - start.year) * 12 + candidate.month - start.month
            return months % rule.interval == 0 and candidate.day in set(rule.by_month_day or [start.day])
        return False

    def _next_cursor(self, start: datetime, cursor: datetime, rule: RecurrenceRule) -> datetime:
        if rule.frequency in {RecurrenceFrequency.ONCE.value, RecurrenceFrequency.DAILY.value}:
            return cursor + timedelta(days=1)
        if rule.frequency == RecurrenceFrequency.WEEKLY.value:
            return cursor + timedelta(days=1)
        if rule.frequency == RecurrenceFrequency.MONTHLY.value:
            day = cursor.day + 1
            last_day = calendar.monthrange(cursor.year, cursor.month)[1]
            if day <= last_day:
                return cursor.replace(day=day)
            month = cursor.month + 1
            year = cursor.year
            if month > 12:
                month = 1
                year += 1
            return datetime.combine(date(year, month, 1), time(cursor.hour, cursor.minute, cursor.second))
        return start + timedelta(days=1)


class ScheduleMaterializationService:
    def __init__(
        self,
        *,
        app_runtime,
        config,
        planning_service: PublicationPlanningService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.app_runtime = app_runtime
        self.config = config
        self.planning_service = planning_service or app_runtime.publication_planning_service(config)
        self.execution_service = app_runtime.publication_execution_service(config)
        self.schedule_repository = PublicationScheduleRepository()
        self.recurrence_repository = RecurrenceRuleRepository()
        self.policy_repository = SchedulePolicyRepository()
        self.snapshot_repository = ScheduleTemplateSnapshotRepository()
        self.occurrence_repository = ScheduleOccurrenceRepository()
        self.exclusion_repository = ScheduleExclusionRepository()
        self.authorization_repository = ScheduleAuthorizationRepository()
        self.clock = clock or Clock()
        self.recurrence_engine = RecurrenceEngine()

    def preview_recurrence(
        self,
        *,
        starts_at_local: str,
        timezone: str,
        recurrence: dict[str, Any],
        policy: dict[str, Any] | None = None,
        maximum: int = 20,
    ) -> list[dict[str, Any]]:
        rule = self._rule_from_payload(recurrence)
        schedule_policy = SchedulePolicy(id="", workspace_id="", **dict(policy or {}))
        return self.recurrence_engine.preview(
            starts_at_local=starts_at_local,
            timezone=timezone,
            rule=rule,
            policy=schedule_policy,
            maximum=maximum,
        )

    def create_template_snapshot(
        self, source_publication_plan_id: str, *, workspace_id: str, created_by: str = ""
    ) -> ScheduleTemplateSnapshot:
        plan = self.planning_service._get_plan(source_publication_plan_id, workspace_id=workspace_id)
        validation = self.planning_service.validate_plan(plan.id, workspace_id=workspace_id)
        if not validation["valid"]:
            raise SchedulingValidationError("schedule.template_invalid", "Source plan is not valid.", validation)
        prepared = self.planning_service.prepare_plan(plan.id, workspace_id=workspace_id, actor=created_by)
        if dict(prepared.metadata or {}).get("revision_policy") == "follow_current_revision":
            raise SchedulingValidationError(
                "schedule.follow_current_not_allowed", "Recurring schedules require pinned revisions."
            )
        item = self.planning_service.content_service.get_content(plan.content_item_id, workspace_id=workspace_id)
        revision = self.planning_service.content_service.revision_repository.get(plan.source_revision_id)
        if revision is None:
            raise SchedulingValidationError("schedule.revision_missing", "Source revision is missing.")
        templates: list[dict[str, Any]] = []
        media_relation_ids: list[str] = []
        content_versions: dict[str, str] = {}
        media_versions: dict[str, str] = {}
        for target in self.planning_service.target_repository.list_by_plan(plan.id):
            snapshot = dict((target.metadata or {}).get("snapshot") or {})
            templates.append(
                asdict(
                    ScheduleTargetTemplate(
                        channel_plugin_id=target.channel_plugin_id,
                        channel_account_id=target.channel_account_id,
                        capability=target.capability,
                        channel_variant_id=target.channel_variant_id,
                        media_relation_ids=list(target.media_relation_ids),
                        position=target.position,
                        offset_seconds=int((target.metadata or {}).get("schedule_offset_seconds") or 0),
                        metadata=_safe_metadata(
                            {
                                "source_target_id": target.id,
                                "snapshot_checksum": target.snapshot_checksum,
                            }
                        ),
                    )
                )
            )
            media_relation_ids.extend(snapshot.get("media_relation_ids") or target.media_relation_ids or [])
            key = f"{target.channel_plugin_id}:{target.capability}"
            content_versions[key] = str(snapshot.get("content_requirement_version") or "")
            media_versions[key] = str(snapshot.get("media_requirement_version") or "")
        if not templates:
            raise SchedulingValidationError("schedule.target_template_missing", "Schedule needs target templates.")
        payload = {
            "contract_version": "1.0",
            "source_publication_plan_id": plan.id,
            "source_plan_checksum": prepared.snapshot_checksum,
            "content_item_id": item.id,
            "source_revision_id": revision.id,
            "revision_checksum": revision.checksum,
            "target_templates": templates,
            "media_relation_ids": sorted(set(media_relation_ids)),
            "content_requirement_versions": content_versions,
            "media_requirement_versions": media_versions,
            "timezone": plan.timezone,
        }
        snapshot = ScheduleTemplateSnapshot(
            id=f"schedule_template_{uuid4().hex}",
            workspace_id=workspace_id,
            source_publication_plan_id=plan.id,
            source_plan_checksum=prepared.snapshot_checksum,
            content_item_id=item.id,
            source_revision_id=revision.id,
            revision_checksum=revision.checksum,
            target_templates=templates,
            media_relation_ids=sorted(set(media_relation_ids)),
            content_requirement_versions=content_versions,
            media_requirement_versions=media_versions,
            timezone=plan.timezone,
            created_at=_now_iso(),
            created_by=created_by,
            checksum=_checksum(payload),
        )
        saved = self.snapshot_repository.create(snapshot)
        self._audit("schedule.template_snapshot.create", workspace_id, "schedule_template", saved.id, created_by)
        return saved

    def create_schedule(
        self,
        *,
        workspace_id: str,
        name: str,
        starts_at_local: str,
        timezone: str,
        recurrence: dict[str, Any],
        source_publication_plan_id: str,
        created_by: str = "",
        policy: dict[str, Any] | None = None,
        campaign_id: str = "",
        description: str = "",
    ) -> PublicationSchedule:
        snapshot = self.create_template_snapshot(
            source_publication_plan_id, workspace_id=workspace_id, created_by=created_by
        )
        policy_record = SchedulePolicy(
            id=f"schedule_policy_{uuid4().hex}",
            workspace_id=workspace_id,
            created_at=_now_iso(),
            updated_at=_now_iso(),
            **dict(policy or {}),
        )
        policy_record = self.policy_repository.create(policy_record)
        rule = self.recurrence_engine.normalize_rule(self._rule_from_payload(recurrence))
        rule = self.recurrence_repository.create(rule)
        resolved = self.recurrence_engine.resolve_local(starts_at_local, timezone, policy_record)
        if not resolved["valid"]:
            raise SchedulingValidationError(
                "schedule.start_time_requires_review", "Schedule start time needs explicit DST resolution.", resolved
            )
        schedule = PublicationSchedule(
            id=f"publication_schedule_{uuid4().hex}",
            workspace_id=workspace_id,
            name=name.strip() or snapshot.source_publication_plan_id,
            description=description,
            timezone=timezone,
            starts_at_local=starts_at_local,
            starts_at_utc=_iso_utc(resolved["utc"]),
            recurrence_rule_id=rule.id,
            schedule_policy_id=policy_record.id,
            template_snapshot_id=snapshot.id,
            campaign_id=campaign_id,
            created_at=_now_iso(),
            updated_at=_now_iso(),
            created_by=created_by,
            updated_by=created_by,
        )
        saved = self.schedule_repository.create(schedule)
        self._event("publication.schedule.created", workspace_id, "publication_schedule", saved.id, created_by)
        self._audit("schedule.create", workspace_id, "publication_schedule", saved.id, created_by)
        return saved

    def validate_schedule(self, schedule_id: str, *, workspace_id: str) -> dict[str, Any]:
        schedule = self._get_schedule(schedule_id, workspace_id=workspace_id)
        blockers: list[str] = []
        try:
            rule = self._get_rule(schedule.recurrence_rule_id)
            policy = self._get_policy(schedule.schedule_policy_id, schedule.workspace_id)
            snapshot = self._get_snapshot(schedule.template_snapshot_id, schedule.workspace_id)
            preview = self.recurrence_engine.preview(
                starts_at_local=schedule.starts_at_local,
                timezone=schedule.timezone,
                rule=rule,
                policy=policy,
                maximum=1,
            )
            if not preview:
                blockers.append("recurrence_empty")
            if not snapshot.target_templates:
                blockers.append("target_templates_missing")
        except SchedulingValidationError as exc:
            blockers.append(exc.code)
        schedule.status = (
            PublicationScheduleStatus.READY.value if not blockers else PublicationScheduleStatus.BLOCKED.value
        )
        schedule.updated_at = _now_iso()
        self.schedule_repository.save(schedule)
        self._event("publication.schedule.validated", workspace_id, "publication_schedule", schedule.id, "")
        return {"valid": not blockers, "schedule_id": schedule.id, "blockers": blockers}

    def activate_schedule(self, schedule_id: str, *, workspace_id: str, actor: str = "") -> PublicationSchedule:
        result = self.validate_schedule(schedule_id, workspace_id=workspace_id)
        schedule = self._get_schedule(schedule_id, workspace_id=workspace_id)
        if not result["valid"]:
            raise SchedulingValidationError("schedule.invalid", "Schedule cannot be activated.", result)
        schedule.status = PublicationScheduleStatus.ACTIVE.value
        schedule.updated_at = _now_iso()
        saved = self.schedule_repository.save(schedule)
        self._event("publication.schedule.activated", workspace_id, "publication_schedule", saved.id, actor)
        self._audit("schedule.activate", workspace_id, "publication_schedule", saved.id, actor)
        return saved

    def pause_schedule(
        self, schedule_id: str, *, workspace_id: str, actor: str = "", reason: str = ""
    ) -> PublicationSchedule:
        schedule = self._get_schedule(schedule_id, workspace_id=workspace_id)
        schedule.status = PublicationScheduleStatus.PAUSED.value
        schedule.paused_at = _now_iso()
        schedule.paused_by = actor
        schedule.pause_reason = reason
        schedule.updated_at = _now_iso()
        saved = self.schedule_repository.save(schedule)
        self._event("publication.schedule.paused", workspace_id, "publication_schedule", saved.id, actor)
        self._audit("schedule.pause", workspace_id, "publication_schedule", saved.id, actor, reason=reason)
        return saved

    def resume_schedule(self, schedule_id: str, *, workspace_id: str, actor: str = "") -> PublicationSchedule:
        schedule = self._get_schedule(schedule_id, workspace_id=workspace_id)
        policy = self._get_policy(schedule.schedule_policy_id, schedule.workspace_id)
        missed = self.detect_missed_occurrences(schedule.id, workspace_id=workspace_id)
        if missed and policy.missed_occurrence_policy == "require_review":
            schedule.status = PublicationScheduleStatus.BLOCKED.value
            schedule.updated_at = _now_iso()
            self.schedule_repository.save(schedule)
            raise SchedulingValidationError("schedule.missed_review_required", "Missed occurrences require review.")
        schedule.status = PublicationScheduleStatus.ACTIVE.value
        schedule.paused_at = ""
        schedule.pause_reason = ""
        schedule.updated_at = _now_iso()
        saved = self.schedule_repository.save(schedule)
        self._event("publication.schedule.resumed", workspace_id, "publication_schedule", saved.id, actor)
        self._audit("schedule.resume", workspace_id, "publication_schedule", saved.id, actor)
        return saved

    def cancel_schedule(
        self, schedule_id: str, *, workspace_id: str, actor: str = "", reason: str = ""
    ) -> PublicationSchedule:
        schedule = self._get_schedule(schedule_id, workspace_id=workspace_id)
        schedule.status = PublicationScheduleStatus.CANCELLED.value
        schedule.cancelled_at = _now_iso()
        schedule.cancelled_by = actor
        schedule.cancellation_reason = reason
        schedule.updated_at = _now_iso()
        for occurrence in self.occurrence_repository.list_by_schedule(schedule.id):
            if occurrence.status in {
                ScheduleOccurrenceStatus.PROJECTED.value,
                ScheduleOccurrenceStatus.DUE.value,
                ScheduleOccurrenceStatus.READY.value,
                ScheduleOccurrenceStatus.SCHEDULED.value,
                ScheduleOccurrenceStatus.BLOCKED.value,
            }:
                occurrence.status = ScheduleOccurrenceStatus.CANCELLED.value
                self.occurrence_repository.save(occurrence)
                if occurrence.publication_plan_id:
                    try:
                        self.planning_service.cancel_plan(
                            occurrence.publication_plan_id, workspace_id=workspace_id, actor=actor
                        )
                    except Exception:
                        pass
        saved = self.schedule_repository.save(schedule)
        self._event("publication.schedule.cancelled", workspace_id, "publication_schedule", saved.id, actor)
        self._audit("schedule.cancel", workspace_id, "publication_schedule", saved.id, actor, reason=reason)
        return saved

    def authorize_schedule(
        self,
        schedule_id: str,
        *,
        workspace_id: str,
        actor: str,
        valid_until: str,
        maximum_occurrences: int,
    ) -> ScheduleAuthorization:
        schedule = self._get_schedule(schedule_id, workspace_id=workspace_id)
        snapshot = self._get_snapshot(schedule.template_snapshot_id, workspace_id)
        if maximum_occurrences <= 0 or not valid_until:
            raise SchedulingValidationError(
                "schedule.authorization_unbounded", "Bounded authorization needs a limit and expiry."
            )
        target_templates = [ScheduleTargetTemplate(**template) for template in snapshot.target_templates]
        authorization = ScheduleAuthorization(
            id=f"schedule_authorization_{uuid4().hex}",
            workspace_id=workspace_id,
            schedule_id=schedule.id,
            template_snapshot_checksum=snapshot.checksum,
            authorized_by=actor,
            authorized_at=_now_iso(),
            valid_from=self.clock.now_iso(),
            valid_until=valid_until,
            maximum_occurrences=maximum_occurrences,
            allowed_channel_account_ids=sorted({item.channel_account_id for item in target_templates}),
            allowed_capabilities=sorted({item.capability for item in target_templates}),
            status="active",
        )
        saved = self.authorization_repository.create(authorization)
        schedule.authorization_id = saved.id
        schedule.updated_at = _now_iso()
        self.schedule_repository.save(schedule)
        self._event(
            "publication.schedule.authorization_created", workspace_id, "publication_schedule", schedule.id, actor
        )
        self._audit("schedule.authorization.create", workspace_id, "publication_schedule", schedule.id, actor)
        return saved

    def revoke_authorization(
        self, schedule_id: str, *, workspace_id: str, actor: str = "", reason: str = ""
    ) -> ScheduleAuthorization:
        schedule = self._get_schedule(schedule_id, workspace_id=workspace_id)
        authorization = self.authorization_repository.get(schedule.authorization_id)
        if authorization is None:
            raise SchedulingValidationError("schedule.authorization_missing", "Authorization is missing.")
        authorization.status = "revoked"
        authorization.revoked_at = _now_iso()
        authorization.revoked_by = actor
        authorization.revoke_reason = reason
        saved = self.authorization_repository.save(authorization)
        self._event(
            "publication.schedule.authorization_revoked", workspace_id, "publication_schedule", schedule.id, actor
        )
        self._audit(
            "schedule.authorization.revoke", workspace_id, "publication_schedule", schedule.id, actor, reason=reason
        )
        return saved

    def materialize_due_horizon(
        self,
        *,
        workspace_id: str = "",
        batch_size: int = 50,
        actor: str = "system",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        batch_size = max(1, min(batch_size, 50))
        materialized: list[dict[str, str]] = []
        blockers: list[dict[str, str]] = []
        for schedule in self.schedule_repository.list_all(workspace_id=workspace_id):
            if len(materialized) >= batch_size:
                break
            if schedule.status != PublicationScheduleStatus.ACTIVE.value:
                continue
            try:
                result = self.materialize_schedule(
                    schedule.id,
                    workspace_id=schedule.workspace_id,
                    batch_size=batch_size - len(materialized),
                    actor=actor,
                    dry_run=dry_run,
                )
                materialized.extend(result["materialized"])
                blockers.extend(result["blockers"])
            except Exception as exc:
                blockers.append(
                    {"schedule_id": schedule.id, "code": getattr(exc, "code", "schedule.materialize_failed")}
                )
        with _dict_store(scheduling_state_path()) as store:
            state = store.read()
            state["last_materialization_run"] = self.clock.now_iso()
            state["last_materialization_dry_run"] = bool(dry_run)
            state["last_materialized_count"] = len(materialized)
            store.write(state)
        return {"materialized": materialized, "blockers": blockers, "dry_run": dry_run}

    def materialize_schedule(
        self,
        schedule_id: str,
        *,
        workspace_id: str,
        batch_size: int = 50,
        actor: str = "system",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        schedule = self._get_schedule(schedule_id, workspace_id=workspace_id)
        policy = self._get_policy(schedule.schedule_policy_id, workspace_id)
        rule = self._get_rule(schedule.recurrence_rule_id)
        horizon = self.clock.now() + timedelta(days=max(policy.materialization_horizon_days, 0))
        preview = self.recurrence_engine.preview(
            starts_at_local=schedule.starts_at_local,
            timezone=schedule.timezone,
            rule=rule,
            policy=policy,
            maximum=min(policy.maximum_materialized_occurrences, 100),
        )
        materialized: list[dict[str, str]] = []
        blockers: list[dict[str, str]] = []
        existing = self.occurrence_repository.list_by_schedule(schedule.id)
        existing_keys = {item.occurrence_key for item in existing}
        pending_count = sum(
            item.status
            not in {
                ScheduleOccurrenceStatus.COMPLETED.value,
                ScheduleOccurrenceStatus.CANCELLED.value,
                ScheduleOccurrenceStatus.SKIPPED.value,
            }
            for item in existing
        )
        for projected in preview:
            if len(materialized) >= min(batch_size, 50):
                break
            scheduled_utc = _parse_datetime(projected.get("scheduled_at_utc", ""))
            if scheduled_utc is None or scheduled_utc > horizon:
                continue
            key = self.occurrence_key(
                schedule_id=schedule.id,
                generation_version=schedule.generation_version,
                scheduled_at_utc=_iso_utc(scheduled_utc),
                template_snapshot_checksum=self._get_snapshot(schedule.template_snapshot_id, workspace_id).checksum,
            )
            if key in existing_keys:
                continue
            if pending_count >= policy.maximum_pending_occurrences:
                blockers.append({"schedule_id": schedule.id, "code": "schedule.maximum_pending_occurrences"})
                break
            if self._is_excluded(schedule.id, projected["scheduled_at_local"], schedule.timezone):
                if not dry_run:
                    occurrence = self._build_occurrence(
                        schedule, projected, key, ScheduleOccurrenceStatus.SKIPPED.value
                    )
                    occurrence.skipped_at = _now_iso()
                    occurrence.skip_reason = "excluded"
                    self.occurrence_repository.create(occurrence)
                    self._event(
                        "publication.schedule.occurrence_skipped",
                        schedule.workspace_id,
                        "schedule_occurrence",
                        occurrence.id,
                        actor,
                    )
                materialized.append({"schedule_id": schedule.id, "occurrence_key": key, "status": "skipped"})
                continue
            if not self._overlap_allowed(schedule, policy):
                if not dry_run:
                    occurrence = self._build_occurrence(
                        schedule, projected, key, ScheduleOccurrenceStatus.BLOCKED.value
                    )
                    occurrence.blocked_reason = "overlap_blocked"
                    self.occurrence_repository.create(occurrence)
                    self._event(
                        "publication.schedule.occurrence_blocked",
                        schedule.workspace_id,
                        "schedule_occurrence",
                        occurrence.id,
                        actor,
                    )
                blockers.append({"schedule_id": schedule.id, "code": "schedule.overlap_blocked"})
                continue
            if dry_run:
                materialized.append({"schedule_id": schedule.id, "occurrence_key": key, "status": "projected"})
            else:
                occurrence = self.materialize_occurrence_from_projection(schedule, projected, key, actor=actor)
                materialized.append(
                    {"schedule_id": schedule.id, "occurrence_id": occurrence.id, "status": occurrence.status}
                )
                pending_count += 1
        if not dry_run and materialized:
            schedule.materialized_until = max(
                (item["scheduled_at_utc"] for item in preview if item.get("scheduled_at_utc")), default=""
            )
            schedule.next_occurrence_at = self._next_unmaterialized(schedule, preview)
            schedule.updated_at = _now_iso()
            self.schedule_repository.save(schedule)
        return {"schedule_id": schedule.id, "materialized": materialized, "blockers": blockers, "dry_run": dry_run}

    def materialize_occurrence_from_projection(
        self, schedule: PublicationSchedule, projected: dict[str, Any], key: str, *, actor: str
    ) -> ScheduleOccurrence:
        occurrence = self._build_occurrence(schedule, projected, key, ScheduleOccurrenceStatus.MATERIALIZING.value)
        occurrence = self.occurrence_repository.create(occurrence)
        if occurrence.publication_plan_id:
            return occurrence
        policy = self._get_policy(schedule.schedule_policy_id, schedule.workspace_id)
        snapshot = self._get_snapshot(schedule.template_snapshot_id, schedule.workspace_id)
        if policy.authorization_policy == "bounded_schedule_authorization":
            self._check_and_consume_authorization(schedule, occurrence, snapshot)
        plan = self.planning_service.create_plan(
            workspace_id=schedule.workspace_id,
            content_item_id=snapshot.content_item_id,
            name=f"{schedule.name} #{occurrence.sequence_number}",
            created_by=actor,
            planned_start_at=occurrence.scheduled_at_utc,
            timezone=schedule.timezone,
            follow_current_revision=False,
        )
        plan.source_revision_id = snapshot.source_revision_id
        plan.snapshot_checksum = snapshot.source_plan_checksum
        plan.metadata = {
            **dict(plan.metadata or {}),
            "schedule_id": schedule.id,
            "schedule_occurrence_id": occurrence.id,
            "schedule_generation_version": schedule.generation_version,
            "template_snapshot_id": snapshot.id,
            "template_snapshot_checksum": snapshot.checksum,
            "campaign_id": schedule.campaign_id,
        }
        self.planning_service.plan_repository.save(plan)
        target_ids: list[str] = []
        for template_payload in snapshot.target_templates:
            template = ScheduleTargetTemplate(**template_payload)
            scheduled_utc = _parse_datetime(occurrence.scheduled_at_utc) or self.clock.now()
            target_time = scheduled_utc + timedelta(seconds=template.offset_seconds)
            metadata = {
                "schedule_id": schedule.id,
                "schedule_occurrence_id": occurrence.id,
                "template_snapshot_id": snapshot.id,
                "template_snapshot_checksum": snapshot.checksum,
                "schedule_offset_seconds": template.offset_seconds,
                "authorization_mode": policy.authorization_policy,
            }
            if policy.authorization_policy == "bounded_schedule_authorization":
                metadata["schedule_authorization_id"] = schedule.authorization_id
            target = self.planning_service.add_target(
                plan.id,
                workspace_id=schedule.workspace_id,
                channel_plugin_id=template.channel_plugin_id,
                channel_account_id=template.channel_account_id,
                capability=template.capability,
                channel_variant_id=template.channel_variant_id,
                media_relation_ids=template.media_relation_ids,
                scheduled_at=_iso_utc(target_time),
                timezone=schedule.timezone,
                position=template.position,
                metadata=metadata,
            )
            target.source_revision_id = snapshot.source_revision_id
            target.status = (
                PublicationTargetStatus.READY.value
                if policy.authorization_policy == "bounded_schedule_authorization"
                else PublicationTargetStatus.AWAITING_CONFIRMATION.value
            )
            target.metadata = {
                **dict(target.metadata or {}),
                "confirmation_required": policy.authorization_policy != "bounded_schedule_authorization",
            }
            self.planning_service.target_repository.save(target)
            target_ids.append(target.id)
        self.planning_service.validate_plan(plan.id, workspace_id=schedule.workspace_id)
        occurrence.publication_plan_id = plan.id
        occurrence.publication_target_ids = target_ids
        occurrence.status = ScheduleOccurrenceStatus.SCHEDULED.value
        occurrence.materialized_at = _now_iso()
        self.occurrence_repository.save(occurrence)
        self._event(
            "publication.schedule.occurrence_materialized",
            schedule.workspace_id,
            "schedule_occurrence",
            occurrence.id,
            actor,
        )
        self._audit(
            "schedule.occurrence.materialize",
            schedule.workspace_id,
            "schedule_occurrence",
            occurrence.id,
            actor,
            snapshot_checksum=snapshot.checksum,
        )
        return occurrence

    def reconcile_occurrence(self, occurrence_id: str, *, workspace_id: str, dry_run: bool = True) -> dict[str, Any]:
        occurrence = self._get_occurrence(occurrence_id, workspace_id=workspace_id)
        plan = (
            self.planning_service.plan_repository.get(occurrence.publication_plan_id)
            if occurrence.publication_plan_id
            else None
        )
        derived = occurrence.status
        blockers: list[str] = []
        if (
            occurrence.status
            in {
                ScheduleOccurrenceStatus.MATERIALIZED.value,
                ScheduleOccurrenceStatus.READY.value,
                ScheduleOccurrenceStatus.SCHEDULED.value,
            }
            and plan is None
        ):
            blockers.append("occurrence.plan_missing")
        if plan is not None:
            targets = self.planning_service.target_repository.list_by_plan(plan.id)
            statuses = {target.status for target in targets}
            if PublicationTargetStatus.UNCERTAIN.value in statuses:
                derived = ScheduleOccurrenceStatus.UNCERTAIN.value
            elif statuses and statuses <= {PublicationTargetStatus.PUBLISHED.value}:
                derived = ScheduleOccurrenceStatus.COMPLETED.value
            elif PublicationTargetStatus.RUNNING.value in statuses:
                derived = ScheduleOccurrenceStatus.RUNNING.value
            elif PublicationTargetStatus.QUEUED.value in statuses:
                derived = ScheduleOccurrenceStatus.QUEUED.value
            elif PublicationTargetStatus.FAILED.value in statuses:
                derived = ScheduleOccurrenceStatus.FAILED.value
        changed = derived != occurrence.status
        if changed and not dry_run:
            occurrence.status = derived
            if derived == ScheduleOccurrenceStatus.COMPLETED.value:
                occurrence.completed_at = _now_iso()
            self.occurrence_repository.save(occurrence)
            if derived == ScheduleOccurrenceStatus.UNCERTAIN.value:
                schedule = self.schedule_repository.get(occurrence.schedule_id)
                if schedule is not None:
                    policy = self._get_policy(schedule.schedule_policy_id, schedule.workspace_id)
                    if policy.uncertain_policy == "pause_schedule":
                        self.pause_schedule(
                            schedule.id,
                            workspace_id=schedule.workspace_id,
                            actor="system",
                            reason="uncertain_occurrence",
                        )
        return {
            "occurrence_id": occurrence.id,
            "classification": "status_lag" if changed else "consistent",
            "current_status": occurrence.status,
            "derived_status": derived,
            "blockers": blockers,
            "dry_run": dry_run,
        }

    def detect_missed_occurrences(self, schedule_id: str, *, workspace_id: str) -> list[dict[str, Any]]:
        schedule = self._get_schedule(schedule_id, workspace_id=workspace_id)
        policy = self._get_policy(schedule.schedule_policy_id, workspace_id)
        now = self.clock.now()
        preview = self.recurrence_engine.preview(
            starts_at_local=schedule.starts_at_local,
            timezone=schedule.timezone,
            rule=self._get_rule(schedule.recurrence_rule_id),
            policy=policy,
            maximum=min(policy.maximum_materialized_occurrences, 100),
        )
        existing_keys = {item.occurrence_key for item in self.occurrence_repository.list_by_schedule(schedule.id)}
        missed: list[dict[str, Any]] = []
        for projected in preview:
            scheduled = _parse_datetime(projected.get("scheduled_at_utc", ""))
            if scheduled and scheduled < now:
                key = self.occurrence_key(
                    schedule_id=schedule.id,
                    generation_version=schedule.generation_version,
                    scheduled_at_utc=_iso_utc(scheduled),
                    template_snapshot_checksum=self._get_snapshot(schedule.template_snapshot_id, workspace_id).checksum,
                )
                if key not in existing_keys:
                    missed.append(projected)
        return missed

    def health_check(self) -> dict[str, Any]:
        schedules = self.schedule_repository.list_all()
        occurrences = self.occurrence_repository.list_all()
        with _dict_store(scheduling_state_path()) as store:
            state = store.read()
        return {
            "status": "ready",
            "scheduling_framework_version": SCHEDULING_FRAMEWORK_VERSION,
            "repositories": {
                "schedules": True,
                "recurrence": True,
                "policies": True,
                "occurrences": True,
                "authorizations": True,
            },
            "recurrence_engine": True,
            "timezone_database": True,
            "clock": True,
            "planning_service": self.planning_service.health_check().get("status", "unknown"),
            "execution_service": self.execution_service.health_check().get("status", "unknown"),
            "last_materialization_run": state.get("last_materialization_run", ""),
            "last_reconciliation": state.get("last_reconciliation", ""),
            "active_schedules": sum(item.status == PublicationScheduleStatus.ACTIVE.value for item in schedules),
            "blocked_schedules": sum(item.status == PublicationScheduleStatus.BLOCKED.value for item in schedules),
            "uncertain_occurrences": sum(
                item.status == ScheduleOccurrenceStatus.UNCERTAIN.value for item in occurrences
            ),
            "contract_versions": {
                "schedule": PUBLICATION_SCHEDULE_CONTRACT_VERSION,
                "recurrence": RECURRENCE_RULE_CONTRACT_VERSION,
                "occurrence": SCHEDULE_OCCURRENCE_CONTRACT_VERSION,
                "policy": SCHEDULE_POLICY_CONTRACT_VERSION,
                "authorization": SCHEDULE_AUTHORIZATION_CONTRACT_VERSION,
            },
        }

    def scan_integrity(self, *, workspace_id: str = "") -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        schedules = self.schedule_repository.list_all(workspace_id=workspace_id)
        occurrences = self.occurrence_repository.list_all(workspace_id=workspace_id)
        keys: dict[str, int] = {}
        for schedule in schedules:
            if not self.recurrence_repository.get(schedule.recurrence_rule_id):
                issues.append({"code": "schedule.recurrence_missing", "schedule_id": schedule.id})
            if not self.policy_repository.get(schedule.schedule_policy_id):
                issues.append({"code": "schedule.policy_missing", "schedule_id": schedule.id})
            if not self.snapshot_repository.get(schedule.template_snapshot_id):
                issues.append({"code": "schedule.template_missing", "schedule_id": schedule.id})
        for occurrence in occurrences:
            keys[occurrence.occurrence_key] = keys.get(occurrence.occurrence_key, 0) + 1
            if not self.schedule_repository.get(occurrence.schedule_id):
                issues.append({"code": "occurrence.schedule_missing", "occurrence_id": occurrence.id})
            if (
                occurrence.status
                in {
                    ScheduleOccurrenceStatus.MATERIALIZED.value,
                    ScheduleOccurrenceStatus.READY.value,
                    ScheduleOccurrenceStatus.SCHEDULED.value,
                }
                and not occurrence.publication_plan_id
            ):
                issues.append({"code": "occurrence.plan_missing", "occurrence_id": occurrence.id})
        for key, count in keys.items():
            if count > 1:
                issues.append({"code": "occurrence.duplicate_key", "occurrence_key": key, "count": count})
        with _dict_store(scheduling_integrity_path()) as store:
            store.write({"checked_at": _now_iso(), "issues": issues})
        return issues

    def occurrence_key(
        self, *, schedule_id: str, generation_version: int, scheduled_at_utc: str, template_snapshot_checksum: str
    ) -> str:
        return _checksum(
            {
                "schedule_id": schedule_id,
                "generation_version": generation_version,
                "scheduled_at_utc": scheduled_at_utc,
                "template_snapshot_checksum": template_snapshot_checksum,
            }
        )

    def _rule_from_payload(self, payload: dict[str, Any]) -> RecurrenceRule:
        return RecurrenceRule(
            id=str(payload.get("id") or f"recurrence_rule_{uuid4().hex}"),
            frequency=str(payload.get("frequency") or "once"),
            interval=int(payload.get("interval") or 1),
            by_weekday=[int(item) for item in payload.get("by_weekday") or []],
            by_month_day=[int(item) for item in payload.get("by_month_day") or []],
            count=int(payload.get("count") or 0),
            until_local=str(payload.get("until_local") or ""),
            until_utc=str(payload.get("until_utc") or ""),
            week_start=int(payload.get("week_start") or 0),
        )

    def _build_occurrence(
        self, schedule: PublicationSchedule, projected: dict[str, Any], key: str, status: str
    ) -> ScheduleOccurrence:
        return ScheduleOccurrence(
            id=f"schedule_occurrence_{uuid4().hex}",
            workspace_id=schedule.workspace_id,
            schedule_id=schedule.id,
            campaign_id=schedule.campaign_id,
            occurrence_key=key,
            generation_version=schedule.generation_version,
            sequence_number=int(projected["sequence"]),
            scheduled_at_local=projected["scheduled_at_local"],
            timezone=schedule.timezone,
            scheduled_at_utc=projected["scheduled_at_utc"],
            status=status,
            source_template_snapshot_id=schedule.template_snapshot_id,
            template_snapshot_checksum=self._get_snapshot(
                schedule.template_snapshot_id, schedule.workspace_id
            ).checksum,
            authorization_id=schedule.authorization_id,
        )

    def _check_and_consume_authorization(
        self, schedule: PublicationSchedule, occurrence: ScheduleOccurrence, snapshot: ScheduleTemplateSnapshot
    ) -> None:
        authorization = self.authorization_repository.get(schedule.authorization_id)
        if authorization is None:
            raise SchedulingValidationError("schedule.authorization_missing", "Bounded authorization is missing.")
        if authorization.template_snapshot_checksum != snapshot.checksum:
            authorization.status = "invalidated"
            self.authorization_repository.save(authorization)
            raise SchedulingValidationError("schedule.authorization_checksum_mismatch", "Authorization is stale.")
        self.authorization_repository.consume_once(authorization.id, occurrence_id=occurrence.id, now=self.clock.now())

    def _is_excluded(self, schedule_id: str, local_value: str, timezone: str) -> bool:
        local = _parse_local_datetime(local_value)
        local_day = local.date()
        for exclusion in self.exclusion_repository.list_by_schedule(schedule_id):
            start = _parse_local_datetime(exclusion.starts_at_local)
            end = _parse_local_datetime(exclusion.ends_at_local) if exclusion.ends_at_local else start
            if exclusion.exclusion_type == "single_occurrence" and start == local:
                return True
            if exclusion.exclusion_type == "date" and start.date() == local_day:
                return True
            if exclusion.exclusion_type in {"date_range", "blackout_window"} and start <= local <= end:
                return True
        return False

    def _overlap_allowed(self, schedule: PublicationSchedule, policy: SchedulePolicy) -> bool:
        if policy.overlap_policy == "allow_independent":
            return True
        for occurrence in self.occurrence_repository.list_by_schedule(schedule.id):
            if occurrence.status in {
                ScheduleOccurrenceStatus.QUEUED.value,
                ScheduleOccurrenceStatus.RUNNING.value,
                ScheduleOccurrenceStatus.UNCERTAIN.value,
                ScheduleOccurrenceStatus.BLOCKED.value,
            }:
                return False
            if occurrence.publication_plan_id:
                targets = self.planning_service.target_repository.list_by_plan(occurrence.publication_plan_id)
                if any(target.status in ACTIVE_OVERLAP_STATUSES for target in targets):
                    return False
        return True

    def _next_unmaterialized(self, schedule: PublicationSchedule, preview: list[dict[str, Any]]) -> str:
        existing_keys = {item.occurrence_key for item in self.occurrence_repository.list_by_schedule(schedule.id)}
        snapshot = self._get_snapshot(schedule.template_snapshot_id, schedule.workspace_id)
        for projected in preview:
            key = self.occurrence_key(
                schedule_id=schedule.id,
                generation_version=schedule.generation_version,
                scheduled_at_utc=projected.get("scheduled_at_utc", ""),
                template_snapshot_checksum=snapshot.checksum,
            )
            if key not in existing_keys:
                return projected.get("scheduled_at_utc", "")
        return ""

    def _get_schedule(self, schedule_id: str, *, workspace_id: str) -> PublicationSchedule:
        schedule = self.schedule_repository.get(schedule_id)
        if schedule is None or schedule.workspace_id != workspace_id:
            raise SchedulingValidationError("schedule.not_found", "Schedule was not found.")
        return schedule

    def _get_occurrence(self, occurrence_id: str, *, workspace_id: str) -> ScheduleOccurrence:
        occurrence = self.occurrence_repository.get(occurrence_id)
        if occurrence is None or occurrence.workspace_id != workspace_id:
            raise SchedulingValidationError("occurrence.not_found", "Occurrence was not found.")
        return occurrence

    def _get_rule(self, rule_id: str) -> RecurrenceRule:
        rule = self.recurrence_repository.get(rule_id)
        if rule is None:
            raise SchedulingValidationError("recurrence.not_found", "Recurrence rule was not found.")
        return rule

    def _get_policy(self, policy_id: str, workspace_id: str) -> SchedulePolicy:
        policy = self.policy_repository.get(policy_id)
        if policy is None or policy.workspace_id != workspace_id:
            raise SchedulingValidationError("schedule.policy_not_found", "Schedule policy was not found.")
        return policy

    def _get_snapshot(self, snapshot_id: str, workspace_id: str) -> ScheduleTemplateSnapshot:
        snapshot = self.snapshot_repository.get(snapshot_id)
        if snapshot is None or snapshot.workspace_id != workspace_id:
            raise SchedulingValidationError("schedule.template_not_found", "Schedule template snapshot was not found.")
        return snapshot

    def _event(self, event_type: str, workspace_id: str, target_type: str, target_id: str, actor: str = "") -> None:
        with _list_store(scheduling_events_path()) as store:
            events = store.read()
            events.append(
                {
                    "id": f"scheduling_event_{uuid4().hex}",
                    "type": event_type,
                    "workspace_id": workspace_id,
                    "target_type": target_type,
                    "target_id": target_id,
                    "actor": actor,
                    "created_at": _now_iso(),
                }
            )
            store.write(events[-500:])

    def _audit(
        self,
        action: str,
        workspace_id: str,
        target_type: str,
        target_id: str,
        actor: str = "",
        *,
        reason: str = "",
        result: str = "ok",
        safe_error_code: str = "",
        snapshot_checksum: str = "",
    ) -> None:
        with _list_store(scheduling_audit_path()) as store:
            records = store.read()
            records.append(
                {
                    "id": f"scheduling_audit_{uuid4().hex}",
                    "workspace_id": workspace_id,
                    "target_type": target_type,
                    "target_id": target_id,
                    "actor": actor or "system",
                    "action": action,
                    "reason": reason,
                    "result": result,
                    "safe_error_code": safe_error_code,
                    "snapshot_checksum": snapshot_checksum[:12],
                    "created_at": _now_iso(),
                }
            )
            store.write(records[-500:])


class ExecutionCalendarService:
    def __init__(self, *, scheduling_service: ScheduleMaterializationService, campaign_service=None) -> None:
        self.scheduling_service = scheduling_service
        self.campaign_service = campaign_service

    def list_calendar_entries(
        self,
        *,
        workspace_id: str,
        start: str,
        end: str,
        timezone: str = "UTC",
        channel_plugin_id: str = "",
        campaign_id: str = "",
        status: str = "",
        attention_required: bool | None = None,
        limit: int = 200,
    ) -> list[CalendarEntry]:
        start_dt = _parse_datetime(start) or datetime.min.replace(tzinfo=UTC)
        end_dt = _parse_datetime(end) or datetime.max.replace(tzinfo=UTC)
        limit = max(1, min(limit, 500))
        entries: list[CalendarEntry] = []
        for occurrence in self.scheduling_service.occurrence_repository.list_all(workspace_id=workspace_id):
            scheduled = _parse_datetime(occurrence.scheduled_at_utc)
            if scheduled is None or scheduled < start_dt or scheduled > end_dt:
                continue
            if campaign_id and occurrence.campaign_id != campaign_id:
                continue
            entries.append(
                CalendarEntry(
                    id=f"calendar_occurrence_{occurrence.id}",
                    workspace_id=workspace_id,
                    entry_type="materialized_occurrence" if occurrence.publication_plan_id else "projected_occurrence",
                    starts_at=occurrence.scheduled_at_utc,
                    ends_at=occurrence.scheduled_at_utc,
                    timezone=timezone,
                    title=f"Occurrence {occurrence.sequence_number}",
                    status=occurrence.status,
                    campaign_id=occurrence.campaign_id,
                    schedule_id=occurrence.schedule_id,
                    occurrence_id=occurrence.id,
                    plan_id=occurrence.publication_plan_id,
                    attention_required=occurrence.status in {"uncertain", "blocked"},
                    blockers=[occurrence.blocked_reason] if occurrence.blocked_reason else [],
                )
            )
        for target in self.scheduling_service.planning_service.target_repository.list_all(workspace_id=workspace_id):
            scheduled = _parse_datetime(target.scheduled_at)
            if scheduled is None or scheduled < start_dt or scheduled > end_dt:
                continue
            if channel_plugin_id and target.channel_plugin_id != channel_plugin_id:
                continue
            metadata = dict(target.metadata or {})
            if campaign_id and metadata.get("campaign_id") != campaign_id:
                continue
            entries.append(
                CalendarEntry(
                    id=f"calendar_target_{target.id}",
                    workspace_id=workspace_id,
                    entry_type="publication_target",
                    starts_at=target.scheduled_at,
                    ends_at=target.scheduled_at,
                    timezone=timezone,
                    title=target.capability,
                    status=target.status,
                    channel_plugin_id=target.channel_plugin_id,
                    channel_account_id=target.channel_account_id,
                    campaign_id=str(metadata.get("campaign_id") or ""),
                    schedule_id=str(metadata.get("schedule_id") or ""),
                    occurrence_id=str(metadata.get("schedule_occurrence_id") or ""),
                    plan_id=target.publication_plan_id,
                    target_id=target.id,
                    attention_required=target.status in {"uncertain", "blocked", "failed", "stale", "invalid"},
                    blockers=[],
                    safe_summary=f"{target.channel_plugin_id} {target.capability}",
                )
            )
        if status:
            entries = [entry for entry in entries if entry.status == status]
        if attention_required is not None:
            entries = [entry for entry in entries if entry.attention_required is attention_required]
        return sorted(entries, key=lambda item: (item.starts_at, item.entry_type, item.id))[:limit]

    def summarize_range(self, *, workspace_id: str, start: str, end: str) -> dict[str, Any]:
        entries = self.list_calendar_entries(workspace_id=workspace_id, start=start, end=end)
        return {
            "count": len(entries),
            "attention_required": sum(entry.attention_required for entry in entries),
            "by_type": {
                kind: sum(entry.entry_type == kind for entry in entries)
                for kind in {entry.entry_type for entry in entries}
            },
        }

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "contract_version": EXECUTION_CALENDAR_CONTRACT_VERSION,
            "read_only": True,
        }


class CampaignService:
    def __init__(
        self, *, scheduling_service: ScheduleMaterializationService, calendar_service: ExecutionCalendarService
    ) -> None:
        self.scheduling_service = scheduling_service
        self.calendar_service = calendar_service
        self.campaign_repository = CampaignRepository()
        self.member_repository = CampaignMemberRepository()
        self.policy_repository = CampaignPolicyRepository()

    def create_campaign(
        self, *, workspace_id: str, name: str, created_by: str = "", description: str = "", timezone: str = "UTC"
    ) -> Campaign:
        policy = CampaignCoordinationPolicy(id=f"campaign_policy_{uuid4().hex}", workspace_id=workspace_id)
        policy = self.policy_repository.create(policy)
        campaign = Campaign(
            id=f"campaign_{uuid4().hex}",
            workspace_id=workspace_id,
            name=name.strip() or "Campaign",
            description=description,
            timezone=timezone,
            coordination_policy_id=policy.id,
            created_at=_now_iso(),
            updated_at=_now_iso(),
            created_by=created_by,
            updated_by=created_by,
        )
        saved = self.campaign_repository.create(campaign)
        self.scheduling_service._event("publication.campaign.created", workspace_id, "campaign", saved.id, created_by)
        self.scheduling_service._audit("campaign.create", workspace_id, "campaign", saved.id, created_by)
        return saved

    def add_member(
        self,
        campaign_id: str,
        *,
        workspace_id: str,
        member_type: str,
        member_id: str,
        position: int = 0,
        required: bool = True,
    ) -> CampaignMember:
        campaign = self._get_campaign(campaign_id, workspace_id=workspace_id)
        if member_type == "publication_plan":
            plan = self.scheduling_service.planning_service.plan_repository.get(member_id)
            if plan is None or plan.workspace_id != workspace_id:
                raise SchedulingValidationError("campaign.member_missing", "Publication plan was not found.")
            plan.metadata = {**dict(plan.metadata or {}), "campaign_id": campaign.id}
            self.scheduling_service.planning_service.plan_repository.save(plan)
        elif member_type == "publication_schedule":
            schedule = self.scheduling_service.schedule_repository.get(member_id)
            if schedule is None or schedule.workspace_id != workspace_id:
                raise SchedulingValidationError("campaign.member_missing", "Schedule was not found.")
            schedule.campaign_id = campaign.id
            self.scheduling_service.schedule_repository.save(schedule)
        else:
            raise SchedulingValidationError("campaign.member_type_invalid", "Unsupported campaign member type.")
        member = CampaignMember(
            id=f"campaign_member_{uuid4().hex}",
            campaign_id=campaign.id,
            member_type=member_type,
            member_id=member_id,
            position=max(position, 0),
            required=required,
            created_at=_now_iso(),
        )
        saved = self.member_repository.add(member)
        self.scheduling_service._audit("campaign.member.add", workspace_id, "campaign_member", saved.id)
        self.derive_status(campaign.id, workspace_id=workspace_id)
        return saved

    def remove_member(self, campaign_id: str, member_id: str, *, workspace_id: str) -> None:
        self._get_campaign(campaign_id, workspace_id=workspace_id)

        def mutate(records: list[CampaignMember]):
            changed = False
            for record in records:
                if record.id == member_id and record.campaign_id == campaign_id:
                    record.active = False
                    changed = True
            return changed, None

        _mutate_records(campaign_members_path(), CampaignMember, mutate)
        self.derive_status(campaign_id, workspace_id=workspace_id)

    def activate_campaign(self, campaign_id: str, *, workspace_id: str, actor: str = "") -> Campaign:
        campaign = self._get_campaign(campaign_id, workspace_id=workspace_id)
        campaign.status = CampaignStatus.ACTIVE.value
        campaign.updated_at = _now_iso()
        saved = self.campaign_repository.save(campaign)
        self.scheduling_service._event("publication.campaign.activated", workspace_id, "campaign", saved.id, actor)
        return saved

    def pause_campaign(self, campaign_id: str, *, workspace_id: str, actor: str = "", reason: str = "") -> Campaign:
        campaign = self._get_campaign(campaign_id, workspace_id=workspace_id)
        campaign.status = CampaignStatus.PAUSED.value
        campaign.paused_at = _now_iso()
        campaign.pause_reason = reason
        campaign.updated_at = _now_iso()
        for member in self.member_repository.list_by_campaign(campaign.id):
            if member.member_type == "publication_schedule":
                try:
                    self.scheduling_service.pause_schedule(
                        member.member_id, workspace_id=workspace_id, actor=actor, reason="campaign_paused"
                    )
                except Exception:
                    pass
        saved = self.campaign_repository.save(campaign)
        self.scheduling_service._event("publication.campaign.paused", workspace_id, "campaign", saved.id, actor)
        self.scheduling_service._audit("campaign.pause", workspace_id, "campaign", saved.id, actor, reason=reason)
        return saved

    def resume_campaign(self, campaign_id: str, *, workspace_id: str, actor: str = "") -> Campaign:
        campaign = self._get_campaign(campaign_id, workspace_id=workspace_id)
        for member in self.member_repository.list_by_campaign(campaign.id):
            if member.member_type == "publication_schedule":
                try:
                    self.scheduling_service.resume_schedule(member.member_id, workspace_id=workspace_id, actor=actor)
                except Exception:
                    pass
        campaign.status = CampaignStatus.ACTIVE.value
        campaign.updated_at = _now_iso()
        return self.campaign_repository.save(campaign)

    def cancel_campaign(self, campaign_id: str, *, workspace_id: str, actor: str = "", reason: str = "") -> Campaign:
        campaign = self._get_campaign(campaign_id, workspace_id=workspace_id)
        for member in self.member_repository.list_by_campaign(campaign.id):
            if member.member_type == "publication_schedule":
                try:
                    self.scheduling_service.cancel_schedule(
                        member.member_id, workspace_id=workspace_id, actor=actor, reason="campaign_cancelled"
                    )
                except Exception:
                    pass
            if member.member_type == "publication_plan":
                try:
                    self.scheduling_service.planning_service.cancel_plan(
                        member.member_id, workspace_id=workspace_id, actor=actor
                    )
                except Exception:
                    pass
        campaign.status = CampaignStatus.CANCELLED.value
        campaign.cancelled_at = _now_iso()
        campaign.cancellation_reason = reason
        campaign.updated_at = _now_iso()
        saved = self.campaign_repository.save(campaign)
        self.scheduling_service._event("publication.campaign.cancelled", workspace_id, "campaign", saved.id, actor)
        self.scheduling_service._audit("campaign.cancel", workspace_id, "campaign", saved.id, actor, reason=reason)
        return saved

    def derive_status(self, campaign_id: str, *, workspace_id: str) -> Campaign:
        campaign = self._get_campaign(campaign_id, workspace_id=workspace_id)
        if campaign.status in {
            CampaignStatus.CANCELLED.value,
            CampaignStatus.ARCHIVED.value,
            CampaignStatus.PAUSED.value,
        }:
            return campaign
        statuses: list[str] = []
        for member in self.member_repository.list_by_campaign(campaign.id):
            if member.member_type == "publication_schedule":
                schedule = self.scheduling_service.schedule_repository.get(member.member_id)
                if schedule is not None:
                    statuses.append(schedule.status)
                    occurrences = self.scheduling_service.occurrence_repository.list_by_schedule(schedule.id)
                    statuses.extend(item.status for item in occurrences)
            elif member.member_type == "publication_plan":
                plan = self.scheduling_service.planning_service.plan_repository.get(member.member_id)
                if plan is not None:
                    statuses.append(plan.status)
        if not statuses:
            campaign.status = CampaignStatus.DRAFT.value
        elif any(status in {"uncertain", "blocked", PublicationPlanStatus.BLOCKED.value} for status in statuses):
            campaign.status = CampaignStatus.ATTENTION_REQUIRED.value
        elif all(status in {"completed", PublicationPlanStatus.COMPLETED.value} for status in statuses):
            campaign.status = CampaignStatus.COMPLETED.value
        elif any(status in {"active", "running", "queued", PublicationPlanStatus.RUNNING.value} for status in statuses):
            campaign.status = CampaignStatus.ACTIVE.value
        elif any(status in {"ready", "scheduled", PublicationPlanStatus.READY.value} for status in statuses):
            campaign.status = CampaignStatus.READY.value
        else:
            campaign.status = CampaignStatus.PARTIALLY_COMPLETED.value
        campaign.updated_at = _now_iso()
        saved = self.campaign_repository.save(campaign)
        self.scheduling_service._event("publication.campaign.status_changed", workspace_id, "campaign", saved.id)
        return saved

    def list_campaign_activity(self, campaign_id: str, *, workspace_id: str) -> dict[str, Any]:
        campaign = self._get_campaign(campaign_id, workspace_id=workspace_id)
        return {
            "campaign": asdict(campaign),
            "members": [asdict(item) for item in self.member_repository.list_by_campaign(campaign.id)],
        }

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "contract_version": CAMPAIGN_CONTRACT_VERSION,
            "campaigns": len(self.campaign_repository.list_all()),
        }

    def _get_campaign(self, campaign_id: str, *, workspace_id: str) -> Campaign:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None or campaign.workspace_id != workspace_id:
            raise SchedulingValidationError("campaign.not_found", "Campaign was not found.")
        return campaign
