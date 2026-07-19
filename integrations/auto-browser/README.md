# Auto Browser Integration

Phase 5 treats Auto Browser as an external browser controller. The application does not vendor Auto Browser code and does not require it to start.

Tested upstream:

- Repository: `LvcidPsyche/auto-browser`
- Server release: `v1.4.0`
- Server commit: `a7414a4`
- `/version` API value observed from the pinned build: `1.3.1`
- Python packages inspected: `auto-browser-client==1.4.0`, `auto-browser-mcp==1.4.0`
- Transport used by this app: deterministic REST, not MCP agent transport

Configure locally through `config.json` and environment secrets:

```json
{
  "auto_browser_enabled": true,
  "auto_browser_base_url": "http://127.0.0.1:8000",
  "auto_browser_bearer_token_env": "AUTO_BROWSER_BEARER_TOKEN",
  "auto_browser_operator_id": "social-media-manager",
  "auto_browser_expected_server_version": "1.3.1"
}
```

Security defaults:

- Bind the controller and takeover viewer to localhost unless you have a protected private network.
- Store the bearer token only in the referenced environment variable.
- Keep TLS verification enabled for non-local URLs.
- Do not enable captcha solving, stealth, or platform-security bypass features.
- Do not copy legacy Playwright cookies into Auto Browser profiles automatically.

Migration route for an existing LinkedIn account:

1. Select `provider.browser.autobrowser` for the LinkedIn channel account.
2. Run LinkedIn Connect.
3. Complete one manual login through the generic human takeover route.
4. Let the provider save the Auto Browser auth profile.
5. Run session check.
6. Publish, metrics, and scraping can then reuse the Auto Browser profile.
7. Switching back to `provider.browser.legacy` reuses the existing legacy browser profile.

Doctor checks should remain non-destructive: health, readiness, version, feature availability, and auth only. They must not open LinkedIn or publish content.

## Local startup

From this directory:

```bash
cp .env.example .env
docker compose --env-file .env -f compose.yaml up --build
```

The Compose file builds directly from the pinned upstream Git tag `v1.4.0`; it does not copy Auto Browser source into this repository. The pinned build reports `1.3.1` from `/version`, so the app checks that API value while the deployment remains pinned to release `v1.4.0`.

Stop:

```bash
docker compose --env-file .env -f compose.yaml down
```

Reset local test data:

```bash
docker compose --env-file .env -f compose.yaml down -v
rm -rf data/controller fixture_uploads
```

## Fixture and doctor

Start the deterministic local fixture:

```bash
python3 fixture_site.py --host 0.0.0.0 --port 8765
```

Use `http://host.docker.internal:8765/` as the fixture URL for tests executed through the Dockerized controller.

Run the read-only doctor from the repository root:

```bash
AUTO_BROWSER_BASE_URL=http://127.0.0.1:8000 \
AUTO_BROWSER_BEARER_TOKEN=replace-with-local-development-token \
AUTO_BROWSER_OPERATOR_ID=social-media-manager \
python3 integrations/auto-browser/doctor.py
```

Doctor output is redacted and reports `PASS`, `WARN`, or `FAIL` per check. It may create and close one temporary testsession against the local fixture, but it never opens LinkedIn, publishes content, or mutates existing auth profiles.

## Observed API notes

The pinned `v1.4.0` build was checked against the local fixture. Differences from the phase-5 fake-controller assumptions:

- `/version` returns `1.3.1`; this is treated as the API version for compatibility checks.
- Session creation accepts `name`, `start_url`, and optional `auth_profile`; it rejects arbitrary `metadata`.
- First-login sessions must omit `auth_profile` when the remote auth profile does not exist yet.
- Observation returns interactive targets under `interactables`.
- Screenshot returns `screenshot_path` and `screenshot_url`.
- Controlled evaluation is available through `/sessions/{session_id}/cdp/raw` with `Runtime.evaluate`.
- Upload actions accept a controller-local file path; a production-safe app-to-controller file transfer endpoint was not present in the inspected REST routes.
- Auth profile save and lookup are available, but a targeted auth profile DELETE route was not present in the inspected REST routes. The app therefore keeps forget-login audited and safe, and reports remote delete failures without deleting legacy state or content.

## Opt-in integration tests

With controller and fixture running:

```bash
AUTO_BROWSER_INTEGRATION=1 \
AUTO_BROWSER_BASE_URL=http://127.0.0.1:8000 \
AUTO_BROWSER_BEARER_TOKEN=replace-with-local-development-token \
AUTO_BROWSER_OPERATOR_ID=social-media-manager \
AUTO_BROWSER_FIXTURE_URL=http://host.docker.internal:8765/ \
.venv/bin/python -m unittest tests.test_auto_browser_integration
```

The tests use unique test profile names and only remove resources created by the same run. They skip by default when `AUTO_BROWSER_INTEGRATION=1` is absent.

## Upgrade and rollback

Upgrade only by changing the pinned tag in `compose.yaml`, then run doctor and the opt-in integration suite before using a channel account. Roll back by restoring the previous tag and restarting Compose.
