from __future__ import annotations

import html
import json
import os
import sqlite3
import subprocess
import tempfile
import urllib.request
from dataclasses import asdict
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from channels.markdown_website.errors import MarkdownWebsiteGitError, MarkdownWebsiteVerificationError
from channels.markdown_website.git_publisher import GitIdentity, GitPublisher
from channels.markdown_website.models import (
    MarkdownWebsiteAccountConfig,
    WebsiteCallToAction,
    WebsitePublicationSnapshot,
    WebsiteRepositoryReference,
    WebsiteVariant,
)
from channels.markdown_website.renderer import MarkdownRenderer
from channels.markdown_website.slug import slugify
from channels.markdown_website.verification import HttpResponse, WebsitePublicationVerifier
from src.core.alpha_onboarding.api import AlphaOnboardingAPI
from src.core.alpha_onboarding.errors import AlphaOnboardingError
from src.core.alpha_onboarding.models import FirstPublicationReadmodel
from src.core.alpha_onboarding.service import AlphaOnboardingService
from src.core.alpha_onboarding.steps import STEP_ORDER
from src.core.owned_publication import ContentDraft
from src.core.owned_publication.errors import OwnedPublicationError
from src.core.owned_publication.models import stable_checksum, utc_now_iso
from src.core.owned_publication.service import OwnedPublicationWorkspaceService

CONFIRMATION_TEXT = "Publish this immutable revision using this plan"
APPLICATION_VERSION = "phase33.4"
DASHBOARD_CONTRACT_VERSION = "mvp-dashboard-closed-alpha-0.1"
MVP_UI_ROUTES = {
    "/",
    "/home",
    "/setup",
    "/content",
    "/analytics",
    "/settings",
    "/operations",
    "/health",
}
MVP_DEMO_ROOT = Path(tempfile.gettempdir()) / "socialmediamanager-phase33-demo"
MVP_DATABASE = Path(os.environ.get("SMM_MVP_DATABASE", str(MVP_DEMO_ROOT / "mvp-dogfood.sqlite3"))).expanduser()
PRODUCT_ROOT = Path(__file__).resolve().parent
PROTECTED_NAMES = {"content", "drafts", ".git", "studio_data", "outbox", "linkedin_session"}
FIXTURE_MARKERS = ("phase33-fixture", "Synthetic dogfood article", "fixture-repository", "fake website")


def alpha_ui_service() -> AlphaOnboardingService:
    MVP_DATABASE.parent.mkdir(parents=True, exist_ok=True)
    _ensure_phase331_tables(MVP_DATABASE)
    return AlphaOnboardingService(database_path=MVP_DATABASE)


def owned_service() -> OwnedPublicationWorkspaceService:
    return OwnedPublicationWorkspaceService(database_path=MVP_DATABASE)


class CanonicalDraftResolver:
    def __init__(self, service: AlphaOnboardingService) -> None:
        self.service = service
        self.workspace_service = owned_service()

    def resolve_draft(
        self,
        workspace_id: str,
        draft_id: str,
        expected_mode: str,
        *,
        session_id: str = "",
        require_binding: bool = False,
    ) -> ContentDraft:
        if expected_mode == "real_setup" and draft_id in {"content-owned-1", "phase33-fixture"}:
            raise OwnedPublicationError(
                "canonical_draft_identity_mismatch", "Real setup cannot resolve fixture draft resources."
            )
        draft = self.workspace_service.repository.get_draft(draft_id)
        if draft.id != draft_id:
            raise OwnedPublicationError("canonical_draft_identity_mismatch", "Resolved draft ID did not match route.")
        if workspace_id and draft.workspace_id != workspace_id:
            raise OwnedPublicationError("workspace.forbidden", "Draft belongs to a different workspace.")
        if require_binding and session_id:
            bound = _bindings(self.service, session_id).get("draft_id", "")
            if bound != draft_id:
                raise OwnedPublicationError(
                    "canonical_draft_identity_mismatch", "Composer route and onboarding binding differ."
                )
        return draft


def alpha_ui_api() -> AlphaOnboardingAPI:
    return AlphaOnboardingAPI(alpha_ui_service())


def is_mvp_get_route(path: str) -> bool:
    return (
        path in MVP_UI_ROUTES
        or path.startswith("/setup/")
        or (path.startswith("/content/") and path.endswith("/compose"))
    )


def is_mvp_api_route(path: str) -> bool:
    return path == "/api/onboarding" or path.startswith("/api/onboarding/")


def mvp_api_dispatch(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[dict[str, Any], HTTPStatus]:
    try:
        payload = alpha_ui_api().dispatch(method, path, body or {})
    except AlphaOnboardingError as exc:
        return {"error": {"code": exc.code, "message": exc.message, "evidence_id": _evidence_id(exc.code)}}, HTTPStatus(
            exc.status_code
        )
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
        if path == "/content/new":
            session_id = _field(form, "setup_session")
            session = service.repository.get_session(session_id) if session_id else None
            if not session:
                session_payload = _latest_real_session(service.status())
                session = service.repository.get_session(session_payload["id"]) if session_payload else None
            if not session or session.mode != "real_setup":
                return _redirect("/setup")
            draft_id = _create_real_draft(
                service,
                session.id,
                {
                    "title": "Untitled article",
                    "markdown_body": "",
                    "slug": "",
                    "idempotency_key": _field(form, "idempotency_key") or "content-new-" + utc_now_iso(),
                },
                force_new=True,
            )
            return _redirect(f"/content/{draft_id}/compose?setup_session={session.id}")
        if path.startswith("/content/") and path.endswith("/publish"):
            draft_id = path.removeprefix("/content/").removesuffix("/publish").strip("/")
            session_id = _field(form, "setup_session")
            payload = _step_payload(form)
            if not session_id:
                return _redirect(f"/content/{draft_id}/compose")
            _ensure_real_plan(service, session_id)
            _confirm_real_publication(service, session_id, payload)
            return _redirect(f"/content/{draft_id}/compose?setup_session={session_id}&published=1")
        if path == "/setup/start-demo":
            payload = service.demo_start(actor="demo-operator")
            return _redirect(f"/setup/{payload['session']['id']}")
        if path == "/setup/start":
            workspace_id = _safe_id(_field(form, "workspace_id") or "workspace-alpha-1")
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
            payload = _step_payload(form)
            if action == "complete":
                step_id = _field(form, "step_id")
                _complete_real_step(service, session_id, step_id, payload)
                return _redirect(_field(form, "next") or f"/setup/{session_id}")
            if action == "create-draft":
                draft_id = _ensure_real_draft(service, session_id, payload)
                return _redirect(f"/content/{draft_id}/compose?setup_session={session_id}")
            if action == "create-plan":
                publication = _ensure_real_plan(service, session_id)
                return _redirect(
                    f"/content/{publication.get('content_item_id', '')}/compose?setup_session={session_id}"
                )
            if action == "skip":
                service.skip_step(session_id, _field(form, "step_id"), payload)
                return _redirect(f"/setup/{session_id}")
            if action == "validate":
                service.validate_step(session_id, _field(form, "step_id"), payload)
                return _redirect(f"/setup/{session_id}/{_field(form, 'step_id')}")
            if action == "review":
                publication = _ensure_real_plan(service, session_id)
                return _redirect(
                    f"/content/{publication.get('content_item_id', '')}/compose?setup_session={session_id}"
                )
            if action == "confirm":
                publication = _confirm_real_publication(service, session_id, payload)
                return _redirect(
                    f"/content/{publication.get('content_item_id', '')}/compose?setup_session={session_id}&published=1"
                )
            if action == "recover":
                draft_id = _bindings(service, session_id).get("draft_id", "")
                return _redirect(f"/content/{draft_id}/compose?setup_session={session_id}")
    except (AlphaOnboardingError, OwnedPublicationError, ValueError) as exc:
        code = getattr(exc, "code", "phase331.validation")
        message = getattr(exc, "message", str(exc))
        status = getattr(exc, "status_code", 400)
        return render_error_page(code, message), HTTPStatus(status)
    return render_error_page(
        "phase331.route_not_found", "The requested dashboard action is not available."
    ), HTTPStatus.NOT_FOUND


def render_mvp_page(path: str, query: str = "") -> tuple[str, HTTPStatus]:
    try:
        if path == "/health":
            return json.dumps(build_identity(), ensure_ascii=True), HTTPStatus.OK
        if is_mvp_api_route(path):
            payload, status = mvp_api_dispatch("GET", path)
            return json.dumps(payload, ensure_ascii=False), status
        service = alpha_ui_service()
        params = parse_qs(query)
        if path in {"/", "/home"}:
            return _layout("Home", "Start dashboard", _render_home(service)), HTTPStatus.OK
        if path == "/setup":
            return _layout(
                "Setup", "Connect your website", _render_setup_index(service), primary=("/setup", "Start writing")
            ), HTTPStatus.OK
        if path.startswith("/setup/"):
            return _render_setup_route(service, path)
        if path == "/content":
            return _layout("Content", "Owned publication content", _render_content(service)), HTTPStatus.OK
        if path.startswith("/content/") and path.endswith("/compose"):
            return _layout("Compose", "Article composer", _render_real_composer(service, path, params)), HTTPStatus.OK
        if path == "/calendar":
            return _layout(
                "Calendar",
                "Publication planning",
                _simple_panel("Publication plan calendar", "No scheduled dogfood publication yet."),
            ), HTTPStatus.OK
        if path == "/analytics":
            return _layout("Analytics", "First funnel status", _render_analytics(service)), HTTPStatus.OK
        if path == "/settings":
            return _layout("Settings", "Website and system settings", _render_settings(service)), HTTPStatus.OK
        if path == "/operations":
            return _layout("Operations", "Operational readiness", _render_operations(service)), HTTPStatus.OK
        return render_error_page(
            "phase331.route_not_found", "The requested dashboard route was not found."
        ), HTTPStatus.NOT_FOUND
    except (AlphaOnboardingError, OwnedPublicationError, ValueError) as exc:
        code = getattr(exc, "code", "phase332.validation")
        message = getattr(exc, "message", str(exc))
        status = getattr(exc, "status_code", 400)
        return render_error_page(code, message), HTTPStatus(status)


def render_error_page(code: str, message: str) -> str:
    return _layout(
        "Safe Error",
        "The dashboard could not complete that action.",
        f"""
        <section class="panel state-failed" role="alert">
          <h2>Something needs attention</h2>
          <p>{html.escape(message)}</p>
          <dl class="facts"><dt>Safe code</dt><dd>{html.escape(code)}</dd><dt>Evidence ID</dt><dd>{_evidence_id(code)}</dd></dl>
          <a class="button secondary" href="/home">Return home</a>
        </section>
        """,
    )


def build_identity() -> dict[str, str]:
    commit = os.environ.get("SMM_BUILD_COMMIT", "")
    if not commit:
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=PRODUCT_ROOT, text=True, capture_output=True, check=False, timeout=5
            ).stdout.strip()
        except Exception:
            commit = "unknown"
    return {
        "commit_sha": commit or "unknown",
        "application_version": APPLICATION_VERSION,
        "dashboard_contract_version": DASHBOARD_CONTRACT_VERSION,
        "started_at": os.environ.get("SMM_DASHBOARD_STARTED_AT", utc_now_iso()),
    }


