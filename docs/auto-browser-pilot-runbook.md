# Auto Browser Pilot Runbook

This runbook freezes the browser layer as framework v1 for the LinkedIn pilot. It keeps Auto Browser optional, provider-selected per account, and reversible to `provider.browser.legacy`.

## Preconditions

- Auto Browser controller is pinned to release `v1.4.0` / commit `a7414a4`.
- The observed API version from `/version` is `1.3.1`.
- `provider.browser.legacy` remains the global default.
- `provider.browser.autobrowser` is enabled only for selected pilot accounts.
- `AUTO_BROWSER_BEARER_TOKEN` is set in the environment and never stored in `config.json`.
- Shared upload transfer is configured with a host path and matching controller path:
  - `auto_browser_shared_upload_host_dir`
  - `auto_browser_shared_upload_controller_dir`
- The controller path should be `/shared/uploads/incoming`, not a mounted subdirectory below `/data`, so controller startup cleanup cannot trip over a busy volume mount.
- Local fixture and doctor pass before any LinkedIn account is switched.

## Pilot Readiness JSON

Use these read-only checks before enabling a pilot account:

```bash
python3 integrations/auto-browser/doctor.py --json
curl -s http://127.0.0.1:8080/api/providers/autobrowser/status
curl -s http://127.0.0.1:8080/api/plugins/health
curl -s http://127.0.0.1:8080/api/browser-framework/conformance
curl -s http://127.0.0.1:8080/api/browser-pilots/panel
```

The provider is pilot-ready only when `pilot_readiness.status` is `ready` and no required check is missing:

```json
{
  "provider_id": "provider.browser.autobrowser",
  "status": "ready",
  "machine_readable": true,
  "reasons": [],
  "required_checks": [
    "health_ready",
    "shared_volume_upload_transfer",
    "provider_bound_auth_state",
    "takeover_reference_safe",
    "legacy_rollback_available"
  ]
}
```

## Controlled Pilot Flow

1. Confirm no active LinkedIn jobs or provider locks exist for the account.
2. Confirm `provider.browser.legacy` still shows the previous provider-bound status.
3. Set the account browser provider to `provider.browser.autobrowser`.
4. Create a pilot run through `POST /api/browser-pilots`.
5. Run `POST /api/browser-pilots/{id}/preflight`.
6. Run LinkedIn Connect only after preflight passes.
7. Complete login through the generic takeover link only.
8. Run session check and confirm the Auto Browser provider-bound state is `connected`.
9. For any real publish action, prepare and confirm a one-time action token immediately before the operator-approved action.
10. Inspect plugin health and provider status for artifacts, orphaned sessions, stale mappings, and redacted errors.
11. Leave the account on Auto Browser only after successful cleanup and no active locks.

Do not use automated tests with production LinkedIn accounts. Do not publish a real LinkedIn post from a pilot validation unless the operator explicitly approves that content and timing.

## Kill Switches

Global kill switch:

```json
{
  "auto_browser_global_kill_switch": true
}
```

Per-account kill switch:

```json
{
  "auto_browser_account_kill_switches": ["connection_linkedin"]
}
```

The global switch disables provider selection. The account switch blocks new Auto Browser sessions for the named profile/account without changing content, metrics, drafts, or legacy provider state.

## Rollback To Legacy

1. Stop or wait for active Auto Browser jobs.
2. Confirm no active Auto Browser lock, session, or takeover exists for the account.
3. Change the account provider back to `provider.browser.legacy`.
4. Run session check through legacy.
5. Confirm the legacy provider-bound status is restored independently from Auto Browser status.
6. Leave Auto Browser auth state intact unless the user explicitly chooses Forget Auto Browser login.

There is no silent fallback: an account explicitly configured for Auto Browser must fail visibly if Auto Browser is disabled, incompatible, unavailable, or killed.

## Forget Auto Browser Login

Targeted remote auth-profile deletion is optional. If the configured controller does not expose a delete route, the app records `revoked_locally` and blocks future reuse of that profile name. The action requires confirmation and an operator reason.

Forget login never removes:

- legacy Playwright profile state;
- user content;
- drafts;
- published post records;
- metrics.

## Chaos Checks

Before widening the pilot, run the fake-controller and opt-in real integration suites:

```bash
.venv/bin/python -m unittest tests.test_auto_browser_provider_phase5 tests.test_auto_browser_provider_phase6 tests.test_auto_browser_provider_phase7
AUTO_BROWSER_INTEGRATION=1 .venv/bin/python -m unittest tests.test_auto_browser_integration
```

Required chaos observations:

- close timeout releases the local profile lock;
- unavailable controller reports reconciliation as `unavailable`;
- stale local mappings are reported and require explicit cleanup;
- orphaned remote sessions are reported only when ownership metadata proves they belong to this app;
- mutating actions such as click, upload, delete auth profile, takeover creation, and publish clicks are not blindly retried.

## Framework V1 Freeze

For the pilot, the browser framework v1 surface is frozen at:

- `BrowserProvider`;
- `BrowserSession`;
- `BrowserTarget`;
- provider-managed profile locks;
- provider-bound authentication state;
- generic human takeover;
- generic browser artifacts;
- provider selection through `ProviderResolver`;
- machine-readable plugin and provider health.

LinkedIn channel code must continue to depend only on the generic browser contracts. Auto Browser details stay inside `plugins/providers/auto_browser`, bootstrap, integration docs, and provider-specific tests.
