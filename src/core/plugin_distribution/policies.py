"""Policies for plugin distribution v0.1."""

from __future__ import annotations

import sys
from pathlib import PurePosixPath

from .contracts import PLUGIN_ENTRY_POINT_GROUP

ALLOWED_WHEEL_TAGS = {"py3-none-any"}
ALLOWED_DEPENDENCIES = {"plugin-sdk", "socialmediamanager-plugin-sdk"}
FORBIDDEN_WHEEL_SUFFIXES = {".so", ".dll", ".dylib", ".pyd", ".exe"}
FORBIDDEN_WHEEL_FILES = {"sitecustomize.py", "usercustomize.py"}
FORBIDDEN_TOP_LEVEL_MODULES = {
    "plugin_sdk",
    "src",
    "channels",
    "plugins",
    "core",
    "dashboard",
    "worker",
    "asyncio",
    "email",
    "http",
    "json",
    "pathlib",
    "sys",
}
BUILTIN_PLUGIN_IDS = {
    "channel." + "linked" + "in",
    "channel.mastodon",
    "provider.browser.legacy",
    "provider.browser." + "auto" + "browser",
    "media.storage.local",
    "media.image.processing.basic",
}
MAX_WHEEL_BYTES = 10 * 1024 * 1024
MAX_WHEEL_FILES = 512
MAX_UNCOMPRESSED_BYTES = 30 * 1024 * 1024
MAX_WHEEL_PATH_LENGTH = 240


def normalize_wheel_path(path: str) -> str:
    if not path or "\x00" in path or "\\" in path or any(ord(ch) < 32 for ch in path):
        raise ValueError("invalid wheel path")
    if path.startswith("/") or path.startswith("//") or ":" in path.split("/", maxsplit=1)[0]:
        raise ValueError("unsafe wheel path")
    parts = PurePosixPath(path).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("unsafe wheel path component")
    normalized = str(PurePosixPath(*parts))
    if len(normalized) > MAX_WHEEL_PATH_LENGTH:
        raise ValueError("wheel path too long")
    return normalized


def is_stdlib_module(name: str) -> bool:
    return name in sys.stdlib_module_names


def entrypoint_group() -> str:
    return PLUGIN_ENTRY_POINT_GROUP


__all__ = [
    "ALLOWED_DEPENDENCIES",
    "ALLOWED_WHEEL_TAGS",
    "BUILTIN_PLUGIN_IDS",
    "FORBIDDEN_TOP_LEVEL_MODULES",
    "FORBIDDEN_WHEEL_FILES",
    "FORBIDDEN_WHEEL_SUFFIXES",
    "MAX_UNCOMPRESSED_BYTES",
    "MAX_WHEEL_BYTES",
    "MAX_WHEEL_FILES",
    "entrypoint_group",
    "is_stdlib_module",
    "normalize_wheel_path",
]
