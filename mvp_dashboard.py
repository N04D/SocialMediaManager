from __future__ import annotations

import html
import json
import os
import tempfile
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from src.core.alpha_onboarding.api import AlphaOnboardingAPI
from src.core.alpha_onboarding.errors import AlphaOnboardingError
from src.core.alpha_onboarding.service import AlphaOnboardingService
from src.core.alpha_onboarding.steps import STEP_ORDER

CONFIRMATION_TEXT = "Publish this immutable revision using this plan"
FIXED_NOW = "2026-07-31T10:00:00+02:00"
MVP_UI_ROUTES = {
    "/",
    "/home",
    "/setup",
    "/content",
    "/calendar",
    "/analytics",
    "/operations",
}
MVP_DEMO_ROOT = Path(tempfile.gettempdir()) / "socialmediamanager-phase33-demo"
MVP_DATABASE = MVP_DEMO_ROOT / f"alpha-onboarding-{os.getpid()}.sqlite3"


def alpha_ui_service() -> AlphaOnboardingService:
    MVP_DEMO_ROOT.mkdir(parents=True, exist_ok=True)
    return AlphaOnboardingService(database_path=MVP_DATABASE)


def alpha_ui_api() -> AlphaOnboardingAPI:
    return AlphaOnboardingAPI(alpha_ui_service())


def is_mvp_get_route(path: str) -> bool:
    if path in MVP_UI_ROUTES:
        return True
    return path.startswith("/setup/") or (path.startswith("/content/") and path.endswith("/compose"))


def is_mvp_api_route(path: str) -> bool:
    return path == "/api/onboarding" or path.startswith("/api/onboarding/")


