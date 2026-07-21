from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import channel_store
from channel_models import ChannelConnection
from publication_execution import Clock
from publication_scheduling import RecurrenceEngine, SchedulingValidationError
from src.core.scheduling import (
    CAMPAIGN_CONTRACT_VERSION,
    EXECUTION_CALENDAR_CONTRACT_VERSION,
    PUBLICATION_SCHEDULE_CONTRACT_VERSION,
    RECURRENCE_RULE_CONTRACT_VERSION,
    SCHEDULE_AUTHORIZATION_CONTRACT_VERSION,
    SCHEDULE_OCCURRENCE_CONTRACT_VERSION,
    SCHEDULE_POLICY_CONTRACT_VERSION,
    SCHEDULING_FRAMEWORK_VERSION,
    RecurrenceRule,
    SchedulePolicy,
)
from tests.test_media_library_phase11 import Phase11Config, runtime_with_library
from tests.test_support import isolated_channel_store


class FixedClock(Clock):
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


class SchedulingFrameworkPhase14Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = isolated_channel_store(Path(self.tmp.name))
        self.store.__enter__()
        self.addCleanup(self.store.__exit__, None, None, None)
        self.config = Phase11Config()
        self.config.media_dir = Path(self.tmp.name) / "tmp_media"
        self.config.content_dir = Path(self.tmp.name) / "content"
        self.config.media_storage_root = Path(self.tmp.name) / "media-root"
        self.config.linkedin_user_data_dir = Path(self.tmp.name) / "profile"
        self.config.media_dir.mkdir()
        self.config.content_dir.mkdir()
        self.config.linkedin_user_data_dir.mkdir()
        self.runtime = runtime_with_library(self.config)
        self.runtime.content_service(self.config)
        self.runtime.publication_planning_service(self.config)
        self.runtime.publication_execution_service(self.config)
        self.scheduling = self.runtime.schedule_materialization_service(self.config)
        self.scheduling.clock = FixedClock(datetime(2026, 7, 21, 12, 0, tzinfo=UTC))
        self.calendar = self.runtime.execution_calendar_service(self.config)
        self.campaigns = self.runtime.campaign_service(self.config)
        self.planning = self.runtime.publication_planning_service(self.config)
        self.content_service = self.runtime.content_service(self.config)
        channel_store.save_channel_connection(
            ChannelConnection(
                id="connection_linkedin",
                channel_id="linkedin",
                mode="playwright_local",
                status="connected",
                created_at=channel_store.now_iso(),
                updated_at=channel_store.now_iso(),
            )
        )

    def prepared_plan(self):
        item = self.content_service.create_content(
            workspace_id="linkedin",
            title="Canonical schedule content",
            body="Scheduled canonical body",
            created_by="tester",
        )
        plan = self.planning.create_plan(
            workspace_id="linkedin",
            content_item_id=item.id,
            name="Template plan",
            created_by="tester",
        )
        self.planning.add_target(
            plan.id,
            workspace_id="linkedin",
            channel_plugin_id="channel.linkedin",
            channel_account_id="linkedin",
            capability="channel.publish.text",
            scheduled_at="2026-07-22T09:00:00+00:00",
            timezone="UTC",
        )
        self.planning.prepare_plan(plan.id, workspace_id="linkedin", actor="tester")
        return plan

    def active_schedule(self, *, policy: dict | None = None, recurrence: dict | None = None):
        plan = self.prepared_plan()
        schedule = self.scheduling.create_schedule(
            workspace_id="linkedin",
            name="Daily schedule",
            starts_at_local="2026-07-22T09:00:00",
            timezone="Europe/Amsterdam",
            recurrence=recurrence or {"frequency": "daily", "interval": 1, "count": 3},
            source_publication_plan_id=plan.id,
            created_by="tester",
            policy=policy or {},
        )
        return self.scheduling.activate_schedule(schedule.id, workspace_id="linkedin", actor="tester")

    def test_contract_versions_and_health(self) -> None:
        self.assertEqual(SCHEDULING_FRAMEWORK_VERSION, "0.1.0")
        self.assertEqual(PUBLICATION_SCHEDULE_CONTRACT_VERSION, "1.0")
        self.assertEqual(RECURRENCE_RULE_CONTRACT_VERSION, "1.0")
        self.assertEqual(SCHEDULE_OCCURRENCE_CONTRACT_VERSION, "1.0")
        self.assertEqual(SCHEDULE_POLICY_CONTRACT_VERSION, "1.0")
        self.assertEqual(SCHEDULE_AUTHORIZATION_CONTRACT_VERSION, "1.0")
        self.assertEqual(EXECUTION_CALENDAR_CONTRACT_VERSION, "1.0")
        self.assertEqual(CAMPAIGN_CONTRACT_VERSION, "1.0")
        self.assertEqual(self.scheduling.health_check()["status"], "ready")

    def test_recurrence_subset_bounds_and_checksums(self) -> None:
        engine = RecurrenceEngine()
        policy = SchedulePolicy(id="p", workspace_id="linkedin")
        once = engine.preview(
            starts_at_local="2026-07-22T09:00:00",
            timezone="UTC",
            rule=RecurrenceRule(id="r", frequency="once"),
            policy=policy,
            maximum=5,
        )
        self.assertEqual(len(once), 1)
        daily = engine.preview(
            starts_at_local="2026-07-22T09:00:00",
            timezone="UTC",
            rule=RecurrenceRule(id="r", frequency="daily", interval=2, count=2),
            policy=policy,
            maximum=10,
        )
        self.assertEqual([item["scheduled_at_local"] for item in daily], ["2026-07-22T09:00:00", "2026-07-24T09:00:00"])
        weekly = engine.preview(
            starts_at_local="2026-07-20T09:00:00",
            timezone="UTC",
            rule=RecurrenceRule(id="r", frequency="weekly", by_weekday=[0, 2], count=3),
            policy=policy,
            maximum=10,
        )
        self.assertEqual(
            [item["scheduled_at_local"] for item in weekly],
            ["2026-07-20T09:00:00", "2026-07-22T09:00:00", "2026-07-27T09:00:00"],
        )
        monthly_skip = engine.preview(
            starts_at_local="2026-01-31T09:00:00",
            timezone="UTC",
            rule=RecurrenceRule(id="r", frequency="monthly", by_month_day=[31], count=3),
            policy=policy,
            maximum=10,
        )
        self.assertEqual(
            [item["scheduled_at_local"] for item in monthly_skip],
            ["2026-01-31T09:00:00", "2026-03-31T09:00:00", "2026-05-31T09:00:00"],
        )
        last_valid = SchedulePolicy(id="p", workspace_id="linkedin", monthly_invalid_date_policy="last_valid_day")
        monthly_last = engine.preview(
            starts_at_local="2026-01-31T09:00:00",
            timezone="UTC",
            rule=RecurrenceRule(id="r", frequency="monthly", by_month_day=[31], count=3),
            policy=last_valid,
            maximum=10,
        )
        self.assertIn("2026-02-28T09:00:00", [item["scheduled_at_local"] for item in monthly_last])
        with self.assertRaises(SchedulingValidationError):
            engine.preview(
                starts_at_local="2026-07-22T09:00:00",
                timezone="UTC",
                rule=RecurrenceRule(id="r", frequency="hourly"),
                policy=policy,
            )
        checksum_a = engine.normalize_rule(RecurrenceRule(id="a", frequency="daily", interval=1)).checksum
        checksum_b = engine.normalize_rule(RecurrenceRule(id="b", frequency="daily", interval=1)).checksum
        self.assertEqual(checksum_a, checksum_b)

    def test_timezone_dst_policies(self) -> None:
        engine = RecurrenceEngine()
        first = SchedulePolicy(id="p", workspace_id="linkedin", dst_ambiguous_policy="first_occurrence")
        second = SchedulePolicy(id="p", workspace_id="linkedin", dst_ambiguous_policy="second_occurrence")
        first_result = engine.resolve_local("2026-10-25T02:30:00", "Europe/Amsterdam", first)
        second_result = engine.resolve_local("2026-10-25T02:30:00", "Europe/Amsterdam", second)
        self.assertNotEqual(first_result["utc"], second_result["utc"])
        review = SchedulePolicy(id="p", workspace_id="linkedin")
        nonexistent = engine.resolve_local("2026-03-29T02:30:00", "Europe/Amsterdam", review)
        self.assertFalse(nonexistent["valid"])
        shifted = engine.resolve_local(
            "2026-03-29T02:30:00",
            "Europe/Amsterdam",
            SchedulePolicy(id="p", workspace_id="linkedin", dst_nonexistent_policy="shift_forward"),
        )
        self.assertTrue(shifted["valid"])
        self.assertEqual(shifted["dst_status"], "nonexistent_shifted")
        with self.assertRaises(SchedulingValidationError):
            engine.resolve_local("2026-07-22T09:00:00", "Invalid/Zone", review)

    def test_schedule_lifecycle_template_snapshot_and_materialization(self) -> None:
        schedule = self.active_schedule()
        snapshot = self.scheduling.snapshot_repository.get(schedule.template_snapshot_id)
        self.assertEqual(snapshot.source_publication_plan_id.startswith("publication_plan_"), True)
        serialized = json.dumps(snapshot.__dict__)
        self.assertNotIn("job_id", serialized)
        self.assertNotIn("publication_id", serialized)
        self.assertNotIn("storage_reference", serialized)
        result = self.scheduling.materialize_schedule(schedule.id, workspace_id="linkedin", batch_size=2)
        self.assertEqual(len(result["materialized"]), 2)
        occurrences = self.scheduling.occurrence_repository.list_by_schedule(schedule.id)
        self.assertEqual(len(occurrences), 2)
        self.assertTrue(occurrences[0].publication_plan_id)
        self.assertTrue(occurrences[0].publication_target_ids)
        again = self.scheduling.materialize_schedule(schedule.id, workspace_id="linkedin", batch_size=2)
        self.assertEqual(len(again["materialized"]), 1)
        exhausted = self.scheduling.materialize_schedule(schedule.id, workspace_id="linkedin", batch_size=2)
        self.assertEqual(exhausted["materialized"], [])

    def test_exclusions_overlap_missed_and_horizon_limits(self) -> None:
        schedule = self.active_schedule(policy={"maximum_materialized_occurrences": 3, "overlap_policy": "block_new"})
        self.scheduling.exclusion_repository.create(
            self.scheduling.exclusion_repository.cls(
                id="exclusion_one",
                schedule_id=schedule.id,
                exclusion_type="single_occurrence",
                starts_at_local="2026-07-22T09:00:00",
                timezone="Europe/Amsterdam",
            )
        )
        result = self.scheduling.materialize_schedule(schedule.id, workspace_id="linkedin", batch_size=3)
        self.assertEqual(result["materialized"][0]["status"], "skipped")
        occurrence = self.scheduling.occurrence_repository.list_by_schedule(schedule.id)[0]
        self.assertEqual(occurrence.status, "skipped")
        missed = self.scheduling.detect_missed_occurrences(schedule.id, workspace_id="linkedin")
        self.assertEqual(missed, [])
        blocked_schedule = self.active_schedule(policy={"overlap_policy": "block_new"})
        self.scheduling.materialize_schedule(blocked_schedule.id, workspace_id="linkedin", batch_size=1)
        first = self.scheduling.occurrence_repository.list_by_schedule(blocked_schedule.id)[0]
        target = self.planning.target_repository.get(first.publication_target_ids[0])
        target.status = "running"
        self.planning.target_repository.save(target)
        blocked = self.scheduling.materialize_schedule(blocked_schedule.id, workspace_id="linkedin", batch_size=2)
        self.assertTrue(any(item["code"] == "schedule.overlap_blocked" for item in blocked["blockers"]))

    def test_bounded_authorization_consumption_and_invalidation(self) -> None:
        schedule = self.active_schedule(policy={"authorization_policy": "bounded_schedule_authorization"})
        authorization = self.scheduling.authorize_schedule(
            schedule.id,
            workspace_id="linkedin",
            actor="operator",
            valid_until="2026-08-01T00:00:00+00:00",
            maximum_occurrences=1,
        )
        result = self.scheduling.materialize_schedule(schedule.id, workspace_id="linkedin", batch_size=1)
        self.assertEqual(len(result["materialized"]), 1)
        consumed = self.scheduling.authorization_repository.get(authorization.id)
        self.assertEqual(consumed.consumed_occurrences, 1)
        self.assertEqual(consumed.status, "exhausted")
        occurrence = self.scheduling.occurrence_repository.list_by_schedule(schedule.id)[0]
        target = self.planning.target_repository.get(occurrence.publication_target_ids[0])
        self.assertEqual(target.metadata["schedule_authorization_id"], authorization.id)
        consumed.template_snapshot_checksum = "changed"
        consumed.status = "active"
        consumed.maximum_occurrences = 2
        self.scheduling.authorization_repository.save(consumed)
        with self.assertRaises(SchedulingValidationError):
            self.scheduling.materialize_schedule(schedule.id, workspace_id="linkedin", batch_size=2)

    def test_calendar_is_read_only_and_campaigns_coordinate_members(self) -> None:
        schedule = self.active_schedule()
        campaign = self.campaigns.create_campaign(workspace_id="linkedin", name="Launch", created_by="tester")
        member = self.campaigns.add_member(
            campaign.id,
            workspace_id="linkedin",
            member_type="publication_schedule",
            member_id=schedule.id,
        )
        self.assertTrue(member.id)
        self.campaigns.activate_campaign(campaign.id, workspace_id="linkedin", actor="tester")
        self.scheduling.materialize_schedule(schedule.id, workspace_id="linkedin", batch_size=1)
        entries = self.calendar.list_calendar_entries(
            workspace_id="linkedin",
            start="2026-07-21T00:00:00+00:00",
            end="2026-07-30T00:00:00+00:00",
            campaign_id=campaign.id,
        )
        self.assertTrue(entries)
        serialized = json.dumps([entry.__dict__ for entry in entries])
        self.assertNotIn("local_path", serialized)
        self.assertNotIn("storage_reference", serialized)
        before = len(self.scheduling.occurrence_repository.list_by_schedule(schedule.id))
        self.calendar.summarize_range(
            workspace_id="linkedin",
            start="2026-07-21T00:00:00+00:00",
            end="2026-07-30T00:00:00+00:00",
        )
        self.assertEqual(before, len(self.scheduling.occurrence_repository.list_by_schedule(schedule.id)))
        paused = self.campaigns.pause_campaign(campaign.id, workspace_id="linkedin", actor="tester")
        self.assertEqual(paused.status, "paused")
        self.assertEqual(self.scheduling.schedule_repository.get(schedule.id).status, "paused")
        cancelled = self.campaigns.cancel_campaign(campaign.id, workspace_id="linkedin", actor="tester")
        self.assertEqual(cancelled.status, "cancelled")

    def test_reconciliation_integrity_worker_and_boundaries(self) -> None:
        schedule = self.active_schedule()
        self.scheduling.materialize_schedule(schedule.id, workspace_id="linkedin", batch_size=1)
        occurrence = self.scheduling.occurrence_repository.list_by_schedule(schedule.id)[0]
        target = self.planning.target_repository.get(occurrence.publication_target_ids[0])
        target.status = "uncertain"
        self.planning.target_repository.save(target)
        result = self.scheduling.reconcile_occurrence(occurrence.id, workspace_id="linkedin", dry_run=False)
        self.assertEqual(result["derived_status"], "uncertain")
        self.assertEqual(self.scheduling.schedule_repository.get(schedule.id).status, "paused")
        issues = self.scheduling.scan_integrity(workspace_id="linkedin")
        self.assertIsInstance(issues, list)
        import worker

        self.assertGreaterEqual(worker.materialize_due_publication_schedules(self.config), 0)
        scheduling_sources = "\n".join(
            path.read_text(encoding="utf-8") for path in Path("src/core/scheduling").glob("*.py")
        )
        self.assertNotIn("channels.", scheduling_sources)
        service_source = Path("publication_scheduling.py").read_text(encoding="utf-8")
        self.assertNotIn("LinkedIn", service_source)
        self.assertNotIn("browser_provider", service_source)
        self.assertNotIn("create_session", service_source)
        dispatcher = Path("publication_execution.py").read_text(encoding="utf-8")
        self.assertNotIn("RecurrenceRule", dispatcher)
        linkedin_sources = "\n".join(
            path.read_text(encoding="utf-8") for path in Path("channels/linkedin").rglob("*.py")
        )
        self.assertNotIn("ScheduleOccurrenceRepository", linkedin_sources)
