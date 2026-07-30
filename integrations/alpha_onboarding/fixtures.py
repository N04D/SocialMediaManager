"""Fixture builders for phase-32 alpha onboarding tests."""

from __future__ import annotations

from pathlib import Path

from src.core.alpha_onboarding.demo import AlphaDemoStack, create_demo_stack, synthetic_article_payload
from src.core.alpha_onboarding.service import AlphaOnboardingService


def build_alpha_onboarding_service(root: Path) -> AlphaOnboardingService:
    stack = create_demo_stack(root)
    return AlphaOnboardingService(database_path=stack.database_path)


def build_demo_stack(root: Path) -> AlphaDemoStack:
    return create_demo_stack(root)


def demo_article() -> dict[str, object]:
    return synthetic_article_payload()
