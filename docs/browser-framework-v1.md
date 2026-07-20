# Browser Framework v1.0.0

Browser Framework v1 is the stable browser boundary for channel plugins. The framework lets a channel use browser automation without importing a concrete provider such as Playwright, Legacy Browser, or Auto Browser.

## Architecture

- `PluginRuntime` owns one runtime registry and concrete plugin services.
- `PluginRegistry` validates manifests, indexes capabilities, and checks dependencies.
- `ProviderResolver` selects a ready provider by capability and optional account preference.
- `BrowserProvider` creates sessions, reports profile status, performs health checks, handles human takeover, and owns profile locking.
- `BrowserSession` exposes provider-independent browser operations.
- `BrowserTarget` models semantic target lookup first, with CSS and XPath as fallbacks.
- `BrowserArtifact`, `BrowserSessionOptions`, and `HumanTakeoverRequest` are the stable data exchange models.
- Provider-bound authentication state keeps legacy and Auto Browser auth status separate.
- Reconciliation detects stale local mappings, owned orphaned remote sessions, and inconsistent provider state.
- Kill switches block Auto Browser globally or per account without changing content.

## Responsibilities

Core:

- plugin contracts and lifecycle;
- capability resolution;
- generic browser models;
- generic browser and plugin errors;
- contract version constants.

Browser provider:

- browser infrastructure;
- sessions and profile ownership;
- provider-managed profile locking;
- browser navigation and interaction;
- shared upload transfer;
- browser artifacts;
- human takeover;
- provider health and reconciliation.

Channel plugin:

- platform targets and navigation;
- login detection;
- publishing, scraping, and metrics semantics;
- platform-specific error classification;
- result verification.

UI and workers:

- fetch runtime services;
- start jobs;
- show safe status;
- avoid concrete provider implementation imports.

## Contract Versions

Central constants live in `src/core/browser/contracts.py`:

- `BROWSER_FRAMEWORK_VERSION = "1.0.0"`
- `BROWSER_PROVIDER_CONTRACT_VERSION = "1.0"`
- `BROWSER_SESSION_CONTRACT_VERSION = "1.0"`
- `BROWSER_TARGET_CONTRACT_VERSION = "1.0"`
- `BROWSER_ARTIFACT_CONTRACT_VERSION = "1.0"`

Provider manifests must declare these versions in `config_schema`. Provider health must report the implemented and required contract versions plus compatibility: `compatible`, `compatible_with_warnings`, or `incompatible`.

## BrowserProvider v1

`create_session(options)`: creates one exclusive provider-managed session. It acquires the profile lock before starting remote/local browser infrastructure. On partial failure it releases the lock and attempts remote cleanup. Not blindly retryable.

`close_session(session_id)`: closes a session by local session ID. Close is idempotent in intent; close timeouts must not leave a permanent local lock.

`get_session(session_id)`: returns the live local session or `None`. No remote lookup side effect is required.

`profile_status(profile_id)`: returns profile availability and stale lock state. Read-only.

`health_check()`: read-only provider health. It must not open a real channel account or publish content.

`request_human_takeover(request)`: creates a generic takeover reference. It must not expose bearer tokens, remote viewer secrets, or provider-internal IDs to channel code.

## BrowserSession v1

Active v1 methods:

- `navigate`, `snapshot`, `current_url`, `title`;
- `element_exists`, `element_visible`, `element_enabled`, `count`;
- `text_content`, `attribute`;
- `wait_for`, `wait_for_timeout`, `wait_for_load_state`;
- `reload`, `go_back`;
- `keyboard_press`, `keyboard_insert_text`;
- `click`, `clear`, `hover`, `fill`, `upload`;
- `evaluate`, `screenshot`, `close`.

All methods must reject actions on closed sessions with a generic `BrowserSessionError`. Provider-specific exceptions are translated to generic browser errors. Mutating methods such as `click`, `upload`, and `evaluate` are not blindly retryable unless the provider can prove idempotence and the channel verifies the remote result.

Unsupported operations must fail with a safe generic error and be visible in provider health.

## Target Policy

Target strategy priority:

1. role plus accessible name;
2. label;
3. test ID;
4. placeholder, title, or alt text;
5. visible text;
6. stable attribute;
7. CSS fallback;
8. XPath last resort.

Selectors live in channel plugins. Providers resolve targets but do not own platform selectors.

## Stable Boundaries

LinkedIn channel runtime must not import concrete providers. Dashboard and worker call the registered channel runtime or runtime resolver. Pipeline article/staging remains outside Browser Framework v1 and is governed by the pipeline ADR.

After v1.0.0, existing methods can only change under the versioning policy in `docs/browser-framework-versioning.md`.
