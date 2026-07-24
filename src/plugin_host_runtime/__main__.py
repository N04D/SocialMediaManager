"""Entrypoint for `python -I -m plugin_host_runtime`."""

from __future__ import annotations

from .host import ChildPluginHost


def main() -> int:
    return ChildPluginHost().run()


if __name__ == "__main__":
    raise SystemExit(main())
