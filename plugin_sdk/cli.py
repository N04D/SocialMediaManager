"""CLI shim for python -m plugin_sdk.cli."""

from src.plugin_sdk.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
