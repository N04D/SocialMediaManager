from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from publication_scheduling import ExecutionCalendarService
from src.core.runtime.errors import PlaybookExecutionError
from src.core.runtime.execution_context import ExecutionContext, _assert_no_secret_values
from src.core.runtime.handlers import CapabilityHandlerRegistry
from src.core.runtime.plans import ExecutionPlanNode
from src.core.runtime.playbooks import PlaybookNode
from src.core.runtime.results import NodeResult

CALENDAR_COMPONENT_ID = "publication-calendar-local"
CALENDAR_EVENT_READ_CAPABILITY = "calendar.event.read"

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


def register_calendar_runtime_handlers(
    handler_registry: CapabilityHandlerRegistry,
    *,
    calendar_service: ExecutionCalendarService,
) -> CalendarEventReadHandler:
    handler = CalendarEventReadHandler(calendar_service=calendar_service)
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
