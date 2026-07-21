from __future__ import annotations

import argparse
import os
import signal
import threading
from datetime import datetime

from channel_models import WorkerHeartbeat
from channel_store import (
    claim_next_metric_job,
    claim_next_publish_job,
    ensure_channel_store_dirs,
    heartbeat_metric_job,
    heartbeat_publish_job,
    now_iso,
    save_worker_heartbeat,
)
from pipeline import (
    AppConfig,
    cleanup_media,
    download_images_from_urls,
    ensure_runtime_dirs,
    load_config,
    stage_linkedin_post,
)
from plugin_runtime import get_plugin_runtime
from scheduler import append_worker_run, load_schedule, next_due_record, update_schedule_record

DEFAULT_CHANNEL_WORKER_POLL_SECONDS = int(os.environ.get("CHANNEL_WORKER_POLL_SECONDS", "15"))
DEFAULT_CHANNEL_WORKER_HEARTBEAT_SECONDS = int(os.environ.get("CHANNEL_WORKER_HEARTBEAT_SECONDS", "10"))
DEFAULT_CHANNEL_JOB_LEASE_SECONDS = int(os.environ.get("CHANNEL_JOB_LEASE_SECONDS", "180"))


class LeaseKeeper:
    def __init__(
        self,
        *,
        channel_id: str,
        worker_id: str,
        job_id: str,
        job_type: str,
        started_at: str,
        heartbeat_seconds: int,
        lease_seconds: int,
    ) -> None:
        self.channel_id = channel_id
        self.worker_id = worker_id
        self.job_id = job_id
        self.job_type = job_type
        self.started_at = started_at
        self.heartbeat_seconds = max(heartbeat_seconds, 1)
        self.lease_seconds = max(lease_seconds, self.heartbeat_seconds + 1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self.heartbeat_seconds + 1)

    def _run(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            if self.job_type == "publish":
                heartbeat_publish_job(self.job_id, worker_id=self.worker_id, lease_seconds=self.lease_seconds)
            else:
                heartbeat_metric_job(self.job_id, worker_id=self.worker_id, lease_seconds=self.lease_seconds)
            _save_channel_heartbeat(
                self.channel_id,
                worker_id=self.worker_id,
                status="busy",
                started_at=self.started_at,
                current_job_id=self.job_id,
                current_job_type=self.job_type,
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process scheduled social posts")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--once", action="store_true", help="Run one queue pass and exit")
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_CHANNEL_WORKER_POLL_SECONDS, help="Polling interval in seconds"
    )
    parser.add_argument("--channel-id", default="", help="Optional channel id for targeted channel actions or jobs")
    parser.add_argument(
        "--channel-action",
        choices=["connect", "check_session"],
        default="",
        help="Run a single channel worker action and exit.",
    )
    parser.add_argument(
        "--channel-jobs-only",
        action="store_true",
        help="Process only plugin-backed publish and metrics jobs.",
    )
    parser.add_argument(
        "--channel-action-id", default="", help="Optional claimed action id for one-shot channel actions."
    )
    return parser.parse_args()


def _save_channel_heartbeat(
    channel_id: str,
    *,
    worker_id: str,
    status: str,
    started_at: str,
    current_job_id: str = "",
    current_job_type: str = "",
    last_error: str = "",
) -> WorkerHeartbeat:
    return save_worker_heartbeat(
        WorkerHeartbeat(
            worker_id=worker_id,
            worker_type="channel_worker",
            channel_id=channel_id,
            status=status,
            last_seen_at=now_iso(),
            current_job_id=current_job_id,
            last_error=last_error,
            started_at=started_at,
            current_job_type=current_job_type,
            process_id=os.getpid(),
        )
    )


def _channel_runtime_service(config: AppConfig, channel_id: str):
    runtime = get_plugin_runtime(config, reset=False, strict=True)
    plugin_id = channel_id if channel_id.startswith("channel.") else f"channel.{channel_id}"
    return runtime.get_plugin_service(plugin_id, "channel_runtime")


