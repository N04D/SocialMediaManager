# Plugin Manifest v1

Manifest schema version `1.0` is published at `schemas/plugin-manifest-v1.schema.json`. Plugin ids are lowercase namespaced ids such as `channel.example`, `provider.browser.example`, and `media.image.example`.

The manifest declares SDK version, framework contract versions, capabilities, dependencies, optional dependencies, high-level permissions, distribution, maintainers, license, repository, documentation, health metadata, configuration schema, and secret declarations. Secret defaults and absolute paths are rejected. Missing maintainers are allowed locally but produce release-readiness warnings.
