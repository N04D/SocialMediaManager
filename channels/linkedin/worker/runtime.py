from __future__ import annotations

import os
from typing import Any

from channel_models import WorkerHeartbeat
from channel_store import now_iso, save_worker_heartbeat



def worker_id_for_channel(channel_id: str) -> str:
    return f"{channel_id}:{os.getpid()}"



def save_channel_worker_heartbeat(
    channel_id: str,
    *,
    status: str,
    current_job_id: str = "",
    current_job_type: str = "",
    last_error: str = "",
    worker_id: str | None = None,
    started_at: str = "",
) -> WorkerHeartbeat:
    heartbeat = WorkerHeartbeat(
        worker_id=worker_id or worker_id_for_channel(channel_id),
        worker_type="channel_worker",
        channel_id=channel_id,
        status=status,
        last_seen_at=now_iso(),
        current_job_id=current_job_id,
        last_error=last_error,
        started_at=started_at or now_iso(),
        current_job_type=current_job_type,
        process_id=os.getpid(),
    )
    return save_worker_heartbeat(heartbeat)
