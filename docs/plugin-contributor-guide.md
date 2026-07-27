# Plugin Contributor Guide

Workflow: fork or checkout, create a Python 3.12 environment, scaffold a plugin, fill the manifest, create a deterministic fixture, implement runtime, register requirements and metrics, run contract tests, run doctor, generate compatibility report, run security scans, run opt-in integration tests, prepare pilot runbook, update changelog, and open a pull request.

Integration levels: deterministic fixture, local real service, external read-only service, and explicit pilot mutation. Pilot mutation never runs in default CI.

## Phase 18 distribution

Package releases as pure-Python wheels only. Do not include native extensions, source distributions, bundled SDK copies, production credentials, or runtime dependency installation. Registry browsing and package verification must not import plugin code. Installation is disabled by default; activation is a separate operator decision and requires restart. Signed does not mean safe.

## Phase 19 host compatibility

External plugins must work out of process. Use host callbacks for secrets, HTTP, media, browser, analytics, execution reporting, event, audit, clock, and scoped JSON state access. Do not rely on in-process globals, repository imports, or application singletons.

## Phase 20 sandbox compatibility

Design external channel plugins for broker-only access. Do not read local files directly, open sockets, spawn subprocesses, or expect repository paths. The sandbox hides `content/`, `drafts/`, home credentials, and other plugin state.

## Phase 21 owned publication

`channel.markdown_website` is a built-in reference for owned publication. It uses allowlisted repository references, normalized relative paths, exact Git path staging, deterministic frontmatter, revision binding, public URL verification, and content-bound funnel metrics. Community plugins should not copy private repository, credential, or raw path handling.
