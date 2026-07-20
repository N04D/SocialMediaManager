# Browser Framework Changelog

## v1.0.0

- Introduced central `PluginRuntime` and provider resolution.
- Registered `provider.browser.legacy`.
- Registered `provider.browser.autobrowser`.
- Stabilized `BrowserProvider`, `BrowserSession`, `BrowserTarget`, and `BrowserArtifact`.
- Moved LinkedIn connect, session check, publish, metrics, and scraping behind provider-independent browser contracts.
- Added provider-managed profile locking.
- Added generic human takeover.
- Added generic browser artifacts.
- Added safe shared-volume uploads.
- Added provider-bound authentication state.
- Added session reconciliation and startup recovery.
- Added Auto Browser global and per-account kill switches.
- Added pilot readiness and controlled pilot evidence APIs.

Known limitations:

- Legacy remains the default provider.
- Auto Browser remote auth-profile delete is optional; logical revoke is used when unavailable.
- Image upload through Auto Browser requires a shared upload volume.
- Pipeline article/staging is outside Browser Framework v1.
- Multi-host locking requires a shared lock backend.
- Real browser workflows remain sensitive to LinkedIn UI changes.
