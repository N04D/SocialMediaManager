#!/usr/bin/env bash
set -euo pipefail
PYBIN="${PYTHON:-${PWD}/.venv/bin/python}"
"${PYBIN}" integrations/plugin_registry/build_fixture.py
"${PYBIN}" -m plugin_sdk.cli validate-manifest channels/linkedin/plugin.manifest.json
"${PYBIN}" -m plugin_sdk.cli validate-manifest channels/mastodon/plugin.manifest.json
"${PYBIN}" -m plugin_sdk.cli compatibility channels/linkedin
"${PYBIN}" -m plugin_sdk.cli compatibility channels/mastodon
"${PYBIN}" -m plugin_sdk.cli test templates/channel-plugin
"${PYBIN}" -m plugin_sdk.cli package-check templates/channel-plugin
"${PYBIN}" -m plugin_sdk.cli package inspect integrations/plugin_registry/targets/channel_example-0.1.0-py3-none-any.whl
"${PYBIN}" -m plugin_sdk.cli package verify integrations/plugin_registry/releases/channel.example-0.1.0
"${PYBIN}" -m plugin_sdk.cli registry verify
"${PYBIN}" -m unittest tests.test_plugin_sdk_phase17 tests.test_plugin_distribution_phase18
"${PYBIN}" -m py_compile $(find src/plugin_sdk plugin_sdk src/core/plugin_distribution integrations/plugin_registry -name '*.py' -print) dashboard.py
"${PYBIN}" -m ruff check src/plugin_sdk plugin_sdk src/core/plugin_distribution integrations/plugin_registry templates/channel-plugin tests/test_plugin_sdk_phase17.py tests/test_plugin_distribution_phase18.py dashboard.py
"${PYBIN}" -m ruff format --check src/plugin_sdk plugin_sdk src/core/plugin_distribution integrations/plugin_registry templates/channel-plugin tests/test_plugin_sdk_phase17.py tests/test_plugin_distribution_phase18.py dashboard.py
