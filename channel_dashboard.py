from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from channel_actions import document_performance, engagement_rate
from channel_registry import ChannelRegistryEntry, get_channel_registry_entry, scan_channel_registry
from channel_store import (
    find_published_post_for_derivative,
    latest_metric_snapshot_for_derivative,
    latest_metric_snapshot_for_post,
    list_channel_job_logs,
    list_derivatives,
    list_metric_jobs,
    list_metric_snapshots,
    list_publish_jobs,
    list_published_posts,
)
from studio_models import ContentItem


def _has_capability(manifest: dict[str, Any], capability_name: str) -> bool:
    capabilities = manifest.get("capabilities", {})
    if isinstance(capabilities, dict):
        return bool(capabilities.get(capability_name))
    elif isinstance(capabilities, (list, tuple, set)):
        return capability_name in capabilities
    return False


def render_channel_checkbox_grid(selected_channels: set[str]) -> str:
    labels: list[str] = []
    for entry in scan_channel_registry():
        manifest = entry.manifest
        if entry.health == "invalid_manifest":
            continue
        checked = "checked" if entry.id in selected_channels else ""
        helper = f"{manifest.get('name', entry.id)} · {entry.health}"
        labels.append(
            f'<label><input type="checkbox" name="channels" value="{html.escape(entry.id)}" {checked} /> '
            f'{html.escape(manifest.get("name", entry.id))}<span class="meta"> {html.escape(helper)}</span></label>'
        )
    if not labels:
        return '<p class="meta">No valid channel plugins discovered yet.</p>'
    return "".join(labels)


def _capability_list(entry: ChannelRegistryEntry) -> str:
    capabilities = entry.manifest.get("capabilities", {})
    items = []
    for key, label in [
        ("canGenerate", "Generate"),
        ("canPreview", "Preview"),
        ("canPublish", "Publish"),
        ("canFetchMetrics", "Metrics"),
        ("canReadComments", "Comments"),
        ("requiresApproval", "Approval required"),
    ]:
        if isinstance(capabilities, dict):
            val = bool(capabilities.get(key))
        elif isinstance(capabilities, (list, tuple, set)):
            val = key in capabilities
        else:
            val = False
        items.append(
            f"<li><strong>{html.escape(label)}</strong>: {html.escape(str(val).lower())}</li>"
        )
    return "".join(items)


def _render_prompt_editor(entry: ChannelRegistryEntry, *, return_to: str) -> str:
    prompt_content = ""
    if entry.id == "linkedin":
        try:
            from channels.linkedin.server.actions import load_prompt_template
            prompt_content = load_prompt_template()
        except Exception:
            prompt_content = ""
    else:
        prompt_path = Path("channels") / entry.id / "prompts" / "linkedin-post.md"
        if prompt_path.exists():
            prompt_content = prompt_path.read_text(encoding="utf-8")

    if not prompt_content and not _has_capability(entry.manifest, "canGenerate"):
        return ""

    return f"""
    <details class="editor-panel">
      <summary class="editor-panel-summary">
        <span class="editor-panel-summary-left"><span>AI Prompt Configuration</span></span>
        <span class="editor-panel-chevron" aria-hidden="true"></span>
      </summary>
      <div class="editor-panel-body">
        <p class="meta">Customize the AI prompt template used to generate derivative posts for {html.escape(str(entry.manifest.get('name', entry.id)))}.</p>
        <form method="post" action="/channels/prompt/save">
          <input type="hidden" name="channel_id" value="{html.escape(entry.id)}" />
          <input type="hidden" name="return_to" value="{html.escape(return_to)}" />
          <label for="prompt-template-{html.escape(entry.id)}">Prompt Template (Markdown & Placeholders)</label>
          <textarea id="prompt-template-{html.escape(entry.id)}" name="prompt_template" class="editor-textarea" style="min-height: 180px; font-family: monospace;">{html.escape(prompt_content)}</textarea>
          <div class="actions" style="margin-top: 10px;">
            <button class="secondary" type="submit">Save AI Prompt</button>
          </div>
        </form>
      </div>
    </details>
    """


def _artifact_link(path_value: str, label: str) -> str:
    if not path_value:
        return ""
    return f'<a class="button secondary" href="/channel-artifact?path={html.escape(path_value)}" target="_blank" rel="noreferrer">{html.escape(label)}</a>'