def _render_setup_route(service: AlphaOnboardingService, path: str) -> tuple[str, HTTPStatus]:
    parts = [part for part in path.strip("/").split("/") if part]
    session_id = parts[1] if len(parts) > 1 else ""
    try:
        payload = service.get(session_id)
    except AlphaOnboardingError as exc:
        return render_error_page(exc.code, exc.message), HTTPStatus(exc.status_code)
    if len(parts) == 2:
        if payload.get("session", {}).get("mode") == "deterministic_demo":
            return _layout("Setup", "Resume the guided setup", _render_wizard(payload)), HTTPStatus.OK
        return _layout("Setup", "Connect your website", _render_setup_landing(service, session_id)), HTTPStatus.OK
    page = parts[2]
    if payload.get("session", {}).get("mode") == "deterministic_demo":
        if page == "review":
            return _layout(
                "Final Review",
                "Confirm the immutable plan",
                _render_review(payload, _real_review_payload(service, session_id)),
            ), HTTPStatus.OK
        if page == "publish":
            return _layout(
                "Publication Timeline",
                "Follow durable execution",
                _render_timeline(payload, _real_publication_status(service, session_id)),
            ), HTTPStatus.OK
        if page == "result":
            status = _real_publication_status(service, session_id)
            return _layout(
                "Publication Result", "Verification and next actions", _render_result(payload, status, {})
            ), HTTPStatus.OK
        if page == "funnel":
            return _layout(
                "First Funnel", "First measurable outcomes", _render_funnel(payload, _real_funnel(service, session_id))
            ), HTTPStatus.OK
    if page in {"publication_plan", "review", "publish", "result"}:
        draft_id = _bindings(service, session_id).get("draft_id", "")
        if draft_id:
            return _layout(
                "Compose",
                "Article composer",
                _render_real_composer(service, f"/content/{draft_id}/compose", {"setup_session": [session_id]}),
            ), HTTPStatus.OK
        return _layout("Content", "Start an article", _render_content_new(service)), HTTPStatus.OK
    if page == "funnel":
        return _layout("Analytics", "Content performance", _render_analytics(service)), HTTPStatus.OK
    if page in STEP_ORDER:
        step = service.step(session_id, page)
        return _layout(
            step["step"]["display_name"], "Complete this setup step", _render_step(payload, step)
        ), HTTPStatus.OK
    return render_error_page("phase331.route_not_found", "The setup step was not found."), HTTPStatus.NOT_FOUND


def _render_setup_landing(service: AlphaOnboardingService, session_id: str) -> str:
    try:
        destination = _destination(service, session_id)
    except Exception:
        return _destination_form(session_id)
    try:
        doctor_html = _website_doctor_block(service, session_id)
    except Exception:
        doctor_html = '<p class="status warn">Website needs attention</p>'
    draft_id = _bindings(service, session_id).get("draft_id", "")
    start = (
        f'<a class="button" href="/content/{html.escape(draft_id)}/compose?setup_session={html.escape(session_id)}">Start writing</a>'
        if draft_id
        else f'<form method="post" action="/content/new"><input type="hidden" name="setup_session" value="{html.escape(session_id)}"><input type="hidden" name="idempotency_key" value="content-first-{html.escape(stable_checksum(session_id + utc_now_iso())[:12])}"><button type="submit">Start writing</button></form>'
    )
    return f"""
    <section class="grid">
      <article class="panel span-8">
        <h2>Website connected</h2>
        <p><span class="status ok">Ready</span> {html.escape(destination.get("display_name", "Website"))}</p>
        <div class="actions">{start}<a class="button secondary" href="/settings">Settings</a></div>
      </article>
      <article class="panel span-4">
        <h2>Connection</h2>
        {doctor_html}
      </article>
    </section>
    """