def run_channel_action(
    config: AppConfig, *, channel_id: str, action: str, action_id: str, worker_id: str, started_at: str
) -> int:
    service = _channel_runtime_service(config, channel_id)
    if action == "connect":
        service.connect(channel_id=channel_id, action_id=action_id, worker_id=worker_id, started_at=started_at)
        return 1
    if action == "check_session":
        if channel_id == "linkedin":
            service.check_session(channel_id=channel_id, worker_id=worker_id, started_at=started_at)
        else:
            service.check_session(channel_account_id=channel_id, worker_id=worker_id, started_at=started_at)
        return 1
    raise ValueError(f"Unsupported channel action: {action}")


def _process_claimed_channel_job(
    config: AppConfig,
    *,
    channel_id: str,
    job_id: str,
    job_type: str,
    worker_id: str,
    started_at: str,
    heartbeat_seconds: int,
    lease_seconds: int,
) -> int:
    service = _channel_runtime_service(config, channel_id)
    keeper = LeaseKeeper(
        channel_id=channel_id,
        worker_id=worker_id,
        job_id=job_id,
        job_type=job_type,
        started_at=started_at,
        heartbeat_seconds=heartbeat_seconds,
        lease_seconds=lease_seconds,
    )
    _save_channel_heartbeat(
        channel_id,
        worker_id=worker_id,
        status="busy",
        started_at=started_at,
        current_job_id=job_id,
        current_job_type=job_type,
    )
    keeper.start()
    try:
        if job_type == "publish":
            service.publish(job_id, worker_id=worker_id, started_at=started_at)
        else:
            service.collect_metrics(job_id, worker_id=worker_id, started_at=started_at)
    finally:
        keeper.stop()
    append_worker_run(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "status": "done",
            "message": f"Processed {job_type} job {job_id} for {channel_id}.",
            "record_id": job_id,
        }
    )
    _save_channel_heartbeat(
        channel_id,
        worker_id=worker_id,
        status="idle",
        started_at=started_at,
    )
    return 1


def process_channel_jobs(
    config: AppConfig,
    channel_id: str | None = None,
    *,
    worker_id: str,
    started_at: str,
    heartbeat_seconds: int,
    lease_seconds: int,
) -> int:
    ensure_channel_store_dirs()
    publish_job = claim_next_publish_job(
        channel_id=channel_id or None, worker_id=worker_id, lease_seconds=lease_seconds
    )
    if publish_job is not None:
        return _process_claimed_channel_job(
            config,
            channel_id=publish_job.channel_id,
            job_id=publish_job.id,
            job_type="publish",
            worker_id=worker_id,
            started_at=started_at,
            heartbeat_seconds=heartbeat_seconds,
            lease_seconds=lease_seconds,
        )

    metric_job = claim_next_metric_job(channel_id=channel_id or None, worker_id=worker_id, lease_seconds=lease_seconds)
    if metric_job is not None:
        return _process_claimed_channel_job(
            config,
            channel_id=metric_job.channel_id,
            job_id=metric_job.id,
            job_type="metrics",
            worker_id=worker_id,
            started_at=started_at,
            heartbeat_seconds=heartbeat_seconds,
            lease_seconds=lease_seconds,
        )
    return 0


def dispatch_due_publication_targets(config: AppConfig, *, worker_id: str) -> int:
    runtime = get_plugin_runtime(config, reset=False, strict=True)
    result = runtime.publication_execution_service(config).dispatch_due_targets(
        batch_size=10,
        dry_run=False,
        worker_id=worker_id,
    )
    return len(result.get("dispatched", []))


def materialize_due_publication_schedules(config: AppConfig) -> int:
    runtime = get_plugin_runtime(config, reset=False, strict=True)
    result = runtime.schedule_materialization_service(config).materialize_due_horizon(
        batch_size=25,
        dry_run=False,
        actor="worker",
    )
    return len(result.get("materialized", []))