def _verification_state(label: str, state: str, detail: str = "") -> str:
    detail_markup = f' <span class="meta">{html.escape(detail)}</span>' if detail else ""
    return f"<li><strong>{html.escape(label)}:</strong> <code>{html.escape(state)}</code>{detail_markup}</li>"


def render_channel_verification_panel(channel_id: str, *, return_to: str) -> str:
    entry = get_channel_registry_entry(channel_id)
    if entry is None:
        return ""
    derivatives = list_derivatives(channel_id=channel_id)
    approved = next((item for item in derivatives if item.status == "approved"), None)
    publish_jobs = list_publish_jobs(channel_id=channel_id)
    dry_run_job = next((job for job in publish_jobs if job.run_mode == "dry_run"), None)
    live_job = next((job for job in publish_jobs if job.run_mode == "live"), None)
    published_posts = list_published_posts(channel_id=channel_id)
    published_post = published_posts[0] if published_posts else None
    latest_snapshot = latest_metric_snapshot_for_post(published_post.id) if published_post else None
    latest_job_logs = list_channel_job_logs(channel_id=channel_id, limit=1)
    latest_log = latest_job_logs[0] if latest_job_logs else None
    latest_screenshot = ""
    for candidate in [live_job, dry_run_job]:
        if candidate and candidate.screenshot_path:
            latest_screenshot = candidate.screenshot_path
            break
    if not latest_screenshot and latest_snapshot is not None:
        latest_screenshot = latest_snapshot.screenshot_path

    checks = [
        _verification_state("Plugin discovered", "PASS"),
        _verification_state("Manifest valid", "PASS" if entry.health != "invalid_manifest" else "FAIL", entry.health),
        _verification_state(
            "Worker online",
            "PASS" if entry.worker_status in {"idle", "busy", "starting"} else "FAIL",
            f"{entry.worker_status} · last seen {entry.worker_last_seen_at or 'never'}",
        ),
        _verification_state(
            "Profile available",
            "MANUAL ACTION REQUIRED" if entry.profile_busy else ("PASS" if entry.local_profile_path else "NOT TESTED"),
            entry.profile_lock_owner if entry.profile_busy else entry.local_profile_path,
        ),
        _verification_state(
            "Connection verified",
            "PASS"
            if entry.connection_status == "connected" and bool(entry.last_checked_at)
            else ("FAIL" if entry.connection_status == "needs_login" else "NOT TESTED"),
            entry.last_checked_at or entry.last_error,
        ),
        _verification_state(
            "Approved derivative available", "PASS" if approved else "NOT TESTED", approved.id if approved else ""
        ),
        _verification_state(
            "Dry-run completed",
            "PASS"
            if dry_run_job and dry_run_job.status == "success"
            else (
                "MANUAL ACTION REQUIRED"
                if dry_run_job and dry_run_job.status not in {"queued", "running"}
                else "NOT TESTED"
            ),
            dry_run_job.last_step if dry_run_job else "",
        ),
        _verification_state(
            "Live publish completed",
            "PASS"
            if live_job and live_job.status == "success"
            else (
                "MANUAL ACTION REQUIRED"
                if live_job and live_job.status == "manual_verification_required"
                else "NOT TESTED"
            ),
            live_job.last_step if live_job else "",
        ),
        _verification_state(
            "Published URL known",
            "PASS"
            if published_post and published_post.external_url
            else ("MANUAL ACTION REQUIRED" if published_post else "NOT TESTED"),
            published_post.external_url if published_post else "",
        ),
        _verification_state(
            "Metrics snapshot available",
            "PASS" if latest_snapshot else "NOT TESTED",
            latest_snapshot.captured_at if latest_snapshot else "",
        ),
    ]

    actions: list[str] = []
    if entry.connection_status in {"not_configured", "needs_login", "error"}:
        actions.append(
            f'<form method="post" action="/channels/connect" class="inline-form">'
            f'<input type="hidden" name="channel_id" value="{html.escape(channel_id)}" />'
            f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
            f'<button type="submit">Connect</button></form>'
        )
    if entry.connection_status in {"connected", "needs_login", "error"}:
        actions.append(
            f'<form method="post" action="/channels/check" class="inline-form">'
            f'<input type="hidden" name="channel_id" value="{html.escape(channel_id)}" />'
            f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
            f'<button class="secondary" type="submit">Check session</button></form>'
        )
    if approved is not None:
        actions.append(
            f'<form method="post" action="/publish-jobs/create" class="inline-form">'
            f'<input type="hidden" name="derivative_id" value="{html.escape(approved.id)}" />'
            f'<input type="hidden" name="channel_id" value="{html.escape(channel_id)}" />'
            f'<input type="hidden" name="run_mode" value="dry_run" />'
            f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
            f'<button class="secondary" type="submit">Run dry-run</button></form>'
        )
    if published_post and published_post.external_url:
        actions.append(
            f'<form method="post" action="/metrics/refresh" class="inline-form">'
            f'<input type="hidden" name="published_post_id" value="{html.escape(published_post.id)}" />'
            f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
            f'<button class="secondary" type="submit">Refresh metrics</button></form>'
        )
    if latest_screenshot:
        actions.append(_artifact_link(latest_screenshot, "Open latest screenshot"))
    if latest_log:
        actions.append(
            f'<a class="button secondary" href="/channel-job-log?channel_id={html.escape(channel_id)}" target="_blank" rel="noreferrer">Open latest job log</a>'
        )

    return f"""
    <section class="card">
      <div class="card-heading">
        <div>
          <h2>{html.escape(entry.manifest.get("name", channel_id))} Verification</h2>
          <p class="meta">Actual persisted status for the current LinkedIn vertical slice. Untested steps stay explicitly unverified.</p>
        </div>
      </div>
      <ul>{"".join(checks)}</ul>
      <div class="actions">{"".join(actions) or '<p class="meta">No direct verification actions available yet.</p>'}</div>
    </section>
    """


