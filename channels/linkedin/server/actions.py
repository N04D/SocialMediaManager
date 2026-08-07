from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from pipeline import AppConfig, run_local_ai
from studio_models import ContentItem


PLUGIN_DIR = Path(__file__).resolve().parents[1]
RULES_PATH = PLUGIN_DIR / "rules.yaml"
PROMPT_PATH = PLUGIN_DIR / "prompts" / "linkedin-post.md"


def load_rules() -> dict[str, Any]:
    loaded = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def load_prompt_template() -> str:
    if not PROMPT_PATH.exists():
        return ""
    return PROMPT_PATH.read_text(encoding="utf-8")


def save_prompt_template(new_template: str) -> None:
    PROMPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROMPT_PATH.write_text(new_template, encoding="utf-8")



def validate_derivative(*, title: str, body: str, output_type: str) -> dict[str, Any]:
    rules = load_rules()
    limits = rules.get("limits", {})
    formatting = rules.get("formatting", {})
    errors: list[str] = []
    warnings: list[str] = []

    if output_type != "linkedin_post":
        errors.append("LinkedIn plugin only supports linkedin_post.")

    max_characters = int(limits.get("max_characters", 3000))
    preferred_min = int(limits.get("preferred_min_characters", 800))
    preferred_max = int(limits.get("preferred_max_characters", 2200))
    body_length = len(body.strip())

    if body_length == 0:
        errors.append("Derivative body is empty.")
    if body_length > max_characters:
        errors.append(f"Derivative exceeds the LinkedIn maximum of {max_characters} characters.")
    if body_length and body_length < preferred_min:
        warnings.append(f"Derivative is shorter than the preferred minimum of {preferred_min} characters.")
    if body_length > preferred_max:
        warnings.append(f"Derivative is longer than the preferred maximum of {preferred_max} characters.")

    max_paragraph_lines = int(formatting.get("max_paragraph_lines", 3))
    for paragraph in [block for block in body.split("\n\n") if block.strip()]:
        if len([line for line in paragraph.splitlines() if line.strip()]) > max_paragraph_lines:
            warnings.append(
                f"At least one paragraph exceeds the preferred {max_paragraph_lines} line limit."
            )
            break

    hashtag_count = sum(1 for token in body.split() if token.startswith("#"))
    hashtag_max = int(formatting.get("hashtags_max", 3))
    if hashtag_count > hashtag_max:
        errors.append(f"Derivative exceeds the hashtag maximum of {hashtag_max}.")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "character_count": body_length,
    }


def generate_derivative(*, source_item: ContentItem, config: AppConfig, output_type: str) -> dict[str, Any]:
    rules = load_rules()
    prompt_template = load_prompt_template()
    prompt = prompt_template.format(
        rules_json=json.dumps(rules, ensure_ascii=False, indent=2),
        title=source_item.title.strip() or "Untitled",
        subtitle=source_item.subtitle.strip(),
        tags=", ".join(source_item.tags),
        categories=", ".join(source_item.categories),
        markdown_body=source_item.markdown_body.strip(),
    )
    generated_body = run_local_ai(prompt, config, f"local://content/{source_item.slug or source_item.id}")
    validation = validate_derivative(
        title=source_item.title.strip(),
        body=generated_body,
        output_type=output_type,
    )
    return {
        "title": source_item.title.strip() or "LinkedIn derivative",
        "body": generated_body.strip(),
        "validation": validation,
        "metadata": {
            "rules_path": str(RULES_PATH),
            "prompt_path": str(PROMPT_PATH),
            "output_type": output_type,
            "character_count": len(generated_body.strip()),
        },
    }