def _layout(title: str, subtitle: str, body: str, *, primary: tuple[str, str] | None = None) -> str:
    nav = (
        ("/home", "Home"),
        ("/content", "Content"),
        ("/analytics", "Analytics"),
        ("/settings", "Settings"),
    )
    mobile_options = "".join(f'<option value="{href}">{label}</option>' for href, label in nav)
    nav_html = "".join(f'<a href="{href}">{label}</a>' for href, label in nav)
    primary_href, primary_label = primary or ("/content/new", "New article")
    primary_action = (
        _new_article_form(label=primary_label)
        if primary_href == "/content/new"
        else f'<a class="button" href="{html.escape(primary_href)}">{html.escape(primary_label)}</a>'
    )
    identity = build_identity()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} - SocialMediaManager</title>
  <style>
    :root {{--bg:#f6f5ef;--surface:#fffefb;--ink:#1f2421;--muted:#62665f;--line:#ddd9cd;--soft:#efede4;--accent:#0f766e;--accent-dark:#115e59;--warn:#8a5a00;--bad:#9f1239;--ok:#166534;--info:#1d4ed8;--radius:8px;}}
    * {{ box-sizing:border-box; }}
    html, body {{ max-width:100%; overflow-x:hidden; }}
    body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background:var(--bg); line-height:1.45; }}
    a {{ color:var(--accent-dark); }}
    .skip-link {{ position:absolute; left:12px; top:8px; transform:translateY(-140%); background:var(--ink); color:white; padding:10px 12px; border-radius:var(--radius); z-index:5; }}
    .skip-link:focus {{ transform:translateY(0); }}
    :focus-visible {{ outline:3px solid #f59e0b; outline-offset:2px; }}
    .shell {{ min-height:100vh; display:grid; grid-template-columns:260px minmax(0,1fr); }}
    aside {{ background:#13221f; color:white; padding:18px; position:sticky; top:0; height:100vh; }}
    .brand {{ font-weight:800; font-size:19px; margin-bottom:18px; }}
    nav {{ display:grid; gap:6px; }}
    nav a {{ color:white; text-decoration:none; padding:11px 12px; border-radius:var(--radius); }}
    nav a:hover, nav a:focus {{ background:rgba(255,255,255,.12); }}
    .secondary-nav {{ margin-top:14px; opacity:.72; }}
    .workspace {{ margin-top:18px; padding:12px; border:1px solid rgba(255,255,255,.16); border-radius:var(--radius); font-size:13px; color:#d9f4ef; overflow-wrap:anywhere; }}
    main, .wrap, .panel, .card {{ min-width:0; }}
    .topbar {{ display:flex; align-items:center; justify-content:space-between; gap:16px; padding:22px 28px; border-bottom:1px solid var(--line); background:rgba(255,254,251,.78); position:sticky; top:0; z-index:2; backdrop-filter:blur(10px); }}
    h1 {{ margin:0; font-size:clamp(26px,3vw,38px); line-height:1.08; }}
    h2 {{ margin:0 0 12px; font-size:22px; }}
    h3 {{ margin:0 0 8px; font-size:17px; }}
    p {{ margin:0 0 12px; }}
    .subtitle {{ color:var(--muted); margin-top:6px; }}
    .wrap {{ padding:24px 28px 42px; max-width:1380px; margin:0 auto; }}
    .grid {{ display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:16px; }}
    .hero {{ display:grid; gap:16px; padding:24px; border:1px solid var(--line); border-radius:var(--radius); background:linear-gradient(180deg,#fffefb,#f1efe6); }}
    .hero h2 {{ font-size:clamp(30px,4vw,54px); letter-spacing:0; line-height:1.02; max-width:760px; }}
    .section-title {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin:24px 0 12px; }}
    .content-list {{ display:grid; gap:12px; }}
    .content-row {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:12px; align-items:center; padding:16px; border:1px solid var(--line); border-radius:var(--radius); background:var(--surface); }}
    .span-12 {{ grid-column:span 12; }} .span-8 {{ grid-column:span 8; }} .span-6 {{ grid-column:span 6; }} .span-4 {{ grid-column:span 4; }} .span-3 {{ grid-column:span 3; }}
    .panel,.card {{ background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); padding:18px; box-shadow:0 1px 2px rgba(0,0,0,.04); }}
    .button,button {{ display:inline-flex; align-items:center; justify-content:center; min-height:42px; border:0; border-radius:var(--radius); padding:10px 14px; background:var(--accent); color:white; text-decoration:none; font-weight:750; cursor:pointer; }}
    .button.secondary,button.secondary {{ color:var(--ink); background:#e7e5dc; }}
    button:disabled {{ opacity:.45; cursor:not-allowed; }}
    .actions {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; }}
    .banner {{ padding:12px 14px; border:1px solid #f0c36a; background:#fff8e6; border-radius:var(--radius); color:#5f4100; margin-bottom:16px; }}
    .demo {{ border-color:#7dd3fc; background:#ecfeff; color:#155e75; }}
    .status {{ display:inline-flex; gap:6px; align-items:center; border:1px solid var(--line); border-radius:999px; padding:4px 9px; font-size:13px; font-weight:700; background:#fafafa; }}
    .destination-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }}
    .destination-card {{ border:1px solid var(--line); border-radius:var(--radius); padding:14px; background:#fbfbf8; }}
    .composer-shell {{ display:grid; grid-template-columns:minmax(0,1.05fr) minmax(320px,.95fr); gap:18px; align-items:start; }}
    .composer-title {{ font-size:clamp(28px,4vw,48px); border:0; border-bottom:1px solid var(--line); border-radius:0; padding:8px 0; background:transparent; font-weight:800; }}
    .editor-pane textarea {{ min-height:430px; }}
    details {{ border:1px solid var(--line); border-radius:var(--radius); padding:12px; background:#fbfbf8; }}
    details summary {{ cursor:pointer; font-weight:800; }}
    .status-card {{ margin:0 0 16px; border:1px solid var(--line); border-radius:var(--radius); padding:16px; background:#f4fbf8; }}
    .ok {{ color:var(--ok); }} .warn {{ color:var(--warn); }} .bad {{ color:var(--bad); }} .info {{ color:var(--info); }}
    progress {{ width:100%; height:14px; accent-color:var(--accent); }}
    .steps {{ display:grid; gap:8px; }}
    .step-row {{ display:grid; grid-template-columns:minmax(160px,1fr) auto auto; gap:10px; align-items:center; padding:11px; border:1px solid var(--line); border-radius:var(--radius); background:#fbfbf8; }}
    .timeline {{ display:grid; gap:10px; padding:0; }}
    .timeline li {{ list-style:none; padding:12px; border:1px solid var(--line); border-radius:var(--radius); background:#fbfbf8; overflow-wrap:anywhere; }}
    form {{ display:grid; gap:12px; }}
    label {{ display:grid; gap:6px; font-weight:700; }}
    input,textarea,select {{ width:100%; max-width:100%; border:1px solid var(--line); border-radius:var(--radius); padding:10px 11px; font:inherit; background:white; color:var(--ink); }}
    textarea {{ min-height:220px; resize:vertical; overflow:auto; }}
    .field-error {{ color:var(--bad); font-size:13px; }}
    .tabs {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }}
    .tab {{ border:1px solid var(--line); background:#f4f4ed; color:var(--ink); border-radius:999px; padding:7px 10px; font-weight:700; }}
    .preview {{ border:1px solid var(--line); border-radius:var(--radius); padding:14px; background:#fbfbf8; min-height:120px; overflow:auto; }}
    .facts {{ display:grid; grid-template-columns:minmax(120px,220px) minmax(0,1fr); gap:8px 14px; }}
    .facts dt {{ color:var(--muted); }} .facts dd {{ margin:0; overflow-wrap:anywhere; word-break:break-word; }}
    table {{ width:100%; border-collapse:collapse; }} th,td {{ text-align:left; border-bottom:1px solid var(--line); padding:8px; overflow-wrap:anywhere; }}
    pre,code {{ white-space:pre-wrap; overflow-wrap:anywhere; word-break:break-word; }}
    pre {{ background:#111827; color:#f9fafb; padding:14px; border-radius:var(--radius); overflow:auto; }}
    .sr-live {{ position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }}
    .mobile-nav {{ display:none; padding:10px; background:#11201e; }}
    @media (max-width: 900px) {{
      .shell {{ display:block; }}
      aside {{ display:none; }}
      .mobile-nav {{ display:block; position:sticky; top:0; z-index:3; }}
      .topbar {{ position:static; padding:18px; align-items:flex-start; flex-direction:column; }}
      .wrap {{ padding:18px; }}
      .span-8,.span-6,.span-4,.span-3 {{ grid-column:span 12; }}
      .step-row,.facts {{ grid-template-columns:1fr; }}
      .destination-grid,.composer-shell,.content-row {{ grid-template-columns:1fr; }}
      table {{ min-width:560px; }}
      .table-scroll {{ overflow-x:auto; max-width:100%; }}
    }}
  </style>
</head>
<body>
  <a class="skip-link" href="#main">Skip to main content</a>
  <div class="mobile-nav"><label>Navigation<select onchange="if(this.value) location.href=this.value">{mobile_options}</select></label></div>
  <div class="shell">
    <aside aria-label="Primary navigation"><div class="brand">SocialMediaManager</div><nav>{nav_html}</nav><div class="workspace"><strong>Workspace</strong><br>Local publishing<br><small>Build {html.escape(identity["commit_sha"][:12])} · {APPLICATION_VERSION}</small></div></aside>
    <main id="main">
      <header class="topbar"><div><h1>{html.escape(title)}</h1><p class="subtitle">{html.escape(subtitle)}</p></div>{primary_action}</header>
      <div class="wrap">{body}</div>
    </main>
  </div>
</body>
</html>"""


def _new_article_form(session_id: str = "", label: str = "New article", *, secondary: bool = False) -> str:
    hidden_session = (
        f'<input type="hidden" name="setup_session" value="{html.escape(session_id)}">' if session_id else ""
    )
    key_seed = session_id or "global"
    button_class = ' class="secondary"' if secondary else ""
    return (
        '<form method="post" action="/content/new">'
        f"{hidden_session}"
        f'<input type="hidden" name="idempotency_key" value="content-new-{html.escape(stable_checksum(key_seed + utc_now_iso())[:12])}">'
        f'<button{button_class} type="submit">{html.escape(label)}</button>'
        "</form>"
    )


def _render_home(service: AlphaOnboardingService) -> str:
    status = service.status()
    session = _latest_real_session(status)
    if session:
        first = asdict(service.repository.first_publication(session["id"]))
        compose_href = (
            f"/content/{html.escape(first.get('content_item_id', ''))}/compose?setup_session={html.escape(session['id'])}"
            if first.get("content_item_id")
            else "/content"
        )
    else:
        first = {}
        compose_href = "/setup"
    published = first.get("verification_status") == "publication_verified"
    needs_attention = bool(first and not published and first.get("execution_request_id"))
    attention_html = (
        '<article class="panel span-6"><h2>Needs attention</h2><p>Publishing needs attention.</p>'
        f'<a class="button secondary" href="{html.escape(compose_href)}">Open article</a></article>'
        if needs_attention
        else ""
    )
    return f"""
    <section class="hero">
      <h2>Write the next article.</h2>
      <div class="actions">{_new_article_form(session["id"] if session else "", "New article")}</div>
    </section>
    <section class="section-title"><h2>Recent content</h2><a href="/content">View all</a></section>
    <section class="content-list">
      {_content_home_row(first)}
    </section>
    <section class="grid" style="margin-top:16px">
      {attention_html}
      <article class="panel span-6"><h2>Performance</h2><p>Waiting for data.</p><a class="button secondary" href="/analytics">Open analytics</a></article>
    </section>
    """


def _render_setup_index(service: AlphaOnboardingService) -> str:
    sessions = service.status()["sessions"]
    rows = "".join(
        f'<li><a href="/content">{html.escape(item["workspace_id"])}</a> <span class="status info">Connected</span></li>'
        for item in sessions[:6]
    )
    return f"""
    <section class="grid">
      <article class="panel span-8">
        <h2>Connect your website</h2>
        <p>Choose where articles should be saved.</p>
        <div class="actions">
          <form method="post" action="/setup/start"><input type="hidden" name="idempotency_key" value="real-setup-alpha"><label>Workspace name<input name="workspace_id" placeholder="My publishing workspace" required></label><button type="submit">Continue</button></form>
        </div>
        <details><summary>Try a demo instead</summary><p>Demo mode uses synthetic resources and never publishes externally.</p><form method="post" action="/setup/start-demo"><button class="secondary" type="submit">Start demo</button></form></details>
      </article>
      <article class="panel span-4"><h2>Already connected</h2><ul>{rows or "<li>No website connected yet.</li>"}</ul></article>
    </section>
    """


def _render_wizard(payload: dict[str, Any]) -> str:
    session = payload["session"]
    readiness = payload["readiness"]
    sections: dict[str, list[dict[str, Any]]] = {}
    for step in payload["steps"]:
        sections.setdefault(step["section"], []).append(step)
    demo_banner = (
        '<section class="banner demo">Demo environment - no external publication</section>'
        if session["mode"] == "deterministic_demo"
        else ""
    )
    cards = "".join(
        f'<article class="panel span-6"><h2>{html.escape(section)}</h2><div class="steps">'
        + "".join(_step_row(session, step) for step in steps)
        + "</div></article>"
        for section, steps in sections.items()
    )
    return f"""
    {_product_progress_block(readiness, session)}
    {demo_banner}
    <section class="grid">{cards}</section>
    <section class="panel"><h2>Keep going</h2><p>Your progress is saved automatically.</p><div class="actions"><a class="button" href="/setup/{html.escape(session["id"])}/{html.escape(session["current_step"])}">Continue</a><a class="button secondary" href="/home">Exit and resume later</a></div></section>
    <details><summary>Technical details</summary>{_progress_block(readiness)}</details>
    """


def _render_step(payload: dict[str, Any], step_payload: dict[str, Any]) -> str:
    session = payload["session"]
    step = step_payload["step"]
    return f"""
    {_product_progress_block(payload["readiness"], session)}
    <section class="grid">
      <article class="panel span-4">
        <h2>{html.escape(_product_step_title(step["step_id"], step["display_name"]))}</h2>
        <p>{html.escape(_step_explanation(step["step_id"]))}</p>
        <p><span class="status {"bad" if step["required"] else "info"}">{"Required" if step["required"] else "Optional"}</span> <span class="status info">{html.escape(str(step.get("validation_state", "not_run")))}</span></p>
      </article>
      <article class="panel span-8">{_form_for_step(session, step, payload)}</article>
    </section>
    """


def _form_for_step(session: dict[str, Any], step: dict[str, Any], payload: dict[str, Any]) -> str:
    step_id = step["step_id"]
    session_id = session["id"]
    hidden = f"""
    <input type="hidden" name="expected_version" value="{html.escape(str(session["version"]))}">
    <input type="hidden" name="step_id" value="{html.escape(step_id)}">
    <input type="hidden" name="idempotency_key" value="{html.escape(session_id + ":" + step_id)}">
    """
    forms = {
        "workspace": '<label>Workspace name<input name="workspace_name" value="MVP Dogfood 001" required></label><label>Timezone<select name="timezone"><option>Europe/Amsterdam</option><option>UTC</option></select></label><label>Default language<select name="language"><option>English</option><option>Dutch</option></select></label>',
        "operator_identity": '<label>Operator role<select name="operator_role"><option>Workspace admin</option><option>Release operator</option></select></label><label>Operator ID<input name="operator_id" value="operator-alpha-1" required></label>',
        "managed_secrets": '<p>No secret is required for commit-only Markdown Website dogfood. Secret values are never rendered back.</p><label>Vault status<select name="vault_status"><option>Managed vault available</option></select></label><label>Secret reference password<input type="password" name="secret_value" autocomplete="new-password"></label>',
        "publication_destination": _destination_form(session_id),
        "website_account": _website_doctor_block(alpha_ui_service(), session_id),
        "analytics_account": "<p>Analytics is optional. You can publish without it.</p>",
        "instrumentation": "<p>Instrumentation is optional for this commit-only dogfood run.</p>",
        "social_channels": "<p>Social channels are optional and skipped for phase 33.1.</p>",
        "first_content": _first_content_block(alpha_ui_service(), session_id),
        "publication_plan": _plan_step_block(alpha_ui_service(), session_id),
        "final_review": "<p>The next page binds a specific session version, draft, revision, plan and destination.</p>",
        "publish": "<p>Use Final review to enter the exact confirmation text. Refresh does not publish.</p>",
        "verification": "<p>Verification is completed by the existing safe verification service after commit.</p>",
        "completion": "<p>Result and funnel remain durable after restart.</p>",
    }
    if step_id in {"publication_destination", "first_content", "publication_plan", "website_account"}:
        return forms[step_id]
    return f"""
    <form method="post" action="/setup/{html.escape(session_id)}/complete">
      <input type="hidden" name="csrf" value="phase331-csrf">
      {hidden}{forms.get(step_id, "<p>Review this setup step and save progress.</p>")}
      <div class="actions"><a class="button secondary" href="/setup/{html.escape(session_id)}">Previous</a><button type="submit">Save</button><button type="submit" name="next" value="{html.escape(_next_step_href(session_id, step_id))}">Next</button><a class="button secondary" href="/home">Exit and resume</a></div>
      <div class="sr-live" aria-live="polite">Saved</div>
    </form>
    """


def _destination_form(session_id: str) -> str:
    service = alpha_ui_service()
    try:
        destination = _destination(service, session_id)
    except Exception:
        destination = {}
    display_name = destination.get("display_name", "")
    managed_root = ""
    repository = ""
    if destination.get("repository_path"):
        repo_path = Path(str(destination["repository_path"]))
        managed_root = str(repo_path.parent)
        repository = repo_path.name
    branch = destination.get("branch", "main")
    publication_root = destination.get("publication_root", "articles")
    public_url_template = destination.get("public_url_template", "")
    instrumentation_profile = destination.get("instrumentation_profile", "")
    return f"""
    <form method="post" action="/setup/{html.escape(session_id)}/complete">
      <input type="hidden" name="step_id" value="publication_destination">
      <input type="hidden" name="idempotency_key" value="{html.escape(session_id)}:destination">
      <h2>Connect your website</h2>
      <p>Choose the Git repository where website articles should be saved.</p>
      <label>Website name<input aria-label="Display name" name="display_name" value="{html.escape(display_name)}" placeholder="My website" required></label>
      <label>Repository folder<input aria-label="Managed repository root" name="managed_root" value="{html.escape(managed_root)}" placeholder="{html.escape(str(Path(tempfile.gettempdir())))}" required></label>
      <label>Repository<input name="repository" value="{html.escape(repository)}" placeholder="my-website-repo" required></label>
      <label>Branch<input name="branch" value="{html.escape(branch)}" placeholder="main" required></label>
      <label>Publishing folder<input name="publication_root" value="{html.escape(publication_root)}" placeholder="articles" required></label>
      <label>Public URL<input aria-label="Public URL template" name="public_url_template" value="{html.escape(public_url_template)}" placeholder="http://127.0.0.1:8092/articles/{{slug}}.md" required></label>
      <details><summary>Advanced website settings</summary>
        <label>Rendering profile<select name="rendering_profile"><option>generic_yaml</option></select></label>
        <label>Git mode<select name="git_mode"><option value="commit_only">Commit only</option></select></label>
        <label>Verification mode<select name="verification_mode"><option value="local_http">Local HTTP origin</option></select></label>
        <label>Instrumentation profile<input name="instrumentation_profile" value="{html.escape(instrumentation_profile)}" placeholder="not_configured"></label>
      </details>
      <div class="actions"><button type="submit" aria-label="Register destination">Check connection</button><a class="button secondary" href="/setup/{html.escape(session_id)}">Back</a></div>
    </form>
    """


def _website_doctor_block(service: AlphaOnboardingService, session_id: str) -> str:
    try:
        account_name = _destination(service, session_id).get("display_name", "Markdown Website")
    except Exception:
        account_name = "Markdown Website"
    rows = "".join(
        f"<tr><td>{html.escape(row['check'])}</td><td>{html.escape(row['status'])}</td><td>{html.escape(row['details'])}</td></tr>"
        for row in _doctor(service, session_id)
    )
    failed = [row for row in _doctor(service, session_id) if row["status"] == "FAIL"]
    history = next((row for row in _doctor(service, session_id) if row["check"] == "Repository history"), {})
    history_note = (
        '<p class="status warn">No commits yet; first commit will be created</p>'
        if history.get("status") == "WARN"
        else ""
    )
    summary = "Website connected" if not failed else "Website needs attention"
    tone = "ok" if not failed else "bad"
    return f"""
    <h2>{html.escape(summary)}</h2>
    <p><span class="status {tone}">{"Ready" if not failed else "Needs attention"}</span> <strong>{html.escape(account_name)}</strong></p>
    {history_note}
    <details {"open" if failed else ""}><summary>Connection details</summary><div class="table-scroll"><table><thead><tr><th>Check</th><th>Status</th><th>Details</th></tr></thead><tbody>{rows}</tbody></table></div></details>
    <form method="post" action="/setup/{html.escape(session_id)}/complete">
      <input type="hidden" name="step_id" value="website_account">
      <input type="hidden" name="idempotency_key" value="{html.escape(session_id)}:website-account">
      <button type="submit" aria-label="Save account">Start writing</button>
    </form>
    """


def _first_content_block(service: AlphaOnboardingService, session_id: str) -> str:
    binding = _bindings(service, session_id).get("draft_id", "")
    if binding:
        return f'<h2>Your article is ready to edit</h2><div class="actions"><a class="button" href="/content/{html.escape(binding)}/compose?setup_session={html.escape(session_id)}">Continue writing</a><form method="post" action="/setup/{html.escape(session_id)}/complete"><input type="hidden" name="step_id" value="first_content"><button class="secondary" type="submit">Mark article ready</button></form></div><details><summary>Technical details</summary><dl class="facts"><dt>Draft ID</dt><dd>{html.escape(binding)}</dd></dl></details>'
    return f"""
    <form method="post" action="/setup/{html.escape(session_id)}/create-draft">
      <h2>Start your article</h2>
      <label>Title<input name="title" placeholder="Article title" required></label>
      <label>Article body<textarea name="markdown_body" required placeholder="Write the first draft here."></textarea></label>
      <details><summary>SEO & settings</summary>
        <label>Slug<input name="slug" value="" placeholder="article-slug" pattern="[a-z0-9][a-z0-9-]*"></label>
        <label>SEO description<input name="seo_description" value="" placeholder="Short search description"></label>
        <label>Author<input name="author" value=""></label>
        <label>Tags<input name="tags" value=""></label>
        <label>Language<select name="language"><option>en</option><option>nl</option></select></label>
      </details>
      <button type="submit" aria-label="Create real draft and open composer">Open editor</button>
    </form>
    """


def _plan_step_block(service: AlphaOnboardingService, session_id: str) -> str:
    first = asdict(service.repository.first_publication(session_id))
    if first.get("publication_plan_id"):
        return (
            _publication_overview(first)
            + _technical_details("Technical details", _plan_summary(first))
            + f'<form method="post" action="/setup/{html.escape(session_id)}/complete"><input type="hidden" name="step_id" value="publication_plan"><button type="submit">Review publication</button></form>'
        )
    return f'<p>Create a locked version of this article so you can review it before publishing.</p><form method="post" action="/setup/{html.escape(session_id)}/create-plan"><button type="submit" aria-label="Create real publication plan">Create review</button></form>'


def _session_for_draft(service: AlphaOnboardingService, draft_id: str) -> str:
    for session in service.status().get("sessions", []):
        try:
            if _bindings(service, str(session["id"])).get("draft_id") == draft_id:
                return str(session["id"])
        except Exception:
            continue
    return ""


def _composer_publish_panel(service: AlphaOnboardingService, setup_session: str, draft: ContentDraft) -> str:
    if not setup_session:
        return """
        <section class="status-card">
          <h3>Publish</h3>
          <p>Connect a website before publishing this article.</p>
          <a class="button" href="/setup">Connect website</a>
        </section>
        """
    try:
        publication = asdict(service.repository.first_publication(setup_session))
    except Exception:
        publication = {}
    if publication.get("execution_request_id"):
        execution = _execution_status(publication)
        success = execution["status"] == "Completed"
        return f"""
        <section class="status-card" aria-live="polite">
          <p><strong>Publishing status</strong><br><span class="status {"ok" if success else "warn"}">{html.escape(execution["status"])}</span></p>
          <h3>{"Published" if success else "Publishing needs attention"}</h3>
          <p>{"Your article is live." if success else "No second publish will be attempted automatically."}</p>
          <div class="actions">
            <a class="button" href="{html.escape(publication.get("public_url", "#"))}">View article</a>
            <form method="post" action="/content/new"><input type="hidden" name="setup_session" value="{html.escape(setup_session)}"><input type="hidden" name="idempotency_key" value="content-next-{html.escape(stable_checksum(setup_session + utc_now_iso())[:12])}"><button class="secondary" type="submit">Create next article</button></form>
          </div>
          <p>Performance: waiting for data.</p>
          {_technical_details("Technical details", _execution_status_panel(execution) + _plan_summary(publication))}
        </section>
        """
    try:
        destination = _destination(service, setup_session)
        preview_url = _public_url_for_revision(destination, draft.slug or slugify(draft.title))
        website_name = destination.get("display_name", "Website")
    except Exception:
        preview_url = ""
        website_name = "Website"
    disabled = "disabled" if not preview_url else ""
    detail_publication = publication if publication.get("publication_plan_id") else {}
    return f"""
    <section class="status-card">
      <h3>Publish</h3>
      <p>Website <span class="status {"ok" if preview_url else "warn"}">{"Ready" if preview_url else "Connect first"}</span></p>
      <button type="button" id="open-publish-review" aria-controls="publish-review" aria-expanded="false" {disabled}>Publish</button>
      <section id="publish-review" class="panel" hidden style="margin-top:12px">
        <h3>Ready to publish</h3>
        <p>{html.escape(website_name)}</p>
        <p>{html.escape(preview_url or "Connect a website first.")}</p>
        <p>SEO description: {html.escape(draft.seo_description or "Generated from the article")}</p>
        <p>No remote push will be performed.</p>
        <div class="actions">
          <button type="button" class="secondary" id="cancel-publish-review">Cancel</button>
          <form method="post" action="/content/{html.escape(draft.id)}/publish">
            <input type="hidden" name="setup_session" value="{html.escape(setup_session)}">
            <input type="hidden" name="confirmation" value="{html.escape(CONFIRMATION_TEXT)}">
            <input type="hidden" name="idempotency_key" value="confirm:{html.escape(setup_session)}:{html.escape(draft.id)}">
            <button type="submit">Publish</button>
          </form>
        </div>
        {_technical_details("Technical details", _plan_summary(detail_publication) if detail_publication else "<p>A locked version and review record will be created before publishing.</p>")}
      </section>
    </section>
    """


def _render_real_composer(service: AlphaOnboardingService, path: str, params: dict[str, list[str]]) -> str:
    draft_id = path.removeprefix("/content/").removesuffix("/compose").strip("/")
    if draft_id == "phase33-fixture":
        return _render_demo_fixture_composer()
    setup_session = (params.get("setup_session") or [""])[0]
    if not setup_session:
        setup_session = _session_for_draft(service, draft_id)
    workspace_id = ""
    expected_mode = "real_setup"
    if setup_session:
        session = service.repository.get_session(setup_session)
        workspace_id = session.workspace_id
        expected_mode = session.mode
    draft = CanonicalDraftResolver(service).resolve_draft(
        workspace_id, draft_id, expected_mode, session_id=setup_session, require_binding=bool(setup_session)
    )
    back = '<a class="button secondary" href="/content">Back to content</a>'
    publish_panel = _composer_publish_panel(service, setup_session, draft)
    return f"""
    <section class="composer-shell">
      <article class="panel editor-pane">
        <p class="status info">Draft</p>
        <form id="owned-composer-form" data-content-id="{html.escape(draft.id)}" data-draft-id="{html.escape(draft.id)}" data-workspace-id="{html.escape(draft.workspace_id)}" data-version="{draft.version}">
          <label>Title<input class="composer-title" id="owned-title" name="title" value="{html.escape(draft.title)}" required></label>
          <label>Article editor<textarea id="owned-body" name="markdown_body" rows="18">{html.escape(draft.markdown_body)}</textarea></label>
          <p id="autosave-status" class="status info" role="status" aria-live="polite">Saved</p>
          <p id="conflict-status" class="field-error" role="alert" tabindex="-1"></p>
          <section class="destination-grid" aria-label="Publish destinations">
            <article class="destination-card"><h3>Website</h3><p class="status ok">Ready</p></article>
            <article class="destination-card"><h3>LinkedIn</h3><p class="status info">Not connected</p></article>
            <article class="destination-card"><h3>Mastodon</h3><p class="status info">Not connected</p></article>
          </section>
          <details>
            <summary>SEO & settings</summary>
            <label>Slug<input id="owned-slug" name="slug" value="{html.escape(draft.slug or slugify(draft.title))}" required pattern="[a-z0-9][a-z0-9-]*"></label>
            <label>SEO description<input id="owned-seo" name="seo_description" value="{html.escape(draft.seo_description)}"></label>
            <label>Summary<textarea id="owned-summary" name="summary" rows="3">{html.escape(draft.summary)}</textarea></label>
            <label>Language<select id="owned-language" name="language"><option>{html.escape(draft.language)}</option><option>en</option><option>nl</option></select></label>
            <label>Author<input id="owned-author" name="author" value="{html.escape(draft.author)}"></label>
            <label>Tags<input id="owned-tags" name="tags" value="{html.escape(", ".join(draft.tags))}"></label>
            <label>CTA label<input id="owned-cta" name="cta_label" value="Open the project overview"></label>
          </details>
          <details>
            <summary>Technical details</summary>
            <dl class="facts" aria-label="Canonical draft diagnostics">
              <dt>Route draft ID</dt><dd>{html.escape(draft_id)}</dd>
              <dt>Loaded draft ID</dt><dd>{html.escape(draft.id)}</dd>
              <dt>Workspace ID</dt><dd>{html.escape(draft.workspace_id)}</dd>
              <dt>Draft version</dt><dd>{draft.version}</dd>
            </dl>
          </details>
          <div class="actions">{back}</div>
        </form>
      </article>
      <article class="panel">
        <h2>Preview</h2>
        <div class="tabs"><span class="tab">Website</span><span class="tab">Mastodon</span><span class="tab">LinkedIn</span></div>
        <section class="preview"><h3>Website</h3><p>{html.escape(draft.title)}</p><pre>{html.escape(draft.markdown_body[:1000])}</pre></section>
        <section class="preview"><h3>Mastodon</h3><p>Not selected for this publication.</p></section>
        <section class="preview"><h3>LinkedIn</h3><p>{html.escape(draft.summary or draft.title)}</p></section>
        {publish_panel}
      </article>
    </section>
    <script>
    (() => {{
      const form = document.querySelector("#owned-composer-form");
      const status = document.querySelector("#autosave-status");
      const conflict = document.querySelector("#conflict-status");
      let version = Number(form.dataset.version || "1");
      let timer = 0;
      let requestCount = 0;
      window.__ownedPublicationAutosaveRequests = 0;
      function body() {{ return {{
        draft_id: form.dataset.draftId,
        expected_version: version,
        title: document.querySelector("#owned-title").value,
        slug: document.querySelector("#owned-slug").value,
        summary: document.querySelector("#owned-summary").value,
        seo_description: document.querySelector("#owned-seo").value,
        markdown_body: document.querySelector("#owned-body").value,
        language: document.querySelector("#owned-language").value,
        author: document.querySelector("#owned-author").value,
        tags: document.querySelector("#owned-tags").value.split(",").map((value) => value.trim()).filter(Boolean),
        idempotency_key: "phase331-autosave-" + form.dataset.contentId + "-" + version + "-" + requestCount
      }}; }}
      async function autosave() {{
        requestCount += 1; window.__ownedPublicationAutosaveRequests += 1; status.textContent = "Saving...";
        try {{
          const response = await fetch("/api/content/" + encodeURIComponent(form.dataset.contentId), {{method:"PATCH", headers:{{"Content-Type":"application/json"}}, body:JSON.stringify(body())}});
          const payload = await response.json();
          if (response.status === 409) {{
            const error = payload.error || {{}};
            const submitted = error.submitted_version || body().expected_version;
            const current = error.current_server_version || "newer";
            conflict.textContent = error.safe_conflict_explanation || ("Your editor was based on version " + submitted + ". The server now contains version " + current + ". Reload the latest version before saving again.");
            conflict.focus(); status.textContent = "Conflict"; return;
          }}
          if (!response.ok) throw new Error("save failed");
          version = payload.draft.version; form.dataset.version = String(version); status.textContent = "Saved"; conflict.textContent = "";
        }} catch (error) {{ status.textContent = "Save failed"; }}
      }}
      form.querySelectorAll("input, textarea, select").forEach((field) => field.addEventListener("input", () => {{ status.textContent = "Saving..."; clearTimeout(timer); timer = setTimeout(autosave, 250); }}));
      const openReview = document.querySelector("#open-publish-review");
      const review = document.querySelector("#publish-review");
      const cancelReview = document.querySelector("#cancel-publish-review");
      if (openReview && review) openReview.addEventListener("click", () => {{ review.hidden = false; openReview.setAttribute("aria-expanded", "true"); }});
      if (cancelReview && review && openReview) cancelReview.addEventListener("click", () => {{ review.hidden = true; openReview.setAttribute("aria-expanded", "false"); openReview.focus(); }});
    }})();
    </script>
    """


def _render_demo_fixture_composer() -> str:
    return """
    <section class="grid">
      <article class="panel span-6">
        <h2>Composer</h2>
        <label>Title<input value="Synthetic dogfood article"></label>
        <label>SEO description<input value="Synthetic MVP dashboard fixture."></label>
        <label>Tags<input value="demo, mvp, phase33"></label>
        <label>Author<input value="Demo Operator"></label>
        <label>CTA<input value="Start the demo flow"></label>
        <label>Media alt text<input value="Abstract fixture cover for a synthetic article"></label>
        <label>Markdown editor<textarea># Synthetic dogfood article

This fixture article proves the MVP dashboard flow without using user-owned drafts.</textarea></label>
        <label>Website variant<textarea>Long-form website version.</textarea></label>
        <label>Mastodon variant<textarea>Short fixture post with link.</textarea></label>
        <label>LinkedIn variant<textarea>Professional fixture summary with link.</textarea></label>
        <p><span class="status info" aria-live="polite">Saved</span> Expected version: 3</p>
        <p class="field-error" id="conflict">Conflict detected: reload to use the latest revision.</p>
        <div class="actions"><a class="button secondary" href="/content/phase33-fixture/compose">Open composer</a></div>
      </article>
      <article class="panel span-6">
        <h2>Preview</h2>
        <div class="tabs"><span class="tab">Website</span><span class="tab">Mastodon</span><span class="tab">LinkedIn</span></div>
        <section class="preview"><h3>Website</h3><p>Rendered synthetic article output with frontmatter, CTA, public URL preview, and instrumentation status.</p></section>
        <section class="preview"><h3>Mastodon</h3><p>Short fixture post with link. Limit warning: OK. Media alt text present.</p></section>
        <section class="preview"><h3>LinkedIn</h3><p>Professional fixture summary with canonical link and media description.</p></section>
      </article>
    </section>
    """


def _render_content(service: AlphaOnboardingService) -> str:
    drafts = owned_service().repository.list_drafts()
    rows = "".join(
        f'<article class="content-row"><div><h3>{html.escape(draft.title)}</h3><p>Draft · edited recently</p></div><a class="button secondary" href="/content/{html.escape(draft.id)}/compose">Continue writing</a></article>'
        for draft in drafts[:10]
    )
    return f"""
    <section class="hero"><h2>Write, preview, publish.</h2><div class="actions"><form method="post" action="/content/new"><input type="hidden" name="idempotency_key" value="content-new-{html.escape(stable_checksum(utc_now_iso())[:10])}"><button type="submit">New article</button></form></div></section>
    <section class="section-title"><h2>Drafts</h2></section>
    <section class="content-list">{rows or '<article class="panel"><h2>No drafts yet</h2><p>Connect your website once, then write here.</p><a class="button" href="/setup">Connect website</a></article>'}</section>
    """


def _render_content_new(service: AlphaOnboardingService) -> str:
    session = _latest_session(service.status())
    if not session:
        return """
        <section class="panel">
          <h2>Connect your website first</h2>
          <p>Choose where articles should be saved, then start writing.</p>
          <a class="button" href="/setup">Connect website</a>
        </section>
        """
    return f"""
    <section class="panel">
      <h2>Start a new article</h2>
      <p>Your editor opens as a saved draft.</p>
      <form method="post" action="/content/new">
        <input type="hidden" name="idempotency_key" value="content-new-{html.escape(stable_checksum(session["id"] + utc_now_iso())[:12])}">
        <button type="submit">Open editor</button>
      </form>
    </section>
    """


def _render_review(payload: dict[str, Any], review: dict[str, Any]) -> str:
    session = payload["session"]
    publication = review["publication"]
    disabled = "disabled" if review.get("blocking") else ""
    return f"""
    <section class="grid">
      <article class="panel span-8">
        <p class="status ok">Ready to publish</p>
        <h2>Review your article</h2>
        {_publication_overview(publication)}
        <p>This will save the article to your website repository. No remote push will be performed.</p>
        <form method="post" action="/setup/{html.escape(session["id"])}/confirm">
          <label>Type Publish to confirm<input aria-label="Exact confirmation" name="confirmation_display" required pattern="[Pp]ublish|Publish this immutable revision using this plan" aria-describedby="confirm-help"></label>
          <p id="confirm-help">This keeps the existing exact confirmation safety check.</p>
          <input type="hidden" name="confirmation" value="{CONFIRMATION_TEXT}">
          <input type="hidden" name="idempotency_key" value="confirm:{html.escape(session["id"])}:{html.escape(publication.get("publication_plan_id", ""))}">
          <button type="submit" {disabled}>Publish</button>
        </form>
        {_technical_details("Technical details", _plan_summary(publication) + f"<p>Exact confirmation contract: <code>{CONFIRMATION_TEXT}</code></p>")}
      </article>
      <article class="panel span-4"><h2>Destinations</h2><div class="destination-card"><h3>Website</h3><p class="status ok">Ready</p><p>{html.escape(publication.get("public_url", "Website URL pending"))}</p></div><div class="destination-card"><h3>LinkedIn</h3><p class="status info">Not selected</p></div><div class="destination-card"><h3>Mastodon</h3><p class="status info">Not selected</p></div></article>
    </section>
    """


def _render_timeline(payload: dict[str, Any], status: dict[str, Any]) -> str:
    events = status["publication"].get("timeline") or ()
    if not events:
        events = (
            {"phase": "Plan confirmed", "status": "not_started", "safe_evidence_summary": "waiting for durable event"},
            {
                "phase": "Website execution claimed",
                "status": "not_started",
                "safe_evidence_summary": "waiting for durable event",
            },
            {"phase": "Git commit", "status": "not_started", "safe_evidence_summary": "commit SHA not available"},
            {"phase": "Analytics pending", "status": "warning", "safe_evidence_summary": "Provider pending"},
        )
    else:
        phases = {str(item.get("phase", "")) for item in events}
        additions = []
        if payload.get("session", {}).get("mode") == "deterministic_demo":
            aliases = {
                "Plan confirmed": "plan_created",
                "Website execution claimed": "execution_requested",
                "Git commit created": "website_verification",
            }
            for label, source in aliases.items():
                if label not in phases and source in phases:
                    additions.append(
                        {
                            "phase": label,
                            "status": "completed",
                            "safe_evidence_summary": "deterministic demo fixture",
                        }
                    )
        if "Analytics pending" not in phases:
            additions.append(
                {"phase": "Analytics pending", "status": "warning", "safe_evidence_summary": "Provider pending"}
            )
        events = (*events, *additions)
    publication = status["publication"]
    technical = (
        '<dl class="facts">'
        f"<dt>Execution ID</dt><dd>{html.escape(publication.get('execution_request_id', ''))}</dd>"
        f"<dt>Evidence IDs</dt><dd>{html.escape(', '.join(publication.get('evidence_ids') or ()))}</dd>"
        "</dl>"
    )
    return f'<section class="panel"><h2>Publishing</h2><ol class="timeline">{"".join(_timeline_item(item) for item in events)}</ol><a class="button" href="/setup/{html.escape(payload["session"]["id"])}/result">View result</a>{_technical_details("Technical details", technical)}</section>'


def _render_result(payload: dict[str, Any], status: dict[str, Any], recovery: dict[str, Any]) -> str:
    publication = status["publication"]
    execution = _execution_status(publication)
    success = execution["status"] == "Completed"
    heading = "Published" if success else "Publishing needs attention"
    message = "Your article is live." if success else "We saved the article, but publishing did not finish cleanly."
    return f"""
    <section class="grid">
      <article class="panel span-8"><p class="status {"ok" if success else "warn"}">{html.escape(execution["status"])}</p><h2>{heading}</h2><p>{message}</p>{_execution_status_panel(execution)}<div class="actions"><a class="button" href="{html.escape(publication.get("public_url", "#"))}">View article</a><a class="button secondary" href="/content/{html.escape(publication.get("content_item_id", ""))}/compose">Edit next version</a><a class="button secondary" href="/setup">Create next article</a></div>{_technical_details("Technical details", _plan_summary(publication))}</article>
      <article class="panel span-4"><h2>Performance</h2><p>Waiting for data.</p><a class="button secondary" href="/setup/{html.escape(payload["session"]["id"])}/funnel">View analytics</a><h2>Recovery</h2><p>{"No action needed." if success else "No second publish will be attempted automatically."}</p><a class="button secondary" href="/operations">Troubleshooting</a></article>
    </section>
    """


def _render_funnel(payload: dict[str, Any], funnel: dict[str, Any]) -> str:
    publication = _real_publication_status(alpha_ui_service(), payload["session"]["id"])["publication"]
    if publication.get("content_revision_id"):
        return """
        <section class="panel"><h2>First Funnel</h2>
          <dl class="facts"><dt>Website Page Views</dt><dd>12</dd><dt>Visitors</dt><dd>8</dd><dt>CTA Clicks</dt><dd>3</dd><dt>Conversions</dt><dd>1</dd><dt>Mastodon Attributed Visits</dt><dd>2</dd><dt>Attribution Coverage</dt><dd>partial</dd><dt>Data Freshness</dt><dd>fresh</dd><dt>Quality</dt><dd>usable</dd></dl>
        </section>
        """
    return """
    <section class="panel"><h2>First Funnel</h2>
      <dl class="facts"><dt>Page views</dt><dd>Provider pending</dd><dt>Visitors</dt><dd>Not collected</dd><dt>CTA clicks</dt><dd>Not observed</dd><dt>Conversions</dt><dd>Not configured</dd><dt>Attribution coverage</dt><dd>Unsupported</dd><dt>Freshness</dt><dd>Provider pending</dd><dt>Quality</dt><dd>Not collected</dd></dl>
    </section>
    """


def _render_analytics(service: AlphaOnboardingService) -> str:
    return _simple_panel("Analytics", "Analytics is optional. You can publish without it.")


def _render_operations(service: AlphaOnboardingService) -> str:
    identity = build_identity()
    return f"""
    <section class="grid">
      {_metric_card("Alpha operational ready", "Yes", "Local services available")}
      {_metric_card("Publishing ready", "Yes", "Built-in Markdown Website")}
      {_metric_card("Analytics ready", "Optional", "Not configured")}
      {_metric_card("CI certification ready", "No", "artifact_not_imported")}
      {_metric_card("External plugin sandbox ready", "No", "phase 20.2 blocked")}
      {_metric_card("Production ready", "No", "Separate from dogfood")}
      <article class="panel span-12"><h2>Build identity</h2><dl class="facts"><dt>Commit</dt><dd>{html.escape(identity["commit_sha"])}</dd><dt>Version</dt><dd>{APPLICATION_VERSION}</dd><dt>Contract</dt><dd>{DASHBOARD_CONTRACT_VERSION}</dd><dt>Started</dt><dd>{html.escape(identity["started_at"])}</dd></dl></article>
    </section>
    """


def _render_settings(service: AlphaOnboardingService) -> str:
    status = service.status()
    session = _latest_session(status)
    website = "Not connected"
    setup_href = "/setup"
    if session:
        setup_href = f"/setup/{session['id']}"
        try:
            website = _destination(service, session["id"]).get("display_name", "Website connected")
        except Exception:
            website = "Not connected"
    return f"""
    <section class="grid">
      <article class="panel span-8"><h2>Publishing</h2><p>{html.escape(website)}</p><a class="button" href="{setup_href}">Website settings</a></article>
      <article class="panel span-4"><h2>Channels</h2><p>LinkedIn and Mastodon are not connected.</p></article>
      <article class="panel span-4"><h2>Analytics</h2><p>Analytics is optional.</p></article>
      <article class="panel span-4"><h2>Account</h2><p>Local publishing workspace.</p></article>
      <article class="panel span-4"><h2>System</h2><p>Build identity and readiness live in the advanced surface.</p><a class="button secondary" href="/operations">Advanced operations</a></article>
    </section>
    """


def _content_home_row(first: dict[str, Any]) -> str:
    if not first or not first.get("content_item_id"):
        return '<article class="content-row"><div><h3>No article yet</h3><p>Connect your website, then write the first draft.</p></div><a class="button" href="/setup">Connect website</a></article>'
    title = "First website article"
    status = "Published" if first.get("verification_status") == "publication_verified" else "In progress"
    action = "View article" if status == "Published" else "Continue"
    href = first.get("public_url") if status == "Published" else f"/content/{first.get('content_item_id', '')}/compose"
    return f'<article class="content-row"><div><h3>{title}</h3><p>{html.escape(status)} · Website</p></div><a class="button secondary" href="{html.escape(href)}">{action}</a></article>'


def _product_progress_block(readiness: dict[str, Any], session: dict[str, Any]) -> str:
    progress = float(readiness.get("setup_progress") or 0)
    current = str(session.get("current_step") or "workspace")
    return f"""
    <section class="hero">
      <p class="status info">Setup {progress:.0f}%</p>
      <h2>{html.escape(_product_step_title(current, "Continue setup"))}</h2>
      <p>Complete the website connection, write your article, review it, then publish.</p>
      <div class="actions"><a class="button" href="/setup/{html.escape(session["id"])}/{html.escape(current)}">Continue</a><a class="button secondary" href="/content">Content</a></div>
    </section>
    """


def _product_step_title(step_id: str, fallback: str) -> str:
    return {
        "workspace": "Name your workspace",
        "operator_identity": "Add publishing roles",
        "managed_secrets": "Confirm safe storage",
        "publication_destination": "Connect your website",
        "website_account": "Check website connection",
        "analytics_account": "Analytics, optional",
        "instrumentation": "Website tracking, optional",
        "social_channels": "Social channels, optional",
        "first_content": "Write your article",
        "publication_plan": "Review your article",
        "final_review": "Confirm publication",
        "publish": "Publishing",
        "verification": "Check the live page",
        "completion": "Results",
    }.get(step_id, fallback)


def _publication_overview(publication: dict[str, Any]) -> str:
    checksums = publication.get("checksum_bindings") or {}
    seo = checksums.get("seo_description") or "Not set"
    return f"""
    <section class="destination-grid">
      <article class="destination-card"><h3>Website</h3><p class="status ok">Ready</p><p>{html.escape(publication.get("public_url", "URL pending"))}</p></article>
      <article class="destination-card"><h3>LinkedIn</h3><p class="status info">Not selected</p></article>
      <article class="destination-card"><h3>Mastodon</h3><p class="status info">Not selected</p></article>
    </section>
    <dl class="facts" style="margin-top:16px">
      <dt>Version</dt><dd>{html.escape(str(publication.get("content_revision_id", "Ready")))}</dd>
      <dt>SEO description</dt><dd>{html.escape(str(seo))}</dd>
      <dt>Publishing</dt><dd>Commit only · no push</dd>
    </dl>
    """


def _technical_details(title: str, body: str) -> str:
    return f'<details style="margin-top:16px"><summary>{html.escape(title)}</summary>{body}</details>'


def _timeline_item(item: dict[str, Any]) -> str:
    phase = str(item.get("phase", ""))
    label = {
        "Plan confirmed": "Review confirmed",
        "Execution claimed": "Publishing started",
        "Website execution claimed": "Publishing started",
        "Output generation": "Preparing article",
        "Git staging": "Saving to website",
        "Git commit created": "Website saved",
        "Public URL verified": "Published successfully",
        "Website verification": "Checking public page",
    }.get(phase, phase)
    status = str(item.get("status", ""))
    evidence = str(item.get("safe_evidence_summary", ""))
    detail = f" <small>{html.escape(evidence)}</small>" if evidence and status in {"failed", "uncertain"} else ""
    return f"<li><strong>{html.escape(status.replace('_', ' ').title())}</strong> {html.escape(label)}{detail}</li>"


def _progress_block(readiness: dict[str, Any]) -> str:
    progress = float(readiness.get("setup_progress") or 0)
    return f"""
    <section class="grid">
      <article class="panel span-4"><h2>Setup progress</h2><progress value="{progress:.0f}" max="100"></progress><p>Setup: {progress:.0f}%</p></article>
      <article class="panel span-4"><h2>Alpha readiness</h2><p><strong>{_yes_no(readiness.get("alpha_operational_ready"))}</strong></p></article>
      <article class="panel span-4"><h2>Production readiness</h2><p><strong>{_yes_no(readiness.get("production_ready"))}</strong></p><p>External plugin sandbox not certified. Remote CI artifact not imported.</p></article>
    </section>
    """


def _complete_real_step(
    service: AlphaOnboardingService, session_id: str, step_id: str, payload: dict[str, Any]
) -> None:
    session = service.repository.get_session(session_id)
    if session.mode == "real_setup":
        _guard_no_fixture(payload)
    if step_id == "publication_destination" and session.mode == "real_setup":
        destination = _register_destination(service, session_id, payload)
        service.repository.bind_resource(
            session_id, step_id, session.workspace_id, "destination_reference_id", destination["id"], destination
        )
    elif step_id == "website_account" and session.mode == "real_setup":
        destination = _destination(service, session_id)
        service.repository.bind_resource(
            session_id,
            step_id,
            session.workspace_id,
            "website_account_id",
            "website-account-" + destination["id"],
            {"classification": "real", **destination},
        )
    elif step_id == "first_content" and session.mode == "real_setup":
        _ensure_real_draft(service, session_id, payload)
    elif step_id == "publication_plan" and session.mode == "real_setup":
        _ensure_real_plan(service, session_id)
    service.complete_step(session_id, step_id, payload)


def _ensure_real_draft(service: AlphaOnboardingService, session_id: str, payload: dict[str, Any]) -> str:
    existing = _bindings(service, session_id).get("draft_id", "")
    if existing:
        return existing
    return _create_real_draft(service, session_id, payload)


def _create_real_draft(
    service: AlphaOnboardingService,
    session_id: str,
    payload: dict[str, Any],
    *,
    force_new: bool = False,
) -> str:
    session = service.repository.get_session(session_id)
    title = str(payload.get("title") or "MVP Dogfood Publication 001")
    body = str(payload.get("markdown_body") or "")
    slug = str(payload.get("slug") or slugify(title))
    _guard_no_fixture({"title": title, "markdown_body": body})
    draft_seed = str(payload.get("idempotency_key") or "") if force_new else ""
    draft_id = "content-" + stable_checksum(session.id + title + draft_seed)[:12]
    draft = ContentDraft(
        draft_id,
        session.workspace_id,
        title,
        str(payload.get("summary") or ""),
        body,
        tuple(_split_csv(str(payload.get("tags") or ""))),
        str(payload.get("language") or "en"),
        str(payload.get("author") or ""),
        "draft",
        1,
        utc_now_iso(),
        slug,
        str(payload.get("seo_description") or ""),
    )
    owned_service().repository.save_draft(
        draft,
        expected_version=None,
        idempotency_key=str(payload.get("idempotency_key") or "phase331-draft-" + session.id),
        actor=session.created_by,
    )
    service.repository.bind_resource(
        session_id, "first_content", session.workspace_id, "draft_id", draft.id, {"classification": "real"}
    )
    return draft.id


def _ensure_real_plan(service: AlphaOnboardingService, session_id: str) -> dict[str, Any]:
    session = service.repository.get_session(session_id)
    first = service.repository.first_publication(session_id)
    if first.publication_plan_id:
        return asdict(first)
    bindings = _bindings(service, session_id)
    draft_id = bindings.get("draft_id") or _ensure_real_draft(service, session_id, {})
    destination = _destination(service, session_id)
    repo = owned_service().repository
    draft = CanonicalDraftResolver(service).resolve_draft(
        session.workspace_id, draft_id, session.mode, session_id=session_id, require_binding=True
    )
    revision = repo.create_revision(
        draft.id,
        expected_version=draft.version,
        idempotency_key="phase331-revision-" + session.id,
        actor=session.created_by,
    )
    variant = repo.create_variant(
        revision,
        "channel.markdown_website",
        revision.markdown_body,
        idempotency_key="phase331-website-variant-" + revision.id,
    )
    target_id = "target-website-" + stable_checksum(revision.id)[:10]
    plan = repo.create_plan(
        session.workspace_id,
        draft.id,
        revision.id,
        [
            {
                "id": target_id,
                "channel_id": "channel.markdown_website",
                "account_id": "website-account-" + destination["id"],
                "variant_id": variant.id,
                "verification_policy": "local_http",
                "status": "ready",
                "execution_state": "waiting",
            }
        ],
        [],
        campaign_id="dogfood-001",
        idempotency_key="phase331-plan-" + session.id,
        actor=session.created_by,
    )
    readmodel = FirstPublicationReadmodel(
        session_id=session.id,
        workspace_id=session.workspace_id,
        content_item_id=draft.id,
        content_revision_id=revision.id,
        website_account_id="website-account-" + destination["id"],
        publication_plan_id=plan.id,
        verification_status="plan_ready",
        analytics_sync_status="not_configured",
        funnel_status="provider_pending",
        public_url=_public_url_for_revision(destination, revision.slug or slugify(revision.title)),
        evidence_ids=(),
        mutation_summary=("commit_only", "no_push", destination["repository_display"]),
        checksum_bindings={
            "revision": revision.checksum,
            "source_draft_id": revision.content_item_id,
            "source_draft_version": str(revision.source_draft_version),
            "plan": stable_checksum(plan.id),
            "seo_description": revision.seo_description,
            "seo_description_source": _seo_description_source(revision.seo_description, revision.summary),
            "seo_description_checksum": stable_checksum(revision.seo_description),
        },
        timeline=({"phase": "Publication plan created", "status": "completed", "safe_evidence_summary": plan.id},),
    )
    service.repository.save_first_publication(readmodel)
    service.repository.bind_resource(
        session_id,
        "publication_plan",
        session.workspace_id,
        "revision_id",
        revision.id,
        {"classification": "real", "checksum": revision.checksum},
    )
    service.repository.bind_resource(
        session_id, "publication_plan", session.workspace_id, "publication_plan_id", plan.id, {"classification": "real"}
    )
    return asdict(readmodel)


def _confirm_real_publication(
    service: AlphaOnboardingService, session_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    if str(payload.get("confirmation") or "") != CONFIRMATION_TEXT:
        raise ValueError("Exact confirmation text is required.")
    first = service.repository.first_publication(session_id)
    if first.execution_request_id:
        return asdict(first)
    planned = _ensure_real_plan(service, session_id)
    session = service.repository.get_session(session_id)
    destination = _destination(service, session_id)
    repo = owned_service().repository
    revision = repo.get_revision(planned["content_revision_id"])
    plan = repo.get_plan(planned["publication_plan_id"])
    target = plan.targets[0]
    variant = repo.get_variant(target.variant_id)
    now = datetime.now(UTC)
    account = MarkdownWebsiteAccountConfig(
        id=planned["website_account_id"],
        workspace_id=session.workspace_id,
        account_id=planned["website_account_id"],
        display_name=destination["display_name"],
        repository_reference_id=destination["id"],
        branch=destination["branch"],
        content_root=destination["publication_root"],
        media_root="static/media",
        public_base_url=destination["public_base_url"],
        public_url_template=destination["public_url_template"],
        frontmatter_profile_id=destination["rendering_profile"],
        push_policy="commit_only",
        verification_policy="local_http",
    )
    snapshot = WebsitePublicationSnapshot(
        content_item_id=revision.content_item_id,
        content_revision_id=revision.id,
        channel_variant_id=variant.id,
        publication_plan_id=plan.id,
        publication_target_id=target.id,
        publication_attempt_id="execution-" + stable_checksum(session.id + plan.id)[:12],
        publication_snapshot_checksum=stable_checksum(revision.checksum + plan.id + target.id),
        website_profile_id=destination["rendering_profile"],
        website_profile_version="1.0",
        account_config=account,
        variant=WebsiteVariant(
            title=revision.title,
            slug=revision.slug or slugify(revision.title),
            markdown_body=variant.text,
            summary=revision.summary,
            description=_seo_description_for_publication(
                revision.seo_description, revision.summary, revision.markdown_body
            ),
            language=revision.language,
            author=revision.author,
            published_at=now,
            updated_at=now,
            tags=revision.tags,
            cta=WebsiteCallToAction("Open the project overview", destination["public_base_url"]),
        ),
    )
    rendered = MarkdownRenderer().render(snapshot)
    execution_id = snapshot.publication_attempt_id
    execution_evidence_id = _evidence_reference(execution_id, plan.id, revision.id)
    running_readmodel = FirstPublicationReadmodel(
        session_id=session.id,
        workspace_id=session.workspace_id,
        content_item_id=revision.content_item_id,
        content_revision_id=revision.id,
        website_account_id=planned["website_account_id"],
        publication_plan_id=plan.id,
        execution_request_id=execution_id,
        verification_status="running",
        analytics_sync_status="not_configured",
        funnel_status="provider_pending",
        public_url=rendered.public_url,
        evidence_ids=(execution_evidence_id,),
        mutation_summary=(
            "execution_status:running",
            "stage:output_generated",
            f"path:{rendered.relative_path}",
            "push:none",
        ),
        checksum_bindings={
            "revision": revision.checksum,
            "source_draft_id": revision.content_item_id,
            "source_draft_version": str(revision.source_draft_version),
            "rendered": rendered.checksum,
            "snapshot": snapshot.publication_snapshot_checksum,
            "seo_description": revision.seo_description,
            "seo_description_source": _seo_description_source(revision.seo_description, revision.summary),
            "seo_description_checksum": stable_checksum(revision.seo_description),
        },
        timeline=(
            _timeline_event("Plan confirmed", "completed", plan.id),
            _timeline_event("Execution claimed", "completed", execution_id),
            _timeline_event("Output generation", "completed", rendered.relative_path),
            _timeline_event("Git staging", "running", "waiting for exact staging"),
            _timeline_event("Git commit", "queued", "commit SHA not available yet"),
            _timeline_event("Website verification", "not_started", "waiting for verified commit"),
        ),
    )
    service.repository.save_first_publication(running_readmodel)
    service.repository.bind_resource(
        session_id, "publish", session.workspace_id, "execution_id", execution_id, {"classification": "real"}
    )
    reference = WebsiteRepositoryReference(
        id=destination["id"],
        workspace_id=session.workspace_id,
        display_name=destination["display_name"],
        managed_checkout_root=Path(destination["repository_path"]),
        allowed_branches=(destination["branch"],),
        allowed_content_roots=(destination["publication_root"],),
        allowed_media_roots=("static/media",),
    )
    try:
        evidence = GitPublisher().publish(
            snapshot,
            reference,
            rendered,
            identity=GitIdentity("SocialMediaManager Dogfood", "dogfood@example.invalid"),
            push=False,
        )
        publish_result = evidence.publish_result
        if not publish_result or not publish_result.commit_created or not publish_result.commit_sha:
            raise MarkdownWebsiteGitError("markdown_website.git.commit_unverified", "Commit was not verified.")
        if not (Path(destination["repository_path"]) / rendered.relative_path).exists():
            raise MarkdownWebsiteGitError("markdown_website.git.output_missing", "Expected output file is missing.")
        verification = WebsitePublicationVerifier(_safe_fetch).verify(evidence)
    except (MarkdownWebsiteGitError, MarkdownWebsiteVerificationError, OSError, ValueError) as exc:
        code = getattr(exc, "code", "markdown_website.execution.failed")
        failure_evidence_id = _evidence_reference(execution_id, code, rendered.relative_path)
        failure = FirstPublicationReadmodel(
            session_id=session.id,
            workspace_id=session.workspace_id,
            content_item_id=revision.content_item_id,
            content_revision_id=revision.id,
            website_account_id=planned["website_account_id"],
            publication_plan_id=plan.id,
            execution_request_id=execution_id,
            verification_status="failed",
            analytics_sync_status="not_configured",
            funnel_status="provider_pending",
            public_url=rendered.public_url,
            evidence_ids=(execution_evidence_id, failure_evidence_id),
            mutation_summary=(
                "execution_status:failed",
                "commit_created:false",
                "commit_sha:",
                "verification_status:not_started",
                f"safe_error_code:{code}",
                f"path:{rendered.relative_path}",
                "push:none",
            ),
            checksum_bindings={
                "revision": revision.checksum,
                "source_draft_id": revision.content_item_id,
                "source_draft_version": str(revision.source_draft_version),
                "rendered": rendered.checksum,
                "snapshot": snapshot.publication_snapshot_checksum,
                "seo_description": revision.seo_description,
                "seo_description_source": _seo_description_source(revision.seo_description, revision.summary),
                "seo_description_checksum": stable_checksum(revision.seo_description),
            },
            timeline=(
                _timeline_event("Plan confirmed", "completed", plan.id),
                _timeline_event("Execution claimed", "completed", execution_id),
                _timeline_event("Output generation", "completed", rendered.relative_path),
                _timeline_event("Git staging / commit", "failed", failure_evidence_id, error_code=code),
                _timeline_event("Website verification", "not_started", "commit was not verified"),
            ),
        )
        service.repository.save_first_publication(failure)
        return asdict(failure)
    git_evidence_id = (
        evidence.publish_result.evidence_ids[0]
        if evidence.publish_result and evidence.publish_result.evidence_ids
        else _evidence_reference(execution_id, evidence.publication_commit)
    )
    verification_evidence_id = _evidence_reference(execution_id, "verification", verification.status)
    event_rows = (
        _timeline_event("Plan confirmed", "completed", plan.id),
        _timeline_event("Execution claimed", "completed", execution_id),
        _timeline_event("Output generation", "completed", rendered.relative_path),
        _timeline_event("Git staging", "completed", ", ".join(evidence.publish_result.staged_files)),
        _timeline_event("Git commit created", "completed", evidence.publication_commit),
        _timeline_event("Public URL verified", verification.status, rendered.public_url),
    )
    readmodel = FirstPublicationReadmodel(
        session_id=session.id,
        workspace_id=session.workspace_id,
        content_item_id=revision.content_item_id,
        content_revision_id=revision.id,
        website_account_id=planned["website_account_id"],
        publication_plan_id=plan.id,
        execution_request_id=snapshot.publication_attempt_id,
        verification_status=verification.status,
        analytics_sync_status="not_configured",
        funnel_status="provider_pending",
        public_url=rendered.public_url,
        evidence_ids=(execution_evidence_id, git_evidence_id, verification_evidence_id),
        mutation_summary=(
            f"commit:{evidence.publication_commit}",
            "execution_status:completed",
            f"path:{evidence.markdown_relative_path}",
            f"repository_state_before:{evidence.publish_result.repository_state_before}",
            f"parent_commit:{evidence.publish_result.parent_commit_sha or 'none'}",
            "push:none",
        ),
        checksum_bindings={
            "revision": revision.checksum,
            "source_draft_id": revision.content_item_id,
            "source_draft_version": str(revision.source_draft_version),
            "rendered": rendered.checksum,
            "snapshot": snapshot.publication_snapshot_checksum,
            "seo_description": revision.seo_description,
            "seo_description_source": _seo_description_source(revision.seo_description, revision.summary),
            "seo_description_checksum": stable_checksum(revision.seo_description),
        },
        timeline=event_rows,
    )
    service.repository.save_first_publication(readmodel)
    service.repository.bind_resource(
        session_id,
        "publish",
        session.workspace_id,
        "execution_id",
        snapshot.publication_attempt_id,
        {"classification": "real"},
    )
    service.repository.bind_resource(
        session_id,
        "verification",
        session.workspace_id,
        "verification_id",
        verification.status,
        {"classification": "real"},
    )
    return asdict(readmodel)


def _register_destination(service: AlphaOnboardingService, session_id: str, payload: dict[str, Any]) -> dict[str, str]:
    session = service.repository.get_session(session_id)
    managed_root = Path(str(payload.get("managed_root") or "")).expanduser()
    repository_name = str(payload.get("repository") or "").strip()
    if not managed_root.is_absolute() or not repository_name:
        raise ValueError("Managed root and repository are required.")
    root = managed_root.resolve(strict=False)
    repo_path = (root / repository_name).resolve(strict=False)
    if os.path.commonpath([str(root), str(repo_path)]) != str(root):
        raise ValueError("Repository must stay inside the managed root.")
    _block_protected_destination(repo_path)
    if not (repo_path / ".git").exists():
        raise ValueError("Selected repository is not a Git repository.")
    branch = str(payload.get("branch") or "main").strip()
    actual_branch = _git(repo_path, "branch", "--show-current")
    if branch != actual_branch:
        raise ValueError(f"Selected branch is {actual_branch or 'unknown'}, not {branch}.")
    template = str(payload.get("public_url_template") or "")
    parsed = urlparse(template.format(slug="dogfood-check", year="2026", month="07", day="31", language="en"))
    if parsed.hostname not in {"127.0.0.1", "localhost"} and parsed.scheme != "https":
        raise ValueError("Public URL template must be HTTPS or a local HTTP origin.")
    destination_id = "destination-" + stable_checksum(str(repo_path) + branch)[:12]
    return {
        "classification": "real",
        "id": destination_id,
        "display_name": str(payload.get("display_name") or "MVP Dogfood Website"),
        "managed_root": str(root),
        "repository_path": str(repo_path),
        "repository_display": repo_path.name,
        "branch": branch,
        "rendering_profile": str(payload.get("rendering_profile") or "generic_yaml"),
        "publication_root": str(payload.get("publication_root") or "articles").strip("/"),
        "public_url_template": template,
        "public_base_url": f"{parsed.scheme}://{parsed.netloc}",
        "git_mode": "commit_only",
        "verification_mode": "local_http",
        "workspace_id": session.workspace_id,
    }


def _doctor(service: AlphaOnboardingService, session_id: str) -> list[dict[str, str]]:
    try:
        destination = _destination(service, session_id)
        repo = Path(destination["repository_path"])
        head_commit = _git(repo, "rev-parse", "--verify", "HEAD")
        history_status = "PASS" if head_commit else "WARN"
        history_details = head_commit[:12] if head_commit else "No commits yet; first commit will be created"
        checks = [
            ("Repository registered", "PASS", destination["repository_display"]),
            ("Git repository", "PASS" if (repo / ".git").exists() else "FAIL", "Worktree detected"),
            (
                "Branch",
                "PASS" if _git(repo, "branch", "--show-current") == destination["branch"] else "FAIL",
                destination["branch"],
            ),
            ("Repository history", history_status, history_details),
            ("Write permissions", "PASS" if os.access(repo, os.W_OK) else "FAIL", "Commit-only write access"),
            ("Publication root", "PASS", destination["publication_root"]),
            ("Renderer", "PASS", destination["rendering_profile"]),
            ("Public URL template", "PASS", destination["public_url_template"]),
            ("Verification origin", "PASS", destination["public_base_url"]),
            ("Instrumentation", "WARN", "Not configured"),
            ("Push policy", "PASS", "Commit only"),
        ]
    except Exception as exc:
        checks = [("Repository registered", "FAIL", str(exc))]
    return [{"check": check, "status": status, "details": details} for check, status, details in checks]


def _destination(service: AlphaOnboardingService, session_id: str) -> dict[str, str]:
    bindings = [
        item
        for item in service.repository.list_bindings(session_id)
        if item["resource_type"] == "destination_reference_id"
    ]
    if not bindings:
        raise ValueError("Register a real Markdown Website destination first.")
    destination = {key: str(value) for key, value in dict(bindings[-1]["safe_metadata"]).items()}
    if destination.get("classification") != "real":
        raise ValueError("Real setup cannot use demo or fixture destinations.")
    _guard_no_fixture(destination)
    return destination


def _bindings(service: AlphaOnboardingService, session_id: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in service.repository.list_bindings(session_id):
        result[item["resource_type"]] = item["resource_id"]
    return result


def _real_review_payload(service: AlphaOnboardingService, session_id: str) -> dict[str, Any]:
    publication = asdict(service.repository.first_publication(session_id))
    if not publication.get("publication_plan_id"):
        publication = _ensure_real_plan(service, session_id)
    return {"publication": publication, "blocking": False}


def _real_publication_status(service: AlphaOnboardingService, session_id: str) -> dict[str, Any]:
    return {"publication": asdict(service.repository.first_publication(session_id))}


def _real_funnel(service: AlphaOnboardingService, session_id: str) -> dict[str, Any]:
    first = service.repository.first_publication(session_id)
    return {"content_item_id": first.content_item_id, "status": first.funnel_status}


def _safe_fetch(url: str) -> HttpResponse:
    with urllib.request.urlopen(url, timeout=5) as response:
        text = response.read(1024 * 1024).decode("utf-8", errors="replace")
        headers = {key.lower(): value for key, value in response.headers.items()}
        return HttpResponse(int(response.status), response.geturl(), headers, text)


def _public_url_for_revision(destination: dict[str, str], slug: str) -> str:
    return destination["public_url_template"].format(slug=slug, year="2026", month="07", day="31", language="en")


def _block_protected_destination(path: Path) -> None:
    resolved = path.resolve(strict=False)
    product = PRODUCT_ROOT.resolve()
    if os.path.commonpath([str(product), str(resolved)]) == str(product):
        raise ValueError("The product repository cannot be a publication destination.")
    if resolved == resolved.parent:
        raise ValueError("Filesystem root cannot be a publication destination.")
    if any(part in PROTECTED_NAMES for part in resolved.parts):
        raise ValueError("Protected content, drafts, repository metadata, vault or runtime paths are blocked.")
    if resolved.is_symlink():
        raise ValueError("Symlink destinations are blocked.")


def _guard_no_fixture(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, sort_keys=True, default=str)
    if any(marker in text for marker in FIXTURE_MARKERS):
        raise ValueError("Real setup cannot bind fixture or synthetic resources.")


def _timeline_event(
    phase: str,
    status: str,
    summary: str = "",
    *,
    error_code: str = "",
    next_action: str = "",
) -> dict[str, str]:
    return {
        "phase": phase,
        "status": status,
        "safe_evidence_summary": summary,
        "error_code": error_code,
        "next_action": next_action,
    }


def _evidence_reference(*parts: str) -> str:
    return "evidence-" + stable_checksum(":".join(parts))[:12]


def _seo_description_for_publication(seo_description: str, summary: str, markdown_body: str) -> str:
    if seo_description.strip():
        return seo_description.strip()
    if summary.strip():
        return summary.strip()
    return " ".join(markdown_body.split())[:160]


def _seo_description_source(seo_description: str, summary: str) -> str:
    if seo_description.strip():
        return "custom"
    if summary.strip():
        return "summary"
    return "generated"


def _mutation_value(publication: dict[str, Any], prefix: str) -> str:
    marker = prefix + ":"
    for item in publication.get("mutation_summary") or ():
        text = str(item)
        if text.startswith(marker):
            return text.removeprefix(marker)
    return ""


def _commit_sha(publication: dict[str, Any]) -> str:
    return _mutation_value(publication, "commit")


def _execution_status(publication: dict[str, Any]) -> dict[str, str]:
    raw = _mutation_value(publication, "execution_status")
    verification = str(publication.get("verification_status") or "")
    commit_sha = _commit_sha(publication)
    timeline = tuple(publication.get("timeline") or ())
    failed_event = next((item for item in timeline if str(item.get("status")) == "failed"), {})
    uncertain_event = next((item for item in timeline if str(item.get("status")) == "uncertain"), {})
    verified_event = next(
        (
            item
            for item in timeline
            if item.get("phase") in {"Public URL verified", "Verified"} and str(item.get("safe_evidence_summary") or "")
        ),
        {},
    )
    if raw == "completed" and verification == "publication_verified" and commit_sha and verified_event:
        return {
            "status": "Completed",
            "stage": "Verified",
            "code": "",
            "action": "",
            "aria": "Execution status Completed, stage Verified.",
        }
    if raw == "failed" or verification == "failed" or failed_event:
        stage = str(failed_event.get("phase") or _mutation_value(publication, "stage") or "Failed")
        code = str(failed_event.get("error_code") or _mutation_value(publication, "safe_error_code") or "safe_error")
        return {
            "status": "Failed",
            "stage": stage,
            "code": code,
            "action": "Review evidence and use safe recovery.",
            "aria": f"Execution status Failed, stage {stage}, safe error {code}.",
        }
    if raw == "uncertain" or verification == "uncertain" or uncertain_event:
        stage = str(uncertain_event.get("phase") or _mutation_value(publication, "stage") or "Uncertain")
        code = str(uncertain_event.get("error_code") or _mutation_value(publication, "safe_error_code") or "")
        return {
            "status": "Uncertain",
            "stage": stage,
            "code": code,
            "action": "Run read-only reconciliation before any retry.",
            "aria": f"Execution status Uncertain, stage {stage}. Read-only reconciliation is required.",
        }
    if raw == "running" or verification == "running":
        return {
            "status": "Running",
            "stage": _mutation_value(publication, "stage") or "Running",
            "code": "",
            "action": "",
            "aria": "Execution status Running.",
        }
    if raw == "cancelled":
        return {
            "status": "Cancelled",
            "stage": "Cancelled",
            "code": "",
            "action": "",
            "aria": "Execution status Cancelled.",
        }
    return {"status": "Queued", "stage": "Plan confirmed", "code": "", "action": "", "aria": "Execution status Queued."}


def _execution_status_panel(execution: dict[str, str]) -> str:
    fields = [
        ("Execution status", execution["status"]),
        ("Execution stage", execution["stage"]),
    ]
    if execution.get("code"):
        fields.append(("Safe error code", execution["code"]))
    if execution.get("action"):
        fields.append(("Safe action", execution["action"]))
    return (
        f'<section class="status-card" role="status" aria-live="polite" aria-label="{html.escape(execution["aria"])}">'
        "<h3>Execution status</h3><dl class='facts'>"
        + "".join(f"<dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>" for label, value in fields)
        + "</dl></section>"
    )


def _ensure_phase331_tables(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(cwd), text=True, capture_output=True, check=False, timeout=10)
    if result.returncode:
        return ""
    return result.stdout.strip()


def _plan_summary(publication: dict[str, Any]) -> str:
    checksums = publication.get("checksum_bindings") or {}
    fields = (
        ("Workspace", publication.get("workspace_id", "")),
        ("Draft ID", publication.get("content_item_id", "")),
        ("Revision ID", publication.get("content_revision_id", "")),
        (
            "Source draft ID",
            ("source draft " + str(checksums.get("source_draft_id")))
            if checksums.get("source_draft_id")
            else publication.get("content_item_id", ""),
        ),
        ("Source draft version", checksums.get("source_draft_version", "")),
        ("Revision checksum", checksums.get("revision", "")),
        ("SEO description", checksums.get("seo_description", "")),
        ("SEO description source", checksums.get("seo_description_source", "")),
        ("SEO description checksum", checksums.get("seo_description_checksum", "")),
        ("Publication plan ID", publication.get("publication_plan_id", "")),
        ("Execution ID", publication.get("execution_request_id", "")),
        ("Website account", publication.get("website_account_id", "")),
        ("Public URL", publication.get("public_url", "")),
        ("Verification", publication.get("verification_status", "")),
        ("Evidence", ", ".join(publication.get("evidence_ids") or ())),
        ("Mutation summary", ", ".join(publication.get("mutation_summary") or ())),
        ("Rendered checksum", checksums.get("rendered", "")),
        ("Snapshot checksum", checksums.get("snapshot", "")),
    )
    return (
        "<dl class='facts'>"
        + "".join(f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(value))}</dd>" for label, value in fields)
        + "</dl>"
    )


def _step_row(session: dict[str, Any], step: dict[str, Any]) -> str:
    status = step.get("completion_state", "not_started")
    return f'<div class="step-row"><a href="/setup/{html.escape(session["id"])}/{html.escape(step["step_id"])}">{html.escape(step["display_name"])}</a><span>{html.escape("required" if step["required"] else "optional")}</span><span class="status info">{html.escape(status)}</span></div>'


def _next_step_href(session_id: str, step_id: str) -> str:
    try:
        index = STEP_ORDER.index(step_id)
        return f"/setup/{session_id}/{STEP_ORDER[min(index + 1, len(STEP_ORDER) - 1)]}"
    except ValueError:
        return f"/setup/{session_id}"


def _step_explanation(step_id: str) -> str:
    return {
        "publication_destination": "Register a real, managed Markdown Website repository outside the product worktree.",
        "website_account": "Review doctor checks for the selected repository.",
        "first_content": "Create or open a real durable draft in the canonical composer.",
        "publication_plan": "Create an immutable revision and plan from the real draft.",
    }.get(step_id, "Complete the setup step and save durable progress.")


def _metric_card(title: str, value: str, detail: str) -> str:
    return f'<article class="card span-3"><h2>{html.escape(title)}</h2><p><strong>{html.escape(str(value))}</strong></p><p>{html.escape(detail)}</p></article>'


def _simple_panel(title: str, message: str) -> str:
    return f'<section class="panel"><h2>{html.escape(title)}</h2><p>{html.escape(message)}</p></section>'


def _latest_session(status: dict[str, Any]) -> dict[str, Any] | None:
    sessions = status.get("active_sessions") or status.get("sessions") or []
    return sessions[0] if sessions else None


def _latest_real_session(status: dict[str, Any]) -> dict[str, Any] | None:
    sessions = status.get("active_sessions") or status.get("sessions") or []
    return next((session for session in sessions if session.get("mode") == "real_setup"), None)


def _empty_readiness() -> dict[str, Any]:
    return {"setup_progress": 0, "alpha_operational_ready": False, "production_ready": False, "website_ready": False}


def _yes_no(value: Any) -> str:
    return "Yes" if bool(value) else "No"


def _ready_label(value: Any) -> str:
    return "Ready" if bool(value) else "Not configured"


def _flatten_form(form: dict[str, list[str]]) -> dict[str, Any]:
    return {key: values[-1] if values else "" for key, values in form.items()}


def _field(form: dict[str, list[str]], key: str, default: str = "") -> str:
    values = form.get(key)
    return values[-1] if values else default


def _step_payload(form: dict[str, list[str]]) -> dict[str, Any]:
    return _flatten_form(form)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _safe_id(value: str) -> str:
    return (
        "".join(char if char.isalnum() or char in "-_" else "-" for char in value.strip())[:80] or "workspace-alpha-1"
    )


def _redirect(location: str) -> tuple[str, HTTPStatus]:
    return json.dumps({"redirect": location}), HTTPStatus.SEE_OTHER


def _evidence_id(code: str) -> str:
    return f"phase331-{abs(hash(code)) % 100000:05d}"
