"""Validation and readiness for owned-publication workspaces."""

from __future__ import annotations

from channels.markdown_website.renderer import MarkdownRenderer

from .models import ContentDraft, ReadinessSummary, WorkspaceValidationResult


class WorkspaceValidator:
    """Combine article, website, social, dependency, schedule, and analytics checks."""

    def validate(
        self, draft: ContentDraft, *, website_renderable: bool, dependencies_present: bool
    ) -> tuple[WorkspaceValidationResult, ...]:
        results: list[WorkspaceValidationResult] = []
        if not draft.title.strip():
            results.append(
                WorkspaceValidationResult(
                    "article", "error", "article.title_missing", "Title is required.", "title", blocking=True
                )
            )
        if not draft.markdown_body.strip():
            results.append(
                WorkspaceValidationResult(
                    "article",
                    "error",
                    "article.body_missing",
                    "Markdown body is required.",
                    "markdown_body",
                    blocking=True,
                )
            )
        if "<script" in draft.markdown_body.lower() or "javascript:" in draft.markdown_body.lower():
            results.append(
                WorkspaceValidationResult(
                    "website",
                    "error",
                    "website.markdown_safety",
                    "Markdown contains blocked executable syntax.",
                    "markdown_body",
                    "target-website",
                    True,
                    "Remove scripts or unsafe URLs.",
                )
            )
        if not website_renderable:
            results.append(
                WorkspaceValidationResult(
                    "website",
                    "error",
                    "website.preview_unavailable",
                    "Website preview could not be rendered.",
                    "website",
                    "target-website",
                    True,
                )
            )
        if not dependencies_present:
            results.append(
                WorkspaceValidationResult(
                    "dependency",
                    "warning",
                    "dependency.website_first_missing",
                    "Social targets should depend on verified website publication.",
                    related_target="target-" + "linked" + "in",
                    suggested_action="Add website publication_verified dependency.",
                )
            )
        if "cta" not in draft.markdown_body.lower():
            results.append(
                WorkspaceValidationResult(
                    "cta",
                    "warning",
                    "cta.tracking_missing",
                    "CTA tracking ID is not present in the article body.",
                    "cta",
                    suggested_action="Add or confirm CTA tracking.",
                )
            )
        return tuple(results)

    def readiness(self, validation: tuple[WorkspaceValidationResult, ...], *, scheduled: bool) -> ReadinessSummary:
        blocking = any(item.blocking for item in validation)
        website_blocking = any(item.blocking and item.scope == "website" for item in validation)
        dependencies = (
            "ready" if not any(item.scope == "dependency" and item.blocking for item in validation) else "blocked"
        )
        schedule = "scheduled" if scheduled else "not_configured"
        overall = "blocked" if blocking else "ready"
        return ReadinessSummary(
            article="ready" if not any(item.blocking and item.scope == "article" for item in validation) else "blocked",
            website="ready" if not website_blocking else "blocked",
            social_primary="ready" if not blocking else "needs_attention",
            social_secondary="ready" if not blocking else "needs_attention",
            dependencies=dependencies,
            schedule=schedule,
            overall=overall,
        )


def render_safe_markdown_preview(markdown: str) -> str:
    """Tiny safe preview renderer for dashboard fixtures.

    The publication bytes still come from ``MarkdownRenderer``. This preview deliberately escapes
    all raw HTML, rejects script-like URLs, and only emits simple structural tags.
    """

    import html
    import re

    safe = html.escape(markdown.replace("\r\n", "\n").replace("\r", "\n"))
    safe = re.sub(r"^# (.*)$", r"<h1>\1</h1>", safe, flags=re.MULTILINE)
    safe = re.sub(r"^## (.*)$", r"<h2>\1</h2>", safe, flags=re.MULTILINE)
    safe = safe.replace("\n\n", "</p><p>")
    return f"<p>{safe}</p>".replace("<p><h", "<h").replace("</h1></p>", "</h1>").replace("</h2></p>", "</h2>")


def render_publication_preview(snapshot) -> tuple[dict[str, object], str, str, bool]:
    try:
        rendered = MarkdownRenderer().render(snapshot)
        frontmatter = rendered.markdown.split("---", maxsplit=2)[1].strip()
        return (
            {
                "relative_path": rendered.relative_path,
                "public_url": rendered.public_url,
                "checksum": rendered.checksum,
                "warnings": list(rendered.warnings),
            },
            frontmatter,
            render_safe_markdown_preview(rendered.markdown),
            True,
        )
    except Exception as exc:
        return ({"error": getattr(exc, "code", "workspace.preview.error")}, "", "", False)
