# Plugin Lifecycle

Plugins move through discovered, manifest_validated, compatibility_checked, dependencies_resolved, registered, initialized, ready/degraded/disabled, and shutdown. Incompatible plugins are not initialized. Disabled plugins are not resolved. Initialization failure must rollback partial service registration.