def mvp_api_dispatch(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[dict[str, Any], HTTPStatus]:
    try:
        payload = alpha_ui_api().dispatch(method, path, body or {})
    except AlphaOnboardingError as exc:
        return {
            "error": {
                "code": exc.code,
                "message": exc.message,
                "evidence_id": f"phase33-{abs(hash((exc.code, path))) % 100000:05d}",
            }
        }, HTTPStatus(exc.status_code)
    if payload.get("error") == "alpha_onboarding.route_not_found":
        return payload, HTTPStatus.NOT_FOUND
    return payload, HTTPStatus.OK


def handle_mvp_post(
    path: str, form: dict[str, list[str]], json_body: dict[str, Any] | None = None
) -> tuple[str, HTTPStatus]:
    if is_mvp_api_route(path):
        payload, status = mvp_api_dispatch("POST", path, json_body or _flatten_form(form))
        return json.dumps(payload, ensure_ascii=False), status
    service = alpha_ui_service()
    try:
        if path == "/setup/start-demo":
            payload = service.demo_start(actor="demo-operator")
            return _redirect(f"/setup/{payload['session']['id']}")
        if path == "/setup/start":
            workspace_id = _field(form, "workspace_id") or "workspace-alpha-1"
            payload = service.start(
                workspace_id=workspace_id,
                actor=_field(form, "actor") or "alpha-operator",
                idempotency_key=_field(form, "idempotency_key") or workspace_id,
            )
            return _redirect(f"/setup/{payload['session']['id']}")
        if path.startswith("/setup/"):
            parts = [part for part in path.strip("/").split("/") if part]
            session_id = parts[1] if len(parts) > 1 else ""
            action = parts[2] if len(parts) > 2 else ""
            if action == "complete":
                step_id = _field(form, "step_id")
                payload = _step_payload(form)
                service.complete_step(session_id, step_id, payload)
                next_path = _field(form, "next") or f"/setup/{session_id}"
                return _redirect(next_path)
            if action == "skip":
                step_id = _field(form, "step_id")
                service.skip_step(session_id, step_id, _step_payload(form))
                return _redirect(f"/setup/{session_id}")
            if action == "validate":
                step_id = _field(form, "step_id")
                service.validate_step(session_id, step_id, _step_payload(form))
                return _redirect(f"/setup/{session_id}/{step_id}")
            if action == "review":
                service.publication_review(session_id)
                return _redirect(f"/setup/{session_id}/review")
            if action == "confirm":
                service.publication_confirm(
                    session_id,
                    {
                        **_step_payload(form),
                        "confirmation": _field(form, "confirmation"),
                        "idempotency_key": _field(form, "idempotency_key") or f"confirm:{session_id}",
                    },
                )
                return _redirect(f"/setup/{session_id}/publish")
            if action == "sync-analytics":
                service.analytics_sync(session_id)
                return _redirect(f"/setup/{session_id}/funnel")
            if action == "recover":
                finding_id = _field(form, "finding_id")
                service.execute_recovery(session_id, finding_id)
                return _redirect(f"/setup/{session_id}/result")
    except AlphaOnboardingError as exc:
        body = render_error_page(exc.code, exc.message)
        return body, HTTPStatus(exc.status_code)
    return render_error_page(
        "phase33.route_not_found", "The requested dashboard action is not available."
    ), HTTPStatus.NOT_FOUND


def render_mvp_page(path: str, query: str = "") -> tuple[str, HTTPStatus]:
    if is_mvp_api_route(path):
        payload, status = mvp_api_dispatch("GET", path)
        return json.dumps(payload, ensure_ascii=False), status
    service = alpha_ui_service()
    params = parse_qs(query)
    if path in {"/", "/home"}:
        return _layout("Home", "Start dashboard", _render_home(service)), HTTPStatus.OK
    if path == "/setup":
        return _layout("Setup", "Guided setup", _render_setup_index(service)), HTTPStatus.OK
    if path.startswith("/setup/"):
        return _render_setup_route(service, path)
    if path in {"/content", "/content/new"}:
        return _layout("Content", "Write the first article", _render_content_new(service, params)), HTTPStatus.OK
    if path.startswith("/content/") and path.endswith("/compose"):
        return _layout("Compose", "Article composer", _render_composer(service, path, params)), HTTPStatus.OK
    if path == "/calendar":
        return _layout("Calendar", "Publication planning", _render_calendar()), HTTPStatus.OK
    if path == "/analytics":
        return _layout("Analytics", "First funnel status", _render_analytics(service)), HTTPStatus.OK
    if path == "/operations":
        return _layout("Operations", "Operational readiness", _render_operations(service)), HTTPStatus.OK
    return render_error_page(
        "phase33.route_not_found", "The requested dashboard route was not found."
    ), HTTPStatus.NOT_FOUND


def render_error_page(code: str, message: str) -> str:
    safe_code = html.escape(code)
    safe_message = html.escape(message)
    return _layout(
        "Safe Error",
        "The dashboard could not complete that action.",
        f"""
        <section class="panel state-failed" role="alert">
          <h2>Something needs attention</h2>
          <p>{safe_message}</p>
          <dl class="facts"><dt>Safe code</dt><dd>{safe_code}</dd><dt>Evidence ID</dt><dd>phase33-ui</dd></dl>
          <a class="button secondary" href="/home">Return home</a>
        </section>
        """,
    )


def _render_setup_route(service: AlphaOnboardingService, path: str) -> tuple[str, HTTPStatus]:
    parts = [part for part in path.strip("/").split("/") if part]
    session_id = parts[1] if len(parts) > 1 else ""
    try:
        payload = service.get(session_id)
    except AlphaOnboardingError as exc:
        return render_error_page(exc.code, exc.message), HTTPStatus(exc.status_code)
    if len(parts) == 2:
        return _layout("Setup", "Resume the guided setup", _render_wizard(payload)), HTTPStatus.OK
    page = parts[2]
    if page == "review":
        review = service.publication_review(session_id)
        return _layout("Final Review", "Confirm the immutable plan", _render_review(payload, review)), HTTPStatus.OK
    if page == "publish":
        status = service.publication_status(session_id)
        return _layout(
            "Publication Timeline", "Follow durable execution", _render_timeline(payload, status)
        ), HTTPStatus.OK
    if page == "result":
        status = service.publication_status(session_id)
        recovery = service.recovery(session_id)
        return _layout(
            "Publication Result", "Verification and next actions", _render_result(payload, status, recovery)
        ), HTTPStatus.OK
    if page == "funnel":
        funnel = service.funnel(session_id)
        return _layout("First Funnel", "First measurable outcomes", _render_funnel(payload, funnel)), HTTPStatus.OK
    if page in STEP_ORDER:
        step = service.step(session_id, page)
        return _layout(
            step["step"]["display_name"], "Complete this setup step", _render_step(payload, step)
        ), HTTPStatus.OK
    return render_error_page("phase33.route_not_found", "The setup step was not found."), HTTPStatus.NOT_FOUND


def _layout(title: str, subtitle: str, body: str) -> str:
    nav = (
        ("/home", "Home"),
        ("/content", "Content"),
        ("/calendar", "Calendar"),
        ("/analytics", "Analytics"),
        ("/setup", "Setup"),
        ("/operations", "Operations"),
    )
    nav_html = "".join(f'<a href="{href}">{label}</a>' for href, label in nav)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} - SocialMediaManager</title>
  <style>
    :root {{
      --bg:#f7f7f2; --surface:#ffffff; --ink:#202124; --muted:#63645f; --line:#d8d8cf;
      --accent:#0f766e; --accent-dark:#115e59; --warn:#8a5a00; --bad:#9f1239; --ok:#166534;
      --info:#1d4ed8; --soft:#eef6f4; --radius:8px;
    }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background:var(--bg); line-height:1.45; }}
    a {{ color:var(--accent-dark); }}
    .skip-link {{ position:absolute; left:12px; top:8px; transform:translateY(-140%); background:var(--ink); color:white; padding:10px 12px; border-radius:var(--radius); z-index:5; }}
    .skip-link:focus {{ transform:translateY(0); }}
    :focus-visible {{ outline:3px solid #f59e0b; outline-offset:2px; }}
    .shell {{ min-height:100vh; display:grid; grid-template-columns:260px minmax(0,1fr); }}
    aside {{ background:#11201e; color:white; padding:18px; position:sticky; top:0; height:100vh; }}
    .brand {{ font-weight:800; font-size:19px; margin-bottom:18px; }}
    nav {{ display:grid; gap:6px; }}
    nav a {{ color:white; text-decoration:none; padding:11px 12px; border-radius:var(--radius); }}
    nav a:hover, nav a:focus {{ background:rgba(255,255,255,.12); }}
    .workspace {{ margin-top:18px; padding:12px; border:1px solid rgba(255,255,255,.16); border-radius:var(--radius); font-size:13px; color:#d9f4ef; }}
    main {{ min-width:0; }}
    .topbar {{ display:flex; align-items:center; justify-content:space-between; gap:16px; padding:22px 28px; border-bottom:1px solid var(--line); background:rgba(255,255,255,.72); position:sticky; top:0; z-index:2; backdrop-filter:blur(10px); }}
    h1 {{ margin:0; font-size:clamp(26px,3vw,38px); line-height:1.08; }}
    h2 {{ margin:0 0 12px; font-size:22px; }}
    h3 {{ margin:0 0 8px; font-size:17px; }}
    p {{ margin:0 0 12px; }}
    .subtitle {{ color:var(--muted); margin-top:6px; }}
    .wrap {{ padding:24px 28px 42px; max-width:1380px; margin:0 auto; }}
    .grid {{ display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:16px; }}
    .span-12 {{ grid-column:span 12; }} .span-8 {{ grid-column:span 8; }} .span-6 {{ grid-column:span 6; }} .span-4 {{ grid-column:span 4; }} .span-3 {{ grid-column:span 3; }}
    .panel, .card {{ background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); padding:18px; box-shadow:0 1px 2px rgba(0,0,0,.04); }}
    .card {{ min-height:120px; }}
    .button, button {{ display:inline-flex; align-items:center; justify-content:center; min-height:42px; border:0; border-radius:var(--radius); padding:10px 14px; background:var(--accent); color:white; text-decoration:none; font-weight:750; cursor:pointer; }}
    .button.secondary, button.secondary {{ color:var(--ink); background:#e7e5dc; }}
    .button.danger, button.danger {{ background:var(--bad); }}
    button:disabled {{ opacity:.45; cursor:not-allowed; }}
    .actions {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; }}
    .banner {{ padding:12px 14px; border:1px solid #f0c36a; background:#fff8e6; border-radius:var(--radius); color:#5f4100; margin-bottom:16px; }}
    .demo {{ border-color:#7dd3fc; background:#ecfeff; color:#155e75; }}
    .status {{ display:inline-flex; gap:6px; align-items:center; border:1px solid var(--line); border-radius:999px; padding:4px 9px; font-size:13px; font-weight:700; background:#fafafa; }}
    .status.ok {{ color:var(--ok); }} .status.warn {{ color:var(--warn); }} .status.bad {{ color:var(--bad); }} .status.info {{ color:var(--info); }}
    progress {{ width:100%; height:14px; accent-color:var(--accent); }}
    .steps {{ display:grid; gap:8px; }}
    .step-row {{ display:grid; grid-template-columns:minmax(160px,1fr) auto auto; gap:10px; align-items:center; padding:11px; border:1px solid var(--line); border-radius:var(--radius); background:#fbfbf8; }}
    .timeline {{ display:grid; gap:10px; }}
    .timeline li {{ list-style:none; padding:12px 12px 12px 38px; border:1px solid var(--line); border-radius:var(--radius); background:#fbfbf8; position:relative; }}
    .timeline li::before {{ content:""; position:absolute; left:14px; top:17px; width:12px; height:12px; border-radius:50%; background:var(--accent); }}
    form {{ display:grid; gap:12px; }}
    label {{ display:grid; gap:6px; font-weight:700; }}
    input, textarea, select {{ width:100%; border:1px solid var(--line); border-radius:var(--radius); padding:10px 11px; font:inherit; background:white; color:var(--ink); }}
    textarea {{ min-height:220px; resize:vertical; }}
    .field-error {{ color:var(--bad); font-size:13px; }}
    .tabs {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }}
    .tab {{ border:1px solid var(--line); background:#f4f4ed; color:var(--ink); border-radius:999px; padding:7px 10px; font-weight:700; }}
    .preview {{ border:1px solid var(--line); border-radius:var(--radius); padding:14px; background:#fbfbf8; min-height:160px; overflow:auto; }}
    .facts {{ display:grid; grid-template-columns:minmax(120px,220px) minmax(0,1fr); gap:8px 14px; }}
    .facts dt {{ color:var(--muted); }} .facts dd {{ margin:0; overflow-wrap:anywhere; }}
    .sr-live {{ position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }}
    .mobile-nav {{ display:none; padding:10px; background:#11201e; }}
    .mobile-nav select {{ background:white; }}
    @media (max-width: 900px) {{
      .shell {{ display:block; }}
      aside {{ display:none; }}
      .mobile-nav {{ display:block; position:sticky; top:0; z-index:3; }}
      .topbar {{ position:static; padding:18px; }}
      .wrap {{ padding:18px; }}
      .span-8,.span-6,.span-4,.span-3 {{ grid-column:span 12; }}
      .step-row {{ grid-template-columns:1fr; }}
      .facts {{ grid-template-columns:1fr; }}
    }}
    @media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation:none !important; transition:none !important; }} }}
  </style>
</head>
<body>
  <a class="skip-link" href="#main">Skip to main content</a>
  <div class="mobile-nav"><label>Navigation<select onchange="if(this.value) location.href=this.value">{"".join(f'<option value="{href}">{label}</option>' for href, label in (("/home", "Home"), ("/content", "Content"), ("/calendar", "Calendar"), ("/analytics", "Analytics"), ("/setup", "Setup"), ("/operations", "Operations")))}</select></label></div>
  <div class="shell">
    <aside aria-label="Primary navigation"><div class="brand">SocialMediaManager</div><nav>{nav_html}</nav><div class="workspace">Workspace<br><strong>demo-workspace-alpha</strong><br><span>Active status: alpha local</span></div></aside>
    <main id="main">
      <header class="topbar"><div><h1>{html.escape(title)}</h1><p class="subtitle">{html.escape(subtitle)}</p></div><a class="button" href="/setup">Continue setup</a></header>
      <div class="wrap">{body}</div>
    </main>
  </div>
</body>
</html>"""


def _render_home(service: AlphaOnboardingService) -> str:
    status = service.status()
    session = _latest_session(status)
    if session:
        readiness = service.get(session["id"])["readiness"]
        first = service.publication_status(session["id"])["publication"]
        setup_href = f"/setup/{session['id']}"
        result_href = f"/setup/{session['id']}/result"
    else:
        readiness = _empty_readiness()
        first = {}
        setup_href = "/setup"
        result_href = "/setup"
    blockers = readiness.get("blocking_findings") or (
        "External plugin sandbox not certified",
        "Remote CI artifact not imported",
    )
    return f"""
    <section class="banner demo">Demo environment - no external publication</section>
    <section class="grid">
      {_metric_card("Setup status", f"{readiness.get('setup_progress', 0):.0f}%", "Setup progress")}
      {_metric_card("Alpha readiness", _yes_no(readiness.get("alpha_operational_ready")), "Local dogfood path")}
      {_metric_card("Production readiness", _yes_no(readiness.get("production_ready")), "Separate from alpha")}
      {_metric_card("First publication", first.get("verification_status", "not started"), first.get("content_revision_id", "No revision yet"))}
      {_metric_card("Next planned publication", "Not scheduled", "Create a plan after first article")}
      {_metric_card("Channel status", readiness.get("social_ready", "optional"), "Mastodon and LinkedIn optional")}
      {_metric_card("Website account", _ready_label(readiness.get("website_ready")), "Markdown Website")}
      {_metric_card("Analytics", readiness.get("analytics_ready_status", "optional"), "Plausible optional")}
      {_metric_card("Instrumentation", readiness.get("instrumentation_ready_status", "not configured"), "Event mappings")}
      <article class="panel span-8">
        <h2>Open blockers</h2>
        <ul>{"".join(f"<li>{html.escape(str(item))}</li>" for item in blockers)}</ul>
        <p>External plugin sandbox and remote CI import are production blockers, not blockers for normal local alpha publication.</p>
        <div class="actions"><a class="button" href="{setup_href}">Continue setup</a><a class="button secondary" href="/content/new">Create content</a><a class="button secondary" href="{result_href}">View results</a></div>
      </article>
      <article class="panel span-4">
        <h2>Recent funnel results</h2>
        <dl class="facts"><dt>Page views</dt><dd>12 fixture</dd><dt>CTA clicks</dt><dd>3 fixture</dd><dt>Quality</dt><dd>Fresh synthetic data</dd></dl>
      </article>
      <article class="panel span-12">
        <h2>Reconciliation items</h2>
        <p><span class="status warn">needs attention</span> Public URL verification can be checked again without retrying social publication.</p>
      </article>
    </section>
    """


def _render_setup_index(service: AlphaOnboardingService) -> str:
    sessions = service.status()["sessions"]
    rows = "".join(
        f'<li><a href="/setup/{html.escape(item["id"])}">{html.escape(item["workspace_id"])}</a> '
        f'<span class="status info">{html.escape(item["status"])}</span></li>'
        for item in sessions[:6]
    )
    return f"""
    <section class="grid">
      <article class="panel span-8">
        <div class="banner demo">Demo environment - no external publication</div>
        <h2>Start setup</h2>
        <p>Use a guided flow for workspace, Markdown Website, optional analytics, first article, plan, confirmation, verification, and funnel.</p>
        <div class="actions">
          <form method="post" action="/setup/start-demo"><input type="hidden" name="csrf" value="phase33-csrf"><button type="submit">Start demo</button></form>
          <form method="post" action="/setup/start"><input type="hidden" name="csrf" value="phase33-csrf"><input type="hidden" name="idempotency_key" value="real-setup-alpha"><label>Workspace name<input name="workspace_id" value="workspace-alpha-1" required></label><button class="secondary" type="submit">Start real setup</button></form>
        </div>
      </article>
      <article class="panel span-4"><h2>Resume</h2><ul>{rows or "<li>No active sessions yet.</li>"}</ul></article>
    </section>
    """


def _render_wizard(payload: dict[str, Any]) -> str:
    session = payload["session"]
    readiness = payload["readiness"]
    steps_by_section: dict[str, list[dict[str, Any]]] = {}
    for step in payload["steps"]:
        steps_by_section.setdefault(step["section"], []).append(step)
    sections = "".join(
        f'<article class="panel span-6"><h2>{html.escape(section)}</h2><div class="steps">'
        + "".join(_step_row(session, step) for step in steps)
        + "</div></article>"
        for section, steps in steps_by_section.items()
    )
    return f"""
    {_progress_block(readiness)}
    <section class="banner demo">Demo environment - no external publication</section>
    <section class="grid">{sections}</section>
    <section class="panel">
      <h2>Exit and resume</h2>
      <p>This session is durable. Reload or return later using this route.</p>
      <div class="actions"><a class="button" href="/setup/{html.escape(session["id"])}/{html.escape(session["current_step"])}">Continue current step</a><a class="button secondary" href="/home">Exit and resume later</a></div>
    </section>
    """


def _render_step(payload: dict[str, Any], step_payload: dict[str, Any]) -> str:
    session = payload["session"]
    step = step_payload["step"]
    form = _form_for_step(session, step)
    validation = step.get("validation_state") or step.get("validation") or "not run"
    required = "Required" if step["required"] else "Optional"
    return f"""
    {_progress_block(payload["readiness"])}
    <section class="grid">
      <article class="panel span-4">
        <h2>{html.escape(step["display_name"])}</h2>
        <p>{html.escape(_step_explanation(step["step_id"]))}</p>
        <p><span class="status {"bad" if step["required"] else "info"}">{required}</span> <span class="status info">{html.escape(str(validation))}</span></p>
        <dl class="facts"><dt>Status</dt><dd>{html.escape(str(step.get("completion_state", "not started")))}</dd><dt>Blockers</dt><dd>{html.escape(", ".join(payload["readiness"].get("blocking_findings") or ()) or "None for this alpha step")}</dd><dt>Warnings</dt><dd>{html.escape(", ".join(payload["readiness"].get("warning_findings") or ()) or "None")}</dd></dl>
      </article>
      <article class="panel span-8">{form}</article>
    </section>
    """


def _form_for_step(session: dict[str, Any], step: dict[str, Any]) -> str:
    step_id = step["step_id"]
    session_id = session["id"]
    base = f"""
    <input type="hidden" name="csrf" value="phase33-csrf">
    <input type="hidden" name="workspace_id" value="{html.escape(session["workspace_id"])}">
    <input type="hidden" name="expected_version" value="{html.escape(str(session["version"]))}">
    <input type="hidden" name="step_id" value="{html.escape(step_id)}">
    <input type="hidden" name="idempotency_key" value="{html.escape(session_id + ":" + step_id)}">
    """
    fields = {
        "workspace": '<label>Workspace name<input name="workspace_name" value="Demo Workspace" required aria-describedby="workspace-help"></label><p id="workspace-help" class="subtitle">Create or select the workspace users see in the dashboard.</p><label>Timezone<select name="timezone"><option>Europe/Amsterdam</option><option>UTC</option></select></label><label>Default language<select name="language"><option>English</option><option>Dutch</option></select></label>',
        "operator_identity": '<label>Operator role<select name="operator_role"><option>Owner</option><option>Publisher</option><option>Reviewer</option></select></label><label>Operator ID<input name="operator_id" value="operator-alpha-1" required></label>',
        "managed_secrets": '<label>Vault status<select name="vault_status"><option>Temporary encrypted vault</option><option>Existing managed vault</option></select></label><label>Secret reference password<input type="password" name="secret_value" autocomplete="new-password" aria-describedby="secret-help"></label><p id="secret-help" class="subtitle">The value is submitted as a secret reference only and is never rendered back.</p>',
        "website_account": '<label>Account name<input name="account_name" value="Demo Markdown Website" required></label><label>Registered repository<input name="repository_ref" value="fixture-repository" required></label><label>Branch<input name="branch" value="main" required></label><label>Renderer<select name="renderer"><option>Markdown renderer</option></select></label><label>Output root<input name="output_root" value="public/articles"></label><label>Public URL template<input name="public_url_template" value="https://example.invalid/{slug}"></label><label>Publishing mode<select name="publishing_mode"><option>Commit only</option><option>Commit and push</option></select></label>',
        "analytics_account": '<p>Analytics is optional. You can publish without it.</p><label>Plausible site identifier<input name="site_id" value="demo.example.invalid"></label><label>Credential reference<input name="credential_reference" value="credential-ref-demo"></label>',
        "instrumentation": '<label>Instrumentation profile<select name="instrumentation_profile"><option>Fixture web events</option></select></label><label>CTA event mapping<input name="event_mapping" value="cta_click"></label>',
        "social_channels": '<fieldset><legend>Optional social channels</legend><label><input type="checkbox" name="mastodon" checked> Mastodon fixture</label><label><input type="checkbox" name="linkedin" checked> LinkedIn fixture</label></fieldset>',
        "first_content": _composer_fields(),
        "publication_plan": '<p>Website commit -> Optional push -> Public URL verification -> Mastodon publish -> LinkedIn publish -> Analytics collection.</p><label>Schedule<select name="schedule"><option>Now after confirmation</option><option>Later</option></select></label>',
        "final_review": "<p>Review immutable revision, destinations, media, analytics, instrumentation, warnings, and external mutations.</p>",
        "publish": "<p>Publication requires the exact final review confirmation. Refreshing this page will not publish.</p>",
        "verification": "<p>Check public URL verification evidence. Social publication will not be retried automatically when status is uncertain.</p>",
        "analytics_sync": "<p>Sync fixture analytics after website verification. Missing metrics remain explicit statuses, never automatic zeroes.</p>",
        "first_funnel": "<p>Review the first funnel with page views, visitors, CTA clicks, conversions, attribution, freshness, and quality.</p>",
    }.get(step_id, "<p>Review this setup step and save progress.</p>")
    next_step = _next_step_href(session_id, step_id)
    return f"""
    <form method="post" action="/setup/{html.escape(session_id)}/complete">
      {base}
      {fields}
      <div class="actions"><a class="button secondary" href="/setup/{html.escape(session_id)}">Previous</a><button type="submit">Save</button><button type="submit" name="next" value="{html.escape(next_step)}">Next</button><a class="button secondary" href="/home">Exit and resume</a></div>
      <div class="sr-live" aria-live="polite">Saved</div>
    </form>
    """


def _composer_fields() -> str:
    return """
    <div class="grid">
      <label class="span-6">Title<input name="title" value="Synthetic dogfood article" required></label>
      <label class="span-6">Slug<input name="slug" value="synthetic-dogfood-article" required></label>
      <label class="span-12">Markdown editor<textarea name="markdown" required># Synthetic dogfood article

This fixture article proves the MVP dashboard flow without using user-owned drafts.</textarea></label>
      <label class="span-6">SEO description<input name="seo_description" value="Synthetic MVP dashboard fixture."></label>
      <label class="span-6">Tags<input name="tags" value="demo, mvp, phase33"></label>
      <label class="span-4">Author<input name="author" value="Demo Operator"></label>
      <label class="span-4">Language<select name="language"><option>English</option><option>Dutch</option></select></label>
      <label class="span-4">CTA<input name="cta" value="Start the demo flow"></label>
      <label class="span-12">Media alt text<input name="media_alt" value="Abstract fixture cover for a synthetic article"></label>
      <label class="span-4">Website variant<textarea name="website_variant">Long-form website version.</textarea></label>
      <label class="span-4">Mastodon variant<textarea name="mastodon_variant">Short fixture post with link.</textarea></label>
      <label class="span-4">LinkedIn variant<textarea name="linkedin_variant">Professional fixture summary with link.</textarea></label>
    </div>
    """


def _render_content_new(service: AlphaOnboardingService, params: dict[str, list[str]]) -> str:
    return f"""
    <section class="grid">
      <article class="panel span-8"><h2>New article</h2>{_composer_fields()}<div class="actions"><a class="button" href="/content/phase33-fixture/compose">Open composer</a><a class="button secondary" href="/setup">Use in setup</a></div><p class="status ok" aria-live="polite">Saved</p></article>
      <article class="panel span-4"><h2>Empty state</h2><p>No user-owned content is loaded for the MVP demo. Synthetic fixtures are used for previews and screenshots.</p></article>
    </section>
    """


def _render_composer(service: AlphaOnboardingService, path: str, params: dict[str, list[str]]) -> str:
    return f"""
    <section class="grid">
      <article class="panel span-6"><h2>Composer</h2>{_composer_fields()}<p><span class="status info" aria-live="polite">Saved</span> Expected version: 3</p><p class="field-error" id="conflict">Conflict detected: reload to use the latest revision.</p><div class="actions"><a class="button secondary" href="/content/phase33-fixture/compose">Open composer</a></div></article>
      <article class="panel span-6">
        <h2>Preview</h2>
        <div class="tabs"><span class="tab">Website</span><span class="tab">Mastodon</span><span class="tab">LinkedIn</span></div>
        <section class="preview"><h3>Website</h3><p>Rendered synthetic article output with frontmatter, CTA, public URL preview, and instrumentation status.</p><dl class="facts"><dt>Public URL</dt><dd>https://example.invalid/synthetic-dogfood-article</dd><dt>Instrumentation</dt><dd>PASS</dd></dl></section>
        <section class="preview"><h3>Mastodon</h3><p>Short fixture post with link. Limit warning: OK. Media alt text present.</p></section>
        <section class="preview"><h3>LinkedIn</h3><p>Professional fixture summary with canonical link and media description.</p></section>
      </article>
    </section>
    """


def _render_review(payload: dict[str, Any], review: dict[str, Any]) -> str:
    session = payload["session"]
    publication = review["publication"]
    blockers = review.get("known_blockers") or ()
    disabled = (
        "disabled"
        if any("external" not in str(item).lower() and "remote" not in str(item).lower() for item in blockers)
        else ""
    )
    return f"""
    <section class="grid">
      <article class="panel span-8">
        <h2>Final review</h2>
        <dl class="facts"><dt>Immutable revision</dt><dd>{html.escape(publication.get("content_revision_id") or "revision pending")}</dd><dt>Destinations</dt><dd>Markdown Website, Mastodon fixture, LinkedIn fixture</dd><dt>Public URL</dt><dd>{html.escape(publication.get("public_url") or "https://example.invalid/demo-alpha-article")}</dd><dt>External mutations</dt><dd>{html.escape(", ".join(review["mutation_summary"]))}</dd><dt>Media</dt><dd>Synthetic fixture cover with alt text</dd><dt>Analytics</dt><dd>Optional Plausible fixture</dd><dt>Instrumentation</dt><dd>Fixture web events</dd></dl>
      </article>
      <article class="panel span-4">
        <h2>Confirmation</h2>
        <p>Type the exact phrase to create one durable execution request.</p>
        <form method="post" action="/setup/{html.escape(session["id"])}/confirm">
          <input type="hidden" name="csrf" value="phase33-csrf">
          <input type="hidden" name="expected_version" value="{html.escape(str(session["version"]))}">
          <input type="hidden" name="idempotency_key" value="confirm-{html.escape(session["id"])}">
          <label>Exact confirmation<input name="confirmation" aria-describedby="confirm-help" required></label>
          <p id="confirm-help" class="subtitle">{CONFIRMATION_TEXT}</p>
          <button type="submit" {disabled}>{CONFIRMATION_TEXT}</button>
        </form>
      </article>
    </section>
    """


def _render_timeline(payload: dict[str, Any], status: dict[str, Any]) -> str:
    session = payload["session"]
    publication = status["publication"]
    timeline = [
        ("Plan confirmed", "completed" if publication.get("execution_request_id") else "waiting"),
        ("Website execution claimed", "completed" if publication.get("execution_request_id") else "waiting"),
        ("Files staged", "completed" if publication.get("execution_request_id") else "waiting"),
        ("Git commit created", "completed" if publication.get("execution_request_id") else "waiting"),
        ("Push completed", "warning"),
        ("Public URL verified", publication.get("verification_status") or "waiting"),
        ("Mastodon published", "completed"),
        ("LinkedIn published", "completed"),
        ("Analytics pending", publication.get("analytics_sync_status") or "not configured"),
    ]
    rows = "".join(
        f'<li><strong>{html.escape(name)}</strong><br><span class="status info">{html.escape(state)}</span></li>'
        for name, state in timeline
    )
    return f"""
    <section class="panel"><h2>Durable publication timeline</h2><ul class="timeline">{rows}</ul><div class="actions"><a class="button" href="/setup/{html.escape(session["id"])}/result">View result</a><form method="post" action="/setup/{html.escape(session["id"])}/sync-analytics"><button class="secondary" type="submit">Sync analytics</button></form></div></section>
    """


def _render_result(payload: dict[str, Any], status: dict[str, Any], recovery: dict[str, Any]) -> str:
    session = payload["session"]
    publication = status["publication"]
    recoveries = recovery.get("recoveries") or [
        {
            "finding_code": "public_url_pending",
            "explanation": "The public URL could not yet be verified.",
            "safe_actions": ("Check again", "Open deployment status", "View evidence"),
            "blocked_actions": ("Social publication will not be retried automatically.",),
        }
    ]
    recovery_html = "".join(_recovery_card(session["id"], item) for item in recoveries)
    return f"""
    <section class="grid">
      <article class="panel span-8"><h2>Publication result</h2><dl class="facts"><dt>Website URL</dt><dd>{html.escape(publication.get("public_url") or "https://example.invalid/demo-alpha-article")}</dd><dt>Social URLs</dt><dd>Fixture Mastodon URL, fixture LinkedIn URL</dd><dt>Revision</dt><dd>{html.escape(publication.get("content_revision_id") or "revision-alpha")}</dd><dt>Commit reference</dt><dd>fixture-commit-reference</dd><dt>Verification</dt><dd>{html.escape(publication.get("verification_status") or "pending")}</dd><dt>Evidence</dt><dd>{html.escape(", ".join(publication.get("evidence_ids") or ("alpha-evidence-fixture",)))}</dd><dt>Instrumentation</dt><dd>PASS</dd><dt>Analytics</dt><dd>{html.escape(publication.get("analytics_sync_status") or "not configured")}</dd></dl><div class="actions"><a class="button" href="https://example.invalid/demo-alpha-article">View website</a><a class="button secondary" href="/content">View content</a><a class="button secondary" href="/setup/{html.escape(session["id"])}/funnel">View analytics</a><a class="button secondary" href="/content/new">Create next article</a></div></article>
      <aside class="span-4">{recovery_html}</aside>
    </section>
    """


def _render_funnel(payload: dict[str, Any], funnel: dict[str, Any]) -> str:
    metrics = funnel["metrics"]
    cards = "".join(_metric_card(_label(key), str(value), "fixture metric") for key, value in metrics.items())
    return f"""
    <section class="banner demo">Demo environment - no external publication</section>
    <section class="grid">{cards}<article class="panel span-12"><h2>Quality</h2><p>Missing metrics use explicit statuses: Not configured, Not collected, Provider pending, Not observed, Unsupported. They are not converted to zero.</p></article></section>
    """


def _render_analytics(service: AlphaOnboardingService) -> str:
    status = service.status()
    session = _latest_session(status)
    if not session:
        return '<section class="panel"><h2>Analytics</h2><p>Analytics is optional. You can publish without it.</p><a class="button" href="/setup">Start setup</a></section>'
    return _render_funnel(service.get(session["id"]), service.funnel(session["id"]))


def _render_calendar() -> str:
    return """
    <section class="panel"><h2>Publication plan calendar</h2><p>No real schedule is required for the deterministic demo. The first plan is reviewed before any mutation request.</p><ol class="timeline"><li>Website commit</li><li>Optional push</li><li>Public URL verification</li><li>Mastodon publish</li><li>LinkedIn publish</li><li>Analytics collection</li></ol></section>
    """


def _render_operations(service: AlphaOnboardingService) -> str:
    ops = service.operations_dashboard()
    readiness = [
        ("Alpha operational ready", "true" if ops["alpha_ready_workspaces"] else "pending"),
        ("Publishing ready", "pending"),
        ("Analytics ready", "pending" if ops["analytics_setup_incomplete"] else "true"),
        ("CI certification ready", "false"),
        ("External plugin sandbox ready", "false"),
        ("Production ready", "false"),
    ]
    widgets = {
        "Worker health": "idle",
        "Queue depth": "0 fixture jobs",
        "Reconciliation": "needs attention",
        "Storage": "temporary demo database",
        "Backups": "not required for demo",
        "Vault": "temporary encrypted vault",
        "Analytics sync": "provider pending",
        "Current publication": str(ops["first_publications_running"]),
        "Onboarding sessions": str(ops["active_onboarding_sessions"]),
    }
    return f"""
    <section class="grid">
      {"".join(_metric_card(name, value, "readiness") for name, value in readiness)}
      {"".join(_metric_card(name, value, "operations") for name, value in widgets.items())}
    </section>
    """


def _progress_block(readiness: dict[str, Any]) -> str:
    progress = float(readiness.get("setup_progress") or 0)
    return f"""
    <section class="panel" aria-label="Readiness progress">
      <div class="grid">
        <div class="span-4"><h2>Setup progress</h2><progress value="{progress:.0f}" max="100">{progress:.0f}%</progress><p>Setup: {progress:.0f}%</p></div>
        <div class="span-4"><h2>Alpha readiness</h2><p><span class="status {"ok" if readiness.get("alpha_operational_ready") else "warn"}">Alpha ready: {_yes_no(readiness.get("alpha_operational_ready"))}</span></p></div>
        <div class="span-4"><h2>Production readiness</h2><p><span class="status bad">Production ready: {_yes_no(readiness.get("production_ready"))}</span></p><p>External plugin sandbox not certified. Remote CI artifact not imported.</p></div>
      </div>
    </section>
    """


def _step_row(session: dict[str, Any], step: dict[str, Any]) -> str:
    completed = step["step_id"] in session["completed_steps"]
    skipped = step["step_id"] in session["skipped_optional_steps"]
    state = "completed" if completed else "skipped" if skipped else "waiting"
    return f"""
    <div class="step-row">
      <a href="/setup/{html.escape(session["id"])}/{html.escape(step["step_id"])}">{html.escape(step["display_name"])}</a>
      <span class="status {"ok" if completed else "info"}">{state}</span>
      <span class="status {"bad" if step["required"] else "info"}">{"required" if step["required"] else "optional"}</span>
    </div>
    """


def _recovery_card(session_id: str, item: dict[str, Any]) -> str:
    safe_actions = item.get("safe_actions") or ()
    blocked = item.get("blocked_actions") or ()
    finding = item.get("finding_code") or "public_url_pending"
    return f"""
    <article class="panel state-uncertain">
      <h2>Guided recovery</h2>
      <h3>Problem</h3><p>{html.escape(item.get("explanation", "The public URL could not yet be verified."))}</p>
      <h3>What this means</h3><p>The website commit succeeded, but the published page is not visible yet.</p>
      <h3>Safe actions</h3><ul>{"".join(f"<li>{html.escape(str(action))}</li>" for action in safe_actions)}</ul>
      <h3>Blocked action</h3><ul>{"".join(f"<li>{html.escape(str(action))}</li>" for action in blocked)}</ul>
      <form method="post" action="/setup/{html.escape(session_id)}/recover"><input type="hidden" name="finding_id" value="{html.escape(str(finding))}"><button class="secondary" type="submit">Check again</button></form>
    </article>
    """


def _metric_card(title: str, value: str, note: str) -> str:
    return f'<article class="card span-3"><h2>{html.escape(title)}</h2><p class="status info">{html.escape(value)}</p><p class="subtitle">{html.escape(note)}</p></article>'


def _step_payload(form: dict[str, list[str]]) -> dict[str, Any]:
    payload = _flatten_form(form)
    if "secret_value" in payload:
        payload["secret_value"] = "stored-as-managed-reference"
    try:
        payload["expected_version"] = int(str(payload.get("expected_version") or "0"))
    except ValueError:
        payload["expected_version"] = 0
    return payload


def _flatten_form(form: dict[str, list[str]]) -> dict[str, Any]:
    return {key: values[-1] if values else "" for key, values in form.items()}


def _field(form: dict[str, list[str]], key: str) -> str:
    values = form.get(key) or [""]
    return values[-1]


def _redirect(location: str) -> tuple[str, HTTPStatus]:
    return json.dumps({"redirect": location}), HTTPStatus.SEE_OTHER


def _latest_session(status: dict[str, Any]) -> dict[str, Any] | None:
    sessions = status.get("active_sessions") or status.get("sessions") or []
    return sessions[0] if sessions else None


def _empty_readiness() -> dict[str, Any]:
    return {
        "setup_progress": 0,
        "alpha_operational_ready": False,
        "production_ready": False,
        "website_ready": False,
        "social_ready": "optional",
        "analytics_ready_status": "optional",
        "instrumentation_ready_status": "not configured",
    }


def _yes_no(value: Any) -> str:
    return "Yes" if bool(value) else "No"


def _ready_label(value: Any) -> str:
    return "Ready" if bool(value) else "Not configured"


def _label(value: str) -> str:
    return value.replace("_", " ").title().replace("Cta", "CTA")


def _step_explanation(step_id: str) -> str:
    explanations = {
        "welcome": "Understand the local alpha path before external publication is allowed.",
        "host_preflight": "Review host checks with production-only blockers separated.",
        "workspace": "Create or select the workspace context for this setup.",
        "website_account": "Configure Markdown Website without exposing internal enum values.",
        "first_content": "Write the first synthetic article and review channel variants.",
        "publication_plan": "Build the dependency plan before final review.",
        "final_review": "Inspect immutable revision and all external mutations.",
    }
    return explanations.get(step_id, "Save this step using the durable onboarding session.")


def _next_step_href(session_id: str, step_id: str) -> str:
    try:
        next_index = STEP_ORDER.index(step_id) + 1
        return f"/setup/{session_id}/{STEP_ORDER[next_index]}"
    except (ValueError, IndexError):
        return f"/setup/{session_id}/review"
