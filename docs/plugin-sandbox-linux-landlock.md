# Linux Landlock

Landlock is applied as defense around the sandbox filesystem view. The controller detects the active Landlock ABI and must not report newer rights than the running kernel supports.

Policy intent is default-deny filesystem access, read-only access to code and runtime, write only to plugin temp and active transfers, no device creation, no mount rights, and no rename, link, or reparent escape from allowed trees.

Older or unavailable Landlock ABIs make production activation incomplete for community plugins.

Phase 20.1 detects the ABI with `landlock_create_ruleset(..., LANDLOCK_CREATE_RULESET_VERSION)`, builds only access bits supported by the active ABI, adds path-beneath rules for runtime and temp/transfer paths, calls `landlock_restrict_self`, and then runs denial probes. The docs and API report supported ABI, requested access, enforced access, and missing access separately.
