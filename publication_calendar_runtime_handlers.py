from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from publication_scheduling import ExecutionCalendarService, ScheduleOccurrenceRepository
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.execution_context import ExecutionContext, _assert_no_secret_values
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.mutations import MutationReceipt, mutation_input_fingerprint
from src.core.runtime.plans import ExecutionPlanNode
from src.core.runtime.playbooks import PlaybookNode
from src.core.runtime.results import NodeResult
from src.core.scheduling import ScheduleOccurrence, ScheduleOccurrenceStatus

CALENDAR_COMPONENT_ID = "publication-calendar-local"
CALENDAR_EVENT_READ_CAPABILITY = "calendar.event.read"
CALENDAR_EVENT_CREATE_CAPABILITY = "calendar.event.create"

CALENDAR_EVENT_READ_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["start", "end"],
    "properties": {
        "workspace_id": {"type": "string"},
        "start": {"type": "string", "format": "date-time"},
        "end": {"type": "string", "format": "date-time"},
        "timezone": {"type": "string", "default": "UTC"},
        "channel_plugin_id": {"type": "string"},
        "campaign_id": {"type": "string"},
        "status": {"type": "string"},
        "attention_required": {"type": "boolean"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200},
    },
}

CALENDAR_EVENT_READ_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["events"],
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "title", "start", "end", "status", "source"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "status": {"type": "string"},
                    "source": {"type": "string"},
                },
            },
        }
    },
}

CALENDAR_EVENT_CREATE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schedule_id", "campaign_id", "start"],
    "properties": {
        "campaign_id": {"type": "string"},
        "end": {"type": "string", "format": "date-time"},
        "occurrence_id": {"type": "string"},
        "occurrence_key": {"type": "string"},
        "schedule_id": {"type": "string"},
        "sequence_number": {"type": "integer", "minimum": 1},
        "start": {"type": "string", "format": "date-time"},
        "status": {"type": "string", "default": ScheduleOccurrenceStatus.PROJECTED.value},
        "timezone": {"type": "string", "default": "UTC"},
        "workspace_id": {"type": "string"},
    },
}

CALENDAR_EVENT_CREATE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["event", "mutation_receipt", "readback_verified", "resource_ref"],
    "properties": {
        "event": {"type": "object"},
        "mutation_receipt": {"type": "object"},
        "readback_verified": {"type": "boolean"},
        "resource_ref": {"type": "string"},
    },
}


@dataclass
class CalendarEventReadHandler:
    calendar_service: ExecutionCalendarService
    component_id: str = CALENDAR_COMPONENT_ID
    capability_id: str = CALENDAR_EVENT_READ_CAPABILITY

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> NodeResult:
        del node, resolved_node
        try:
            _assert_no_secret_values(input_data, code="calendar.input_secret_value")
            query = _read_query(input_data, context)
        except PlaybookExecutionError as exc:
            return NodeResult.failure(exc.code, exc.user_message, exc.details)
        try:
            entries = self.calendar_service.list_calendar_entries(**query)
        except Exception as exc:
            return NodeResult.failure(
                "CAPABILITY_EXECUTION_FAILED",
                "Calendar event read failed.",
                {"error": type(exc).__name__},
            )
        return NodeResult.success(
            {
                "events": [_normalize_calendar_entry(entry) for entry in entries],
                "source": CALENDAR_COMPONENT_ID,
            }
        )


@dataclass
class CalendarEventCreateHandler:
    calendar_service: ExecutionCalendarService
    occurrence_repository: ScheduleOccurrenceRepository
    component_id: str = CALENDAR_COMPONENT_ID
    capability_id: str = CALENDAR_EVENT_CREATE_CAPABILITY

    def execute(
        self,
        *,
        context: ExecutionContext,
        node: PlaybookNode,
        resolved_node: ExecutionPlanNode,
        input_data: dict[str, Any],
    ) -> NodeResult:
        del node, resolved_node
        try:
            _assert_no_secret_values(input_data, code="calendar.create_input_secret_value")
            command = _create_command(input_data, context)
        except PlaybookExecutionError as exc:
            return NodeResult.failure(exc.code, exc.user_message, exc.details)

        runtime = dict(input_data.get("_runtime") or {})
        mutation_id = str(runtime.get("mutation_id") or command["occurrence_id"])
        idempotency_key = str(runtime.get("idempotency_key") or command["occurrence_key"])
        try:
            occurrence = self.occurrence_repository.find_by_key(command["occurrence_key"])
            if occurrence is None:
                occurrence = self.occurrence_repository.create(_occurrence_from_command(command))
            event = _readback_created_event(self.calendar_service, occurrence, timezone=command["timezone"])
            receipt = MutationReceipt(
                mutation_id=mutation_id,
                capability_id=CALENDAR_EVENT_CREATE_CAPABILITY,
                component_id=CALENDAR_COMPONENT_ID,
                resource_ref=f"calendar-occurrence:{occurrence.id}",
                applied_at=datetime.now(UTC).isoformat(timespec="seconds"),
                idempotency_key=idempotency_key,
                result_fingerprint=mutation_input_fingerprint(event),
                metadata={"readback_verified": True, "resource_type": "calendar_occurrence"},
            )
        except Exception as exc:
            return NodeResult.failure(
                "CAPABILITY_EXECUTION_FAILED",
                "Calendar event create failed.",
                {"error": type(exc).__name__},
            )

        return NodeResult.success(
            {
                "event": event,
                "mutation_receipt": receipt.to_dict(),
                "readback_verified": True,
                "resource_ref": receipt.resource_ref,
                "source": CALENDAR_COMPONENT_ID,
            },
            {"applied_at": receipt.applied_at, "readback_verified": True},
        )


