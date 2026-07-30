"""Deterministic demo resources for alpha onboarding."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import stable_checksum


@dataclass(frozen=True)
class AlphaDemoStack:
    root: Path
    database_path: Path
    vault_path: Path
    repository_root: Path
    workspace_id: str = "demo-workspace-alpha"
    operator_id: str = "demo-operator-alpha"
    website_account_id: str = "demo-markdown-website-account"
    analytics_account_id: str = "demo-plausible-account"
    instrumentation_config_id: str = "demo-instrumentation-config"
    mastodon_account_id: str = "demo-mastodon-account"
    professional_social_account_id: str = "demo-professional-social-account"


def create_demo_stack(root: Path | None = None) -> AlphaDemoStack:
    base = root or Path(tempfile.mkdtemp(prefix="smm-alpha-demo-"))
    database_path = base / "alpha-demo.sqlite3"
    vault_path = base / "vault"
    repository_root = base / "markdown-website"
    vault_path.mkdir(parents=True, exist_ok=True)
    repository_root.mkdir(parents=True, exist_ok=True)
    (repository_root / ".git").mkdir(exist_ok=True)
    (repository_root / "README.md").write_text("# Synthetic alpha demo website\n", encoding="utf-8")
    return AlphaDemoStack(base, database_path, vault_path, repository_root)


def synthetic_article_payload() -> dict[str, object]:
    body = (
        "# Demo alpha article\n\n"
        "This synthetic article exists only inside deterministic demo mode. "
        "It contains no customer name, campaign data, credentials, or private operator content.\n\n"
        "## CTA\n\nTry the fixture onboarding flow."
    )
    return {
        "title": "Demo alpha article",
        "markdown_body": body,
        "language": "en",
        "author": "Demo Operator",
        "tags": ["demo", "alpha"],
        "slug": "demo-alpha-article",
        "seo_description": "Synthetic fixture article for alpha onboarding.",
        "cta": "Try the fixture onboarding flow",
        "checksum": stable_checksum(body),
        "synthetic": True,
        "fixture_repository_only": True,
    }
