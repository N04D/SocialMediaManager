from __future__ import annotations

import json
import sys
import types
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import channel_store


@contextmanager
def isolated_channel_store(base_dir: Path) -> Iterator[None]:
    base_dir = base_dir.resolve()
    studio_data_dir = base_dir / "studio_data"
    locks_dir = studio_data_dir / "locks"
    screenshots_dir = base_dir / "outbox" / "channel_screenshots"
    archives_dir = studio_data_dir / "profile_archives"
    path_overrides = {
        "STUDIO_DATA_DIR": studio_data_dir,
        "LOCKS_DIR": locks_dir,
        "CHANNEL_CONNECTIONS_PATH": studio_data_dir / "channel_connections.json",
        "CONTENT_DERIVATIVES_PATH": studio_data_dir / "content_derivatives.json",
        "APPROVALS_PATH": studio_data_dir / "approvals.json",
        "PUBLISH_JOBS_PATH": studio_data_dir / "publish_jobs.json",
        "PUBLISHED_POSTS_PATH": studio_data_dir / "published_posts.json",
        "METRIC_JOBS_PATH": studio_data_dir / "metric_jobs.json",
        "POST_METRIC_SNAPSHOTS_PATH": studio_data_dir / "post_metric_snapshots.json",
        "WORKER_HEARTBEATS_PATH": studio_data_dir / "worker_heartbeats.json",
        "CHANNEL_JOB_LOGS_PATH": studio_data_dir / "channel_job_logs.json",
        "CHANNEL_SCREENSHOTS_DIR": screenshots_dir,
        "PROFILE_ARCHIVE_DIR": archives_dir,
    }
    with ExitStack() as stack:
        for name, value in path_overrides.items():
            stack.enter_context(patch.object(channel_store, name, value))
        yield



def install_pipeline_stub() -> None:
    pipeline_stub = types.ModuleType("pipeline")

    class _AppConfig:
        linkedin_user_data_dir = Path("/tmp/linkedin-profile")
        linkedin_feed_url = "https://www.linkedin.com/feed/"
        linkedin_wait_after_open_seconds = 0.1

    pipeline_stub.AppConfig = _AppConfig
    pipeline_stub.POST_BUTTON_PATTERNS = [r"post"]
    pipeline_stub.run_local_ai = lambda *args, **kwargs: "stubbed derivative"
    pipeline_stub.open_linkedin_session = lambda *args, **kwargs: None
    sys.modules["pipeline"] = pipeline_stub



def build_manifest(
    *,
    channel_id: str,
    name: str | None = None,
    status: str = "planned",
    mode: str = "placeholder",
    can_generate: bool = False,
    can_preview: bool = True,
    can_publish: bool = False,
    can_fetch_metrics: bool = False,
    can_read_comments: bool = False,
    requires_approval: bool = True,
    can_connect: bool = False,
    can_disconnect: bool = False,
    can_check_status: bool = False,
    output_types: list[str] | None = None,
    metrics_mode: str = "none",
) -> dict[str, object]:
    return {
        "id": channel_id,
        "name": name or channel_id.title(),
        "version": "0.1.0",
        "description": f"{name or channel_id.title()} test plugin.",
        "status": status,
        "mode": mode,
        "capabilities": {
            "canGenerate": can_generate,
            "canPreview": can_preview,
            "canPublish": can_publish,
            "canFetchMetrics": can_fetch_metrics,
            "canReadComments": can_read_comments,
            "requiresApproval": requires_approval,
        },
        "connection": {
            "canConnect": can_connect,
            "canDisconnect": can_disconnect,
            "canCheckStatus": can_check_status,
        },
        "outputTypes": output_types or [f"{channel_id}_post"],
        "metrics": {
            "mode": metrics_mode,
            "supportsManualRefresh": can_fetch_metrics,
            "supportsScheduledRefresh": can_fetch_metrics,
            "defaultRefreshWindows": ["1h"] if can_fetch_metrics else [],
        },
    }



def write_plugin(
    channels_dir: Path,
    folder_name: str,
    manifest: dict[str, object],
    *,
    include_readme: bool = True,
    include_rules: bool = False,
    include_worker: bool = False,
    include_prompt: bool = False,
) -> Path:
    plugin_dir = channels_dir / folder_name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "channel.manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    if include_readme:
        (plugin_dir / "README.md").write_text(f"# {manifest['name']}\n", encoding="utf-8")
    if include_rules:
        (plugin_dir / "rules.yaml").write_text("channel: test\n", encoding="utf-8")
    if include_prompt:
        prompts_dir = plugin_dir / "prompts"
        prompts_dir.mkdir(exist_ok=True)
        (prompts_dir / "default.md").write_text("Prompt\n", encoding="utf-8")
    if include_worker:
        worker_dir = plugin_dir / "worker"
        worker_dir.mkdir(exist_ok=True)
        (worker_dir / "index.py").write_text("def noop():\n    return None\n", encoding="utf-8")
    return plugin_dir
