"""Reusable assertions for plugin contract tests."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

SECRET_WORDS = ("access_token", "client_secret", "password", "authorization_code", "cookie", "private_key")


def public_payload(value: Any) -> str:
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(value, default=str, sort_keys=True)


def assert_no_secrets(value: Any) -> None:
    payload = public_payload(value).lower()
    for word in SECRET_WORDS:
        assert word not in payload, f"secret-like field leaked: {word}"


def assert_no_storage_references(value: Any) -> None:
    payload = public_payload(value).lower()
    forbidden = ("storage://", "/home/", "/tmp/", "local_path")
    for word in forbidden:
        assert word not in payload, f"storage reference leaked: {word}"


__all__ = ["assert_no_secrets", "assert_no_storage_references", "public_payload"]