def render_channel_cards(*, return_to: str) -> str:
    entries = scan_channel_registry()
    cards: list[str] = []
    for entry in entries:
        manifest = entry.manifest
        outputs = ", ".join(manifest.get("outputTypes", [])) or "None"
        error_markup = (
            f'<p class="meta"><strong>Last error:</strong> {html.escape(entry.last_error)}</p>'
            if entry.last_error
            else ""
        )
        health_markup = (
            "".join(f"<li>{html.escape(message)}</li>" for message in entry.errors)
            or "<li>No plugin issues reported.</li>"
        )
        worker_meta = f"{entry.worker_status} · last seen {entry.worker_last_seen_at or 'never'}"
        if entry.worker_current_job_type:
            worker_meta += f" · job {entry.worker_current_job_type}"
        if entry.worker_is_stale:
            worker_meta += " · stale heartbeat"
        profile_meta = ""
        if entry.profile_busy:
            profile_meta = f'<p class="meta"><strong>Profile busy:</strong> {html.escape(entry.profile_lock_owner or "another process is using the persistent profile")}</p>'
        provider_meta = (
            f'<p class="meta">Browser provider: <code>{html.escape(entry.browser_provider_id or "default resolver")}</code></p>'
            f'<form method="post" action="/channels/browser-provider" class="inline-form">'
            f'<input type="hidden" name="channel_id" value="{html.escape(entry.id)}" />'
            f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
            f'<input name="browser_provider_id" list="browser-provider-options" value="{html.escape(entry.browser_provider_id)}" placeholder="blank for default legacy provider" />'
            '<datalist id="browser-provider-options">'
            '<option value="">Default: Legacy Browser</option>'
            '<option value="provider.browser.legacy">Legacy Browser</option>'
            '<option value="provider.browser.autobrowser">Auto Browser</option>'
            "</datalist>"
            f'<button class="secondary" type="submit">Set provider</button></form>'
            '<p class="meta">Auto Browser usually needs one manual reconnect before this account can reuse that provider profile.</p>'
        )
        session_meta = ""
        if entry.browser_session_status or entry.human_takeover_status:
            session_meta = (
                f'<p class="meta">Browser session: <code>{html.escape(entry.browser_session_status or "unknown")}</code>'
                f" · Human takeover: <code>{html.escape(entry.human_takeover_status or 'not_required')}</code></p>"
            )
        pilot_meta = ""
        if entry.id == "linkedin":
            pilot_meta = (
                '<p class="meta">Browser Framework v1 pilot: '
                '<a href="/api/browser-pilots/panel" target="_blank" rel="noreferrer">panel JSON</a>'
                ' · <a href="/api/browser-framework/conformance" target="_blank" rel="noreferrer">conformance</a>'
                ' · <a href="/api/provider-state/history?channel_account_id=linkedin" target="_blank" rel="noreferrer">provider history</a></p>'
            )
        actions: list[str] = []
        auto_profile = entry.auto_browser_auth_profile or {}
        if auto_profile.get("exists"):
            actions.append(
                f'<details class="editor-panel"><summary class="editor-panel-summary">'
                f'<span class="editor-panel-summary-left"><span>Forget Auto Browser login</span></span></summary>'
                f'<p class="meta">Removes only the Auto Browser auth profile for this channel. Legacy login, content, posts, and metrics stay untouched.</p>'
                f'<form method="post" action="/channels/forget-browser-login" class="stacked-form">'
                f'<input type="hidden" name="channel_id" value="{html.escape(entry.id)}" />'
                f'<input type="hidden" name="provider_id" value="provider.browser.autobrowser" />'
                f'<label>Reason <input name="reason" placeholder="Why should this Auto Browser login be removed?" /></label>'
                f'<label>Confirm <input name="confirm_forget_login" placeholder="forget auto browser login" /></label>'
                f'<button class="secondary danger" type="submit">Forget Auto Browser login</button>'
                f"</form></details>"
            )
        if entry.profile_busy:
            lease_warning = (
                "Active lease: verify the browser process before unlocking."
                if not entry.profile_lock_owner.lower().startswith("legacy")
                else "Legacy or stale lock detected."
            )
            actions.append(
                f'<form method="post" action="/channels/force-unlock" class="inline-form">'
                f'<input type="hidden" name="channel_id" value="{html.escape(entry.id)}" />'
                f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
                f'<input name="reason" placeholder="Reason for force unlock" required minlength="8" />'
                f'<label><input type="checkbox" name="confirm_force_unlock" value="yes" required /> Confirm force unlock</label>'
                f'<button class="secondary" type="submit" title="{html.escape(lease_warning)}">Force unlock profile</button></form>'
            )
        if entry.connection_status == "not_configured":
            actions.append(
                f'<form method="post" action="/channels/connect" class="inline-form">'
                f'<input type="hidden" name="channel_id" value="{html.escape(entry.id)}" />'
                f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
                f'<button type="submit">Connect</button></form>'
            )
        elif entry.connection_status == "connecting":
            actions.append('<button type="button" disabled>Connecting...</button>')
        elif entry.connection_status == "connected":
            actions.append(
                f'<form method="post" action="/channels/check" class="inline-form">'
                f'<input type="hidden" name="channel_id" value="{html.escape(entry.id)}" />'
                f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
                f'<button class="secondary" type="submit">Check session</button></form>'
            )
            actions.append(
                f'<form method="post" action="/channels/disconnect" class="inline-form">'
                f'<input type="hidden" name="channel_id" value="{html.escape(entry.id)}" />'
                f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
                f'<button type="submit">Disconnect</button></form>'
            )
        elif entry.connection_status == "needs_login":
            actions.append(
                f'<form method="post" action="/channels/connect" class="inline-form">'
                f'<input type="hidden" name="channel_id" value="{html.escape(entry.id)}" />'
                f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
                f'<button type="submit">Reconnect</button></form>'
            )
            actions.append(
                f'<form method="post" action="/channels/check" class="inline-form">'
                f'<input type="hidden" name="channel_id" value="{html.escape(entry.id)}" />'
                f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
                f'<button class="secondary" type="submit">Check session</button></form>'
            )
        elif entry.connection_status == "error":
            actions.append(
                f'<form method="post" action="/channels/check" class="inline-form">'
                f'<input type="hidden" name="channel_id" value="{html.escape(entry.id)}" />'
                f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
                f'<button type="submit">Retry</button></form>'
            )
        elif entry.connection_status == "disabled":
            actions.append('<button type="button" disabled>Disabled</button>')

        cards.append(
            f"""
            <section class="card">
              <div class="card-heading">
                <div>
                  <h2>{html.escape(manifest.get("name", entry.id))}</h2>
                  <p class="meta">{html.escape(manifest.get("description", ""))}</p>
                </div>
                <span class="summary-pill static"><strong>{html.escape(entry.health)}</strong><span>{html.escape(entry.connection_status)}</span></span>
              </div>
              <p class="meta">Version: <code>{html.escape(manifest.get("version", ""))}</code> · Mode: <code>{html.escape(entry.mode)}</code></p>
              <p class="meta">Outputs: <code>{html.escape(outputs)}</code></p>
              <p class="meta">Worker: <code>{html.escape(worker_meta)}</code></p>
              {provider_meta}
              <p class="meta">Active provider auth: <code>{html.escape(entry.active_provider_connection_status or "unknown")}</code></p>
              <p class="meta">Auto Browser auth profile: <code>{html.escape(str((entry.auto_browser_auth_profile or {}).get("status") or bool((entry.auto_browser_auth_profile or {}).get("exists"))).lower())}</code></p>
              {pilot_meta}
              {session_meta}
              <p class="meta">Last checked: <code>{html.escape(entry.last_checked_at or "never")}</code></p>
              {profile_meta}
              {error_markup}
              <div class="actions">{"".join(actions)}</div>
              <details class="editor-panel">
                <summary class="editor-panel-summary">
                  <span class="editor-panel-summary-left"><span>Capabilities</span></span>
                  <span class="editor-panel-chevron" aria-hidden="true"></span>
                </summary>
                <div class="editor-panel-body">
                  <ul>{_capability_list(entry)}</ul>
                </div>
              </details>
              <details class="editor-panel">
                <summary class="editor-panel-summary">
                  <span class="editor-panel-summary-left"><span>Plugin health</span></span>
                  <span class="editor-panel-chevron" aria-hidden="true"></span>
                </summary>
                <div class="editor-panel-body">
                  <ul>{health_markup}</ul>
                </div>
              </details>
              {_render_prompt_editor(entry, return_to=return_to)}
            </section>
            """
        )
    if not cards:
        cards.append(
            '<section class="card"><h2>Channels</h2><p class="meta">No channel plugins were discovered.</p></section>'
        )
    cards.insert(
        0,
        f'<section class="card compact-card"><div class="card-heading"><div><h2>Channels</h2><p class="meta">Manifest-driven plugin registry with local connection and worker status.</p></div><form method="post" action="/channels/rescan" class="inline-form"><input type="hidden" name="return_to" value="{html.escape(return_to)}" /><button class="secondary" type="submit">Rescan plugins</button></form></div></section>',
    )
    linkedin_panel = render_channel_verification_panel("linkedin", return_to=return_to)
    if linkedin_panel:
        cards.insert(1, linkedin_panel)
    return "".join(cards)


