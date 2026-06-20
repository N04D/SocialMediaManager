from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from channel_registry import get_channel_registry_entry
from channel_store import (
    get_channel_connection,
    latest_metric_snapshot_for_post,
    list_channel_job_logs,
    list_derivatives,
    list_publish_jobs,
    list_published_posts,
)
from pipeline import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Report the current LinkedIn channel verification state.')
    parser.add_argument('--config', default='config.json', help='Path to config.json')
    return parser.parse_args()



def line(label: str, state: str, detail: str = '') -> str:
    suffix = f' - {detail}' if detail else ''
    return f'{state:<22} {label}{suffix}'



def main() -> int:
    args = parse_args()
    load_config(args.config)
    entry = get_channel_registry_entry('linkedin')
    if entry is None:
        print(line('Plugin discovered', 'FAIL', 'LinkedIn plugin was not found.'))
        return 1

    derivatives = list_derivatives(channel_id='linkedin')
    approved = next((item for item in derivatives if item.status == 'approved'), None)
    publish_jobs = list_publish_jobs(channel_id='linkedin')
    dry_run_job = next((job for job in publish_jobs if job.run_mode == 'dry_run'), None)
    live_job = next((job for job in publish_jobs if job.run_mode == 'live'), None)
    published_posts = list_published_posts(channel_id='linkedin')
    post = published_posts[0] if published_posts else None
    snapshot = latest_metric_snapshot_for_post(post.id) if post else None
    logs = list_channel_job_logs(channel_id='linkedin', limit=5)
    connection = get_channel_connection('linkedin')

    print(line('Plugin discovered', 'PASS'))
    print(line('Manifest valid', 'PASS' if entry.health != 'invalid_manifest' else 'FAIL', entry.health))
    print(line('Worker online', 'PASS' if entry.worker_status in {'idle', 'busy', 'starting'} else 'FAIL', f'{entry.worker_status} / {entry.worker_last_seen_at or "never"}'))
    print(line('Profile available', 'MANUAL ACTION REQUIRED' if entry.profile_busy else ('PASS' if entry.local_profile_path else 'NOT TESTED'), entry.profile_lock_owner or entry.local_profile_path))
    print(line('Connection verified', 'PASS' if entry.connection_status == 'connected' and entry.last_checked_at else ('FAIL' if entry.connection_status == 'needs_login' else 'NOT TESTED'), entry.last_checked_at or entry.last_error))
    print(line('Approved derivative available', 'PASS' if approved else 'NOT TESTED', approved.id if approved else ''))
    print(line('Dry-run completed', 'PASS' if dry_run_job and dry_run_job.status == 'success' else ('MANUAL ACTION REQUIRED' if dry_run_job and dry_run_job.status not in {'queued', 'running'} else 'NOT TESTED'), dry_run_job.last_step if dry_run_job else ''))
    print(line('Live publish completed', 'PASS' if live_job and live_job.status == 'success' else ('MANUAL ACTION REQUIRED' if live_job and live_job.status == 'manual_verification_required' else 'NOT TESTED'), live_job.last_step if live_job else ''))
    print(line('Published URL known', 'PASS' if post and post.external_url else ('MANUAL ACTION REQUIRED' if post else 'NOT TESTED'), post.external_url if post else ''))
    print(line('Metrics snapshot available', 'PASS' if snapshot else 'NOT TESTED', snapshot.captured_at if snapshot else ''))
    print('\nArtifacts')
    if dry_run_job and dry_run_job.screenshot_path:
        print(f'- latest dry-run screenshot: {dry_run_job.screenshot_path}')
    if live_job and live_job.screenshot_path:
        print(f'- latest live publish screenshot: {live_job.screenshot_path}')
    if snapshot and snapshot.screenshot_path:
        print(f'- latest metrics screenshot: {snapshot.screenshot_path}')
    if logs:
        print('- latest job logs:')
        for record in logs:
            print(f'  - {record.created_at} {record.job_type} {record.status} {record.last_step} {record.error_code or "ok"}')
    else:
        print('- latest job logs: none yet')
    if connection is not None:
        print(f'\nConnection store: {connection.status} / {connection.last_checked_at or "never"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