def process_queue(config: AppConfig) -> int:
    records = load_schedule()
    due_record = next_due_record(records, datetime.now())
    if not due_record:
        append_worker_run(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "status": "idle",
                "message": "No due queue items.",
            }
        )
        return 0

    record_id = str(due_record["id"])
    image_sources = due_record.get("image_sources", [])
    if not isinstance(image_sources, list):
        image_sources = []
    image_sources = [str(item) for item in image_sources]

    update_schedule_record(
        record_id,
        {
            "status": "processing",
            "processed_at": datetime.now().isoformat(timespec="seconds"),
        },
    )

    downloaded_paths = download_images_from_urls(image_sources, config.media_dir, prefix="scheduled")
    teaser = str(due_record.get("article_teaser", ""))
    article_title = str(due_record.get("article_title", ""))
    article_link = str(due_record.get("article_link", ""))
    article_html = str(due_record.get("article_html", ""))
    article_text = str(due_record.get("article_text", ""))
    source_published_at = due_record.get("source_published_at")
    if source_published_at is not None:
        source_published_at = str(source_published_at)
    content_type = str(due_record.get("content_type", "article"))

    try:
        stage_linkedin_post(
            config,
            teaser,
            downloaded_paths,
            interactive=False,
            article_title=article_title,
            article_link=article_link,
            article_html=article_html,
            article_text=article_text,
            article_published_at=source_published_at,
            content_type=content_type,
        )
        update_schedule_record(
            record_id,
            {
                "status": "done",
                "processed_at": datetime.now().isoformat(timespec="seconds"),
                "result": "staged",
            },
        )
        append_worker_run(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "status": "done",
                "message": f"Staged {content_type} {due_record.get('article_title', 'untitled')} for {due_record.get('platform', '')}.",
                "record_id": record_id,
            }
        )
        return 1
    except Exception as exc:
        update_schedule_record(
            record_id,
            {
                "status": "failed",
                "processed_at": datetime.now().isoformat(timespec="seconds"),
                "result": str(exc),
            },
        )
        append_worker_run(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "status": "failed",
                "message": str(exc),
                "record_id": record_id,
            }
        )
        raise
    finally:
        cleanup_media(config.media_dir, config.cleanup_media_after_run)


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    ensure_runtime_dirs(config)
    ensure_channel_store_dirs()
    get_plugin_runtime(config, reset=True, strict=True)
    heartbeat_seconds = DEFAULT_CHANNEL_WORKER_HEARTBEAT_SECONDS
    lease_seconds = max(DEFAULT_CHANNEL_JOB_LEASE_SECONDS, heartbeat_seconds + 1)
    poll_seconds = max(args.interval, 1)
    target_channel = args.channel_id or "linkedin"
    worker_id = f"{target_channel}:{os.getpid()}"
    started_at = now_iso()
    stop_event = threading.Event()

    def handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        if args.channel_id:
            _save_channel_heartbeat(
                args.channel_id,
                worker_id=worker_id,
                status="starting",
                started_at=started_at,
            )
        if args.channel_action:
            if not args.channel_id:
                raise ValueError("--channel-id is required when --channel-action is used.")
            run_channel_action(
                config,
                channel_id=args.channel_id,
                action=args.channel_action,
                action_id=args.channel_action_id,
                worker_id=worker_id,
                started_at=started_at,
            )
            return 0
        if args.once:
            processed = materialize_due_publication_schedules(config)
            processed += dispatch_due_publication_targets(config, worker_id=worker_id)
            processed += process_channel_jobs(
                config,
                channel_id=args.channel_id or None,
                worker_id=worker_id,
                started_at=started_at,
                heartbeat_seconds=heartbeat_seconds,
                lease_seconds=lease_seconds,
            )
            if processed == 0 and not args.channel_jobs_only:
                process_queue(config)
            return 0

        while not stop_event.is_set():
            if args.channel_id:
                _save_channel_heartbeat(
                    args.channel_id,
                    worker_id=worker_id,
                    status="idle",
                    started_at=started_at,
                )
            processed = materialize_due_publication_schedules(config)
            processed += dispatch_due_publication_targets(config, worker_id=worker_id)
            processed += process_channel_jobs(
                config,
                channel_id=args.channel_id or None,
                worker_id=worker_id,
                started_at=started_at,
                heartbeat_seconds=heartbeat_seconds,
                lease_seconds=lease_seconds,
            )
            if processed == 0 and not args.channel_jobs_only:
                processed = process_queue(config)
            if processed == 0:
                stop_event.wait(poll_seconds)
    finally:
        if args.channel_id:
            _save_channel_heartbeat(
                args.channel_id,
                worker_id=worker_id,
                status="stopping",
                started_at=started_at,
            )
            _save_channel_heartbeat(
                args.channel_id,
                worker_id=worker_id,
                status="offline",
                started_at=started_at,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
