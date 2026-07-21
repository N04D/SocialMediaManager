#!/usr/bin/env bash
set -euo pipefail
"${PYTHON:-${PWD}/.venv/bin/python}" -m plugin_sdk.cli validate-manifest channels/linkedin/plugin.manifest.json
"${PYTHON:-${PWD}/.venv/bin/python}" -m plugin_sdk.cli validate-manifest channels/mastodon/plugin.manifest.json
"${PYTHON:-${PWD}/.venv/bin/python}" -m plugin_sdk.cli compatibility channels/linkedin
"${PYTHON:-${PWD}/.venv/bin/python}" -m plugin_sdk.cli compatibility channels/mastodon
"${PYTHON:-${PWD}/.venv/bin/python}" -m plugin_sdk.cli test templates/channel-plugin
"${PYTHON:-${PWD}/.venv/bin/python}" -m plugin_sdk.cli package-check templates/channel-plugin
"${PYTHON:-${PWD}/.venv/bin/python}" -m py_compile $(find src/plugin_sdk plugin_sdk -name '*.py' -print)
"${PYTHON:-${PWD}/.venv/bin/python}" -m ruff check src/plugin_sdk plugin_sdk templates/channel-plugin tests/test_plugin_sdk_phase17.py
"${PYTHON:-${PWD}/.venv/bin/python}" -m ruff format --check src/plugin_sdk plugin_sdk templates/channel-plugin tests/test_plugin_sdk_phase17.py
