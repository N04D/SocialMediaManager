"""Repository path validation for Markdown Website publishing."""

from __future__ import annotations

import os
from pathlib import Path
from string import Formatter

from .errors import MarkdownWebsitePathError
from .models import WebsiteRepositoryReference

KNOWN_TEMPLATE_TOKENS = {"content_root", "media_root", "slug", "year", "month", "day", "language"}
BLOCKED_PARTS = {".git", ".ssh", ".gnupg"}


def validate_template(template: str) -> None:
    for _, field_name, format_spec, conversion in Formatter().parse(template):
        if format_spec or conversion or (field_name and field_name not in KNOWN_TEMPLATE_TOKENS):
            raise MarkdownWebsitePathError(
                "markdown_website.path.bad_template", "Path template contains an unsupported token."
            )


def render_template(template: str, values: dict[str, str]) -> str:
    validate_template(template)
    return template.format(**{key: values.get(key, "") for key in KNOWN_TEMPLATE_TOKENS})


def normalize_relative_path(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise MarkdownWebsitePathError("markdown_website.path.absolute", "Absolute paths are rejected.")
    parts = candidate.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise MarkdownWebsitePathError("markdown_website.path.traversal", "Path traversal is rejected.")
    if any(part in BLOCKED_PARTS for part in parts):
        raise MarkdownWebsitePathError("markdown_website.path.blocked", "Sensitive repository paths are rejected.")
    if any(ord(char) < 32 for char in str(candidate)):
        raise MarkdownWebsitePathError("markdown_website.path.control", "Control characters are rejected.")
    if any("\\" in part for part in parts):
        raise MarkdownWebsitePathError("markdown_website.path.backslash", "Backslash paths are rejected.")
    return candidate


def ensure_under(root: Path, relative: str) -> Path:
    rel = normalize_relative_path(relative)
    resolved_root = root.resolve()
    resolved = (resolved_root / rel).resolve(strict=False)
    if os.path.commonpath([str(resolved_root), str(resolved)]) != str(resolved_root):
        raise MarkdownWebsitePathError("markdown_website.path.escape", "Resolved path escapes the repository root.")
    for parent in [resolved, *resolved.parents]:
        if parent == resolved_root:
            break
        if parent.is_symlink():
            raise MarkdownWebsitePathError("markdown_website.path.symlink", "Symlink escapes are rejected.")
    return resolved


def assert_allowed_roots(config_root: str, allowed_roots: tuple[str, ...], *, kind: str) -> None:
    normalized = str(normalize_relative_path(config_root))
    allowed = {str(normalize_relative_path(item)) for item in allowed_roots}
    if normalized not in allowed:
        raise MarkdownWebsitePathError(f"markdown_website.path.{kind}_not_allowed", f"{kind} root is not allowlisted.")


def validate_repository_reference(reference: WebsiteRepositoryReference) -> None:
    root = reference.managed_checkout_root.resolve(strict=False)
    if not reference.enabled:
        raise MarkdownWebsitePathError("markdown_website.repository.disabled", "Repository reference is disabled.")
    if not (root / ".git").exists():
        raise MarkdownWebsitePathError(
            "markdown_website.repository.not_git", "Repository reference is not a Git worktree."
        )
    if any(part in {"content", "drafts"} for part in root.parts[-2:]):
        raise MarkdownWebsitePathError(
            "markdown_website.repository.user_owned_root",
            "Project content and drafts directories cannot be used as website fixtures.",
        )