def register_calendar_runtime_handlers(
    handler_registry: CapabilityHandlerRegistry,
    *,
    calendar_service: ExecutionCalendarService,
) -> CalendarEventReadHandler:
    handler = CalendarEventReadHandler(calendar_service=calendar_service)
    handler_registry.register(handler)
    return handler


def register_calendar_mutation_runtime_handlers(
    handler_registry: CapabilityHandlerRegistry,
    *,
    calendar_service: ExecutionCalendarService,
    occurrence_repository: ScheduleOccurrenceRepository,
) -> CalendarEventCreateHandler:
    handler = CalendarEventCreateHandler(
        calendar_service=calendar_service,
        occurrence_repository=occurrence_repository,
    )
    handler_registry.register(handler)
    return handler


def _read_query(input_data: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    start = str(input_data.get("start") or "")
    end = str(input_data.get("end") or "")
    start_dt = _parse_datetime(start, "start")
    end_dt = _parse_datetime(end, "end")
    if start_dt >= end_dt:
        raise PlaybookExecutionError(
            "CALENDAR_INVALID_RANGE",
            "Calendar read start must be before end.",
            {"start": start, "end": end},
        )
    workspace_id = str(input_data.get("workspace_id") or context.trigger_event.workspace_id or "")
    if not workspace_id:
        raise PlaybookExecutionError(
            "CALENDAR_INPUT_INVALID",
            "Calendar read requires a workspace_id from input or trigger event.",
        )
    limit = int(input_data.get("limit") or 200)
    return {
        "workspace_id": workspace_id,
        "start": start_dt.isoformat(timespec="seconds"),
        "end": end_dt.isoformat(timespec="seconds"),
        "timezone": str(input_data.get("timezone") or "UTC"),
        "channel_plugin_id": str(input_data.get("channel_plugin_id") or ""),
        "campaign_id": str(input_data.get("campaign_id") or ""),
        "status": str(input_data.get("status") or ""),
        "attention_required": input_data.get("attention_required")
        if isinstance(input_data.get("attention_required"), bool)
        else None,
        "limit": max(1, min(limit, 500)),
    }


def _parse_datetime(value: str, field_name: str) -> datetime:
    if not value:
        raise PlaybookExecutionError(
            "CALENDAR_INPUT_INVALID",
            "Calendar read requires start and end timestamps.",
            {"field": field_name},
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PlaybookExecutionError(
            "CALENDAR_INPUT_INVALID",
            "Calendar timestamp must be ISO-8601.",
            {"field": field_name},
        ) from exc
    if parsed.tzinfo is None:
        raise PlaybookExecutionError(
            "CALENDAR_INPUT_INVALID",
            "Calendar timestamp must include timezone information.",
            {"field": field_name},
        )
    return parsed


def _normalize_calendar_entry(entry: Any) -> dict[str, Any]:
    payload = asdict(entry) if hasattr(entry, "__dataclass_fields__") else dict(entry)
    return {
        "id": str(payload.get("id") or ""),
        "workspace_id": str(payload.get("workspace_id") or ""),
        "entry_type": str(payload.get("entry_type") or ""),
        "title": str(payload.get("title") or ""),
        "start": str(payload.get("starts_at") or ""),
        "end": str(payload.get("ends_at") or ""),
        "timezone": str(payload.get("timezone") or ""),
        "status": str(payload.get("status") or ""),
        "source": CALENDAR_COMPONENT_ID,
        "channel_plugin_id": str(payload.get("channel_plugin_id") or ""),
        "channel_account_id": str(payload.get("channel_account_id") or ""),
        "campaign_id": str(payload.get("campaign_id") or ""),
        "schedule_id": str(payload.get("schedule_id") or ""),
        "occurrence_id": str(payload.get("occurrence_id") or ""),
        "plan_id": str(payload.get("plan_id") or ""),
        "target_id": str(payload.get("target_id") or ""),
        "attention_required": bool(payload.get("attention_required")),
        "blockers": list(payload.get("blockers") or []),
        "safe_summary": str(payload.get("safe_summary") or ""),
    }


def _create_command(input_data: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    start = _parse_datetime(str(input_data.get("start") or ""), "start")
    end = _parse_datetime(str(input_data.get("end") or input_data.get("start") or ""), "end")
    if end < start:
        raise PlaybookExecutionError(
            "CALENDAR_INVALID_RANGE",
            "Calendar create end must not be before start.",
            {"end": end.isoformat(timespec="seconds"), "start": start.isoformat(timespec="seconds")},
        )
    workspace_id = str(input_data.get("workspace_id") or context.trigger_event.workspace_id or "")
    schedule_id = str(input_data.get("schedule_id") or "")
    campaign_id = str(input_data.get("campaign_id") or "")
    if not workspace_id or not schedule_id or not campaign_id:
        raise PlaybookExecutionError(
            "CALENDAR_INPUT_INVALID",
            "Calendar create requires workspace_id, schedule_id, and campaign_id.",
        )
    status = str(input_data.get("status") or ScheduleOccurrenceStatus.PROJECTED.value)
    if status not in {item.value for item in ScheduleOccurrenceStatus}:
        raise PlaybookExecutionError("CALENDAR_INPUT_INVALID", "Calendar create status is unsupported.")
    sequence_number = int(input_data.get("sequence_number") or 1)
    if sequence_number < 1:
        raise PlaybookExecutionError("CALENDAR_INPUT_INVALID", "Calendar create sequence_number must be positive.")
    runtime = dict(input_data.get("_runtime") or {})
    idempotency_key = str(runtime.get("idempotency_key") or "")
    occurrence_key = str(input_data.get("occurrence_key") or f"runtime:{idempotency_key or _stable_suffix(input_data)}")
    occurrence_id = str(input_data.get("occurrence_id") or f"runtime-{_stable_suffix({'key': occurrence_key})}")
    return {
        "campaign_id": campaign_id,
        "occurrence_id": occurrence_id,
        "occurrence_key": occurrence_key,
        "schedule_id": schedule_id,
        "scheduled_at_local": start.isoformat(timespec="seconds"),
        "scheduled_at_utc": start.astimezone(UTC).isoformat(timespec="seconds"),
        "sequence_number": sequence_number,
        "status": status,
        "timezone": str(input_data.get("timezone") or "UTC"),
        "workspace_id": workspace_id,
    }


def _occurrence_from_command(command: dict[str, Any]) -> ScheduleOccurrence:
    return ScheduleOccurrence(
        id=str(command["occurrence_id"]),
        workspace_id=str(command["workspace_id"]),
        schedule_id=str(command["schedule_id"]),
        campaign_id=str(command["campaign_id"]),
        occurrence_key=str(command["occurrence_key"]),
        generation_version=1,
        sequence_number=int(command["sequence_number"]),
        scheduled_at_local=str(command["scheduled_at_local"]),
        timezone=str(command["timezone"]),
        scheduled_at_utc=str(command["scheduled_at_utc"]),
        status=str(command["status"]),
        metadata={"created_by": "generic-runtime"},
    )


def _readback_created_event(
    calendar_service: ExecutionCalendarService,
    occurrence: ScheduleOccurrence,
    *,
    timezone: str,
) -> dict[str, Any]:
    entries = calendar_service.list_calendar_entries(
        workspace_id=occurrence.workspace_id,
        start=occurrence.scheduled_at_utc,
        end=occurrence.scheduled_at_utc,
        timezone=timezone,
        limit=50,
    )
    expected = f"calendar_occurrence_{occurrence.id}"
    for entry in entries:
        normalized = _normalize_calendar_entry(entry)
        if normalized["id"] == expected:
            return normalized
    raise PlaybookExecutionError(
        "CALENDAR_READBACK_FAILED",
        "Calendar create readback did not find the created occurrence.",
        {"resource_ref": f"calendar-occurrence:{occurrence.id}"},
    )


def _stable_suffix(value: dict[str, Any]) -> str:
    encoded = repr(sorted((str(key), str(child)) for key, child in value.items())).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]
