"""Compatibility shim for local source-tree imports of Plugin SDK v1."""

from __future__ import annotations

import importlib
import sys

from src.plugin_sdk import *  # noqa: F403
from src.plugin_sdk import __all__  # noqa: F401

_SUBMODULES = (
    "analytics",
    "assets",
    "auth",
    "browser",
    "capabilities",
    "channel",
    "compatibility",
    "content",
    "contracts",
    "errors",
    "execution",
    "fixtures",
    "health",
    "manifest",
    "media",
    "provider",
    "publication",
    "requirements",
    "testing",
)
for _name in _SUBMODULES:
    sys.modules.setdefault(f"plugin_sdk.{_name}", importlib.import_module(f"src.plugin_sdk.{_name}"))