def _render_validation(validation: dict[str, Any]) -> str:
    errors = validation.get("errors", []) if isinstance(validation, dict) else []
    warnings = validation.get("warnings", []) if isinstance(validation, dict) else []
    if not errors and not warnings:
        return '<p class="meta">Validation: no channel rule issues recorded.</p>'
    rows = []
    for error in errors:
        rows.append(f"<li><strong>Error:</strong> {html.escape(str(error))}</li>")
    for warning in warnings:
        rows.append(f"<li><strong>Warning:</strong> {html.escape(str(warning))}</li>")
    return f"<ul>{''.join(rows)}</ul>"


def _render_snapshot_history(derivative_id: str) -> str:
    post = find_published_post_for_derivative(derivative_id)
    if post is None:
        return '<p class="meta">No published post is linked yet.</p>'
    snapshots = list_metric_snapshots(post.id)[:8]
    if not snapshots:
        return '<p class="meta">No metric snapshots captured yet.</p>'
    rows = []
    for snapshot in snapshots:
        rows.append(
            "<tr>"
            f"<td>{html.escape(snapshot.captured_at)}</td>"
            f"<td>{html.escape(str(snapshot.impressions) if snapshot.impressions is not None else 'unknown')}</td>"
            f"<td>{html.escape(str(snapshot.views) if snapshot.views is not None else 'unknown')}</td>"
            f"<td>{html.escape(str(snapshot.reactions) if snapshot.reactions is not None else 'unknown')}</td>"
            f"<td>{html.escape(str(snapshot.comments) if snapshot.comments is not None else 'unknown')}</td>"
            f"<td>{html.escape(str(snapshot.reposts) if snapshot.reposts is not None else 'unknown')}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Captured</th><th>Impressions</th><th>Views</th><th>Reactions</th><th>Comments</th><th>Reposts</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _render_job_logs(channel_id: str, derivative_id: str) -> str:
    publish_job_ids = {job.id for job in list_publish_jobs(channel_id=channel_id, derivative_id=derivative_id)}
    post = find_published_post_for_derivative(derivative_id)
    metric_job_ids = {job.id for job in list_metric_jobs(published_post_id=post.id)} if post else set()
    relevant_ids = publish_job_ids | metric_job_ids
    logs = [
        record for record in list_channel_job_logs(channel_id=channel_id, limit=20) if record.job_id in relevant_ids
    ]
    if not logs:
        return '<p class="meta">No job logs recorded for this derivative yet.</p>'
    rows = []
    for record in logs:
        rows.append(
            f"<tr><td>{html.escape(record.job_type)}</td><td>{html.escape(record.status)}</td><td>{html.escape(record.last_step)}</td><td>{html.escape(record.error_code or '—')}</td><td>{html.escape(record.error_message or '—')}</td></tr>"
        )
    return f"<table><thead><tr><th>Type</th><th>Status</th><th>Step</th><th>Error code</th><th>Error</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"


def render_document_performance_panel(source_item: ContentItem) -> str:
    if not source_item.id:
        return ""
    summary = document_performance(source_item.id, channel_id="linkedin")
    engagement = summary.get("engagement_rate")
    engagement_markup = "Not available"
    if engagement is not None:
        engagement_markup = f"{engagement * 100:.2f}% of {html.escape(summary.get('engagement_rate_denominator', ''))}"
    return f"""
    <section class="card">
      <h2>LinkedIn Performance</h2>
      <div class="summary-metrics">
        <div class="summary-pill static"><strong>{html.escape(str(summary.get("derivative_count", 0)))}</strong><span>Derivatives</span></div>
        <div class="summary-pill static"><strong>{html.escape(str(summary.get("published_count", 0)))}</strong><span>Published</span></div>
        <div class="summary-pill static"><strong>{html.escape(str(summary.get("impressions")) if summary.get("impressions") is not None else "unknown")}</strong><span>Impressions</span></div>
        <div class="summary-pill static"><strong>{html.escape(str(summary.get("views")) if summary.get("views") is not None else "unknown")}</strong><span>Views</span></div>
        <div class="summary-pill static"><strong>{html.escape(str(summary.get("reactions")) if summary.get("reactions") is not None else "unknown")}</strong><span>Reactions</span></div>
        <div class="summary-pill static"><strong>{html.escape(str(summary.get("comments")) if summary.get("comments") is not None else "unknown")}</strong><span>Comments</span></div>
        <div class="summary-pill static"><strong>{html.escape(str(summary.get("reposts")) if summary.get("reposts") is not None else "unknown")}</strong><span>Reposts</span></div>
      </div>
      <p class="meta">Latest snapshot: <code>{html.escape(summary.get("latest_snapshot_at") or "never")}</code></p>
      <p class="meta">Engagement rate: <code>{engagement_markup}</code></p>
    </section>
    """


def render_derivatives_panel(source_item: ContentItem, *, return_to: str) -> str:
    entries = {entry.id: entry for entry in scan_channel_registry() if entry.health != "invalid_manifest"}
    if not source_item.id:
        return (
            '<section class="card"><h2>Channel Derivatives</h2>'
            '<p class="meta">Save the canonical document first so derivatives can stay traceable to a source record.</p></section>'
        )

    generate_actions: list[str] = []
    for entry in entries.values():
        manifest = entry.manifest
        if _has_capability(manifest, "canGenerate"):
            output_type = manifest.get("outputTypes", [""])[0]
            generate_actions.append(
                f'<form method="post" action="/derivatives/generate" class="inline-form">'
                f'<input type="hidden" name="content_id" value="{html.escape(source_item.id)}" />'
                f'<input type="hidden" name="channel_id" value="{html.escape(entry.id)}" />'
                f'<input type="hidden" name="output_type" value="{html.escape(output_type)}" />'
                f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
                f'<button class="secondary" type="submit">Generate {html.escape(manifest.get("name", entry.id))} derivative</button></form>'
            )

    derivative_cards: list[str] = []
    for derivative in list_derivatives(source_document_id=source_item.id):
        entry = entries.get(derivative.channel_id)
        if entry is None:
            continue
        validation = {}
        if isinstance(derivative.generation_metadata_json, dict):
            validation = derivative.generation_metadata_json.get("validation", {})
        post = find_published_post_for_derivative(derivative.id)
        latest_snapshot = latest_metric_snapshot_for_derivative(derivative.id)
        latest_publish_job = next(
            (job for job in list_publish_jobs(channel_id=derivative.channel_id, derivative_id=derivative.id)), None
        )
        worker_warning = ""
        if entry.worker_status == "offline":
            worker_warning = '<p class="meta"><strong>Worker offline:</strong> live or metric jobs will stay queued until the worker runs.</p>'
        latest_metrics_markup = '<p class="meta">No metrics captured yet.</p>'
        if latest_snapshot is not None:
            rate, denominator = engagement_rate(latest_snapshot)
            rate_markup = f"{rate * 100:.2f}% of {denominator}" if rate is not None else "n/a"
            latest_metrics_markup = (
                f'<p class="meta">Latest metrics: impressions <code>{html.escape(str(latest_snapshot.impressions) if latest_snapshot.impressions is not None else "unknown")}</code>, '
                f"views <code>{html.escape(str(latest_snapshot.views) if latest_snapshot.views is not None else 'unknown')}</code>, "
                f"reactions <code>{html.escape(str(latest_snapshot.reactions) if latest_snapshot.reactions is not None else 'unknown')}</code>, "
                f"comments <code>{html.escape(str(latest_snapshot.comments) if latest_snapshot.comments is not None else 'unknown')}</code>, "
                f"reposts <code>{html.escape(str(latest_snapshot.reposts) if latest_snapshot.reposts is not None else 'unknown')}</code>, "
                f"captured <code>{html.escape(latest_snapshot.captured_at)}</code>, engagement <code>{html.escape(rate_markup)}</code>.</p>"
            )
        publish_details = ""
        if latest_publish_job is not None:
            publish_details = f'<p class="meta">Latest publish job: <code>{html.escape(latest_publish_job.run_mode)}</code> · <code>{html.escape(latest_publish_job.status)}</code> · step <code>{html.escape(latest_publish_job.last_step or "queued")}</code></p>'
        elif derivative.status == "approved":
            publish_details = '<p class="meta"><strong>Ready to queue:</strong> this approved derivative has no publish job yet. Use Dry run publish before Live publish.</p>'
        publish_actions = ""
        if derivative.status == "approved":
            publish_actions = (
                f'<div class="actions">'
                f'<form method="post" action="/publish-jobs/create" class="inline-form">'
                f'<input type="hidden" name="derivative_id" value="{html.escape(derivative.id)}" />'
                f'<input type="hidden" name="channel_id" value="{html.escape(derivative.channel_id)}" />'
                f'<input type="hidden" name="run_mode" value="dry_run" />'
                f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
                f'<button class="secondary" type="submit">Dry run publish</button></form>'
                f'<form method="post" action="/publish-jobs/create" class="inline-form">'
                f'<input type="hidden" name="derivative_id" value="{html.escape(derivative.id)}" />'
                f'<input type="hidden" name="channel_id" value="{html.escape(derivative.channel_id)}" />'
                f'<input type="hidden" name="run_mode" value="live" />'
                f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
                f'<button type="submit">Live publish</button></form>'
                f"</div>"
            )
        export_actions = (
            f'<div class="actions">'
            f'<button type="button" class="secondary" onclick="navigator.clipboard.writeText(document.getElementById(&quot;derivative-body-{html.escape(derivative.id)}&quot;).value)">Copy to clipboard</button>'
            f'<a class="button secondary" href="/derivatives/export?derivative_id={html.escape(derivative.id)}&format=markdown">Export Markdown</a>'
            f'<a class="button secondary" href="/derivatives/export?derivative_id={html.escape(derivative.id)}&format=text">Export plain text</a>'
            f'<a class="button secondary" href="https://www.linkedin.com/feed/" target="_blank" rel="noreferrer">Open LinkedIn manually</a>'
            f"</div>"
        )
        manual_url_form = (
            f'<form method="post" action="/derivatives/attach-url">'
            f'<input type="hidden" name="derivative_id" value="{html.escape(derivative.id)}" />'
            f'<input type="hidden" name="channel_id" value="{html.escape(derivative.channel_id)}" />'
            f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
            f'<label for="published-url-{html.escape(derivative.id)}">Attach published post URL</label>'
            f'<input id="published-url-{html.escape(derivative.id)}" name="external_url" value="{html.escape(post.external_url if post else "")}" placeholder="https://www.linkedin.com/..." />'
            f'<div class="actions"><button class="secondary" type="submit">Save published URL</button></div></form>'
        )
        refresh_metrics = ""
        if post is not None:
            refresh_metrics = (
                f'<form method="post" action="/metrics/refresh" class="inline-form">'
                f'<input type="hidden" name="published_post_id" value="{html.escape(post.id)}" />'
                f'<input type="hidden" name="return_to" value="{html.escape(return_to)}" />'
                f'<button class="secondary" type="submit">Refresh metrics</button></form>'
            )
        published_link = (
            f'<a class="button secondary" href="{html.escape(post.external_url)}" target="_blank" rel="noreferrer">Open published post</a>'
            if post and post.external_url
            else ""
        )
        screenshot_link = _artifact_link(
            latest_publish_job.screenshot_path if latest_publish_job else "", "Open latest screenshot"
        )
        derivative_cards.append(
            f"""
            <section class="card">
              <div class="card-heading">
                <div>
                  <h3>{html.escape(entry.manifest.get("name", derivative.channel_id))} derivative</h3>
                  <p class="meta">Status: <code>{html.escape(derivative.status)}</code> · Output: <code>{html.escape(derivative.output_type)}</code> · Updated: <code>{html.escape(derivative.updated_at)}</code></p>
                </div>
                <span class="summary-pill static"><strong>{html.escape(entry.connection_status)}</strong><span>{html.escape(entry.worker_status)}</span></span>
              </div>
              {worker_warning}
              {publish_details}
              {latest_metrics_markup}
              <form method="post" action="/derivatives/save">
                <input type="hidden" name="derivative_id" value="{html.escape(derivative.id)}" />
                <input type="hidden" name="return_to" value="{html.escape(return_to)}" />
                <label for="derivative-title-{html.escape(derivative.id)}">Derivative title</label>
                <input id="derivative-title-{html.escape(derivative.id)}" name="title" value="{html.escape(derivative.title)}" />
                <label for="derivative-body-{html.escape(derivative.id)}">Derivative body</label>
                <textarea id="derivative-body-{html.escape(derivative.id)}" name="body" class="editor-textarea" style="min-height:260px;">{html.escape(derivative.body)}</textarea>
                <div class="actions">
                  <button type="submit">Save derivative</button>
                  <button class="secondary" type="submit" formaction="/derivatives/review">Send for review</button>
                  <button class="secondary" type="submit" formaction="/derivatives/approve">Approve</button>
                  <button class="secondary" type="submit" formaction="/derivatives/reject">Reject</button>
                  <button class="secondary" type="submit" formaction="/derivatives/return-draft">Return to draft</button>
                </div>
              </form>
              {publish_actions}
              <div class="actions">{refresh_metrics}{published_link}{screenshot_link}</div>
              {export_actions}
              {manual_url_form}
              <details class="editor-panel">
                <summary class="editor-panel-summary"><span class="editor-panel-summary-left"><span>Validation</span></span><span class="editor-panel-chevron" aria-hidden="true"></span></summary>
                <div class="editor-panel-body">{_render_validation(validation)}</div>
              </details>
              <details class="editor-panel">
                <summary class="editor-panel-summary"><span class="editor-panel-summary-left"><span>Snapshot history</span></span><span class="editor-panel-chevron" aria-hidden="true"></span></summary>
                <div class="editor-panel-body">{_render_snapshot_history(derivative.id)}</div>
              </details>
              <details class="editor-panel">
                <summary class="editor-panel-summary"><span class="editor-panel-summary-left"><span>Worker logs</span></span><span class="editor-panel-chevron" aria-hidden="true"></span></summary>
                <div class="editor-panel-body">{_render_job_logs(derivative.channel_id, derivative.id)}</div>
              </details>
            </section>
            """
        )

    if not derivative_cards:
        derivative_cards.append(
            '<section class="card"><p class="meta">No channel derivatives generated for this document yet.</p></section>'
        )

    actions_markup = (
        "".join(generate_actions) or '<p class="meta">No plugins currently support derivative generation.</p>'
    )
    return (
        '<section class="card"><div class="card-heading"><div><h2>Channel Derivatives</h2><p class="meta">Generate, review, approve, publish, and track per-channel outputs from the canonical Markdown source.</p></div></div>'
        f'<div class="actions">{actions_markup}</div></section>' + "".join(derivative_cards)
    )
