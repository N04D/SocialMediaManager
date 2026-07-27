# Plugin Review and Release

Reviews check plugin id, type, capabilities, authentication, requirements, media formats, metric definitions, fixture, doctor, contract tests, integration tests, pilot status, security, privacy, framework contracts, changelog, and maintainer commitment.

Core SDK files require core maintainer review. Channel plugin changes require a plugin maintainer or channel owner. Security-sensitive auth and manifest schema changes require SDK review. Concrete maintainers are intentionally documented in manifests rather than hard-coded in CODEOWNERS.

## Phase 18 distribution

Package releases as pure-Python wheels only. Do not include native extensions, source distributions, bundled SDK copies, production credentials, or runtime dependency installation. Registry browsing and package verification must not import plugin code. Installation is disabled by default; activation is a separate operator decision and requires restart. Signed does not mean safe.

## Phase 20 sandbox review

Reviewers must verify permission-to-policy mapping, sandbox plan checksum binding, platform attestation, direct network denial, filesystem allowlist, violation handling, and development override audit behavior before approving community activation.

## Phase 21 owned publication review

Owned-publication review must verify deterministic rendering, safe frontmatter serialization, path allowlists, exact Git path staging, no force push, dirty worktree protection, public URL markers, dependency gates before social publishing, and exact content revision attribution for metrics.
