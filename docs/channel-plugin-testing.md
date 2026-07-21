# Channel Plugin Testing

Use `plugin_sdk.testing.ChannelPluginContractSuite` and fake services for contract tests outside the full application. Profiles include channel.minimal, channel.api_first, channel.browser_based, channel.text_publish, channel.image_publish, channel.metrics, and channel.full.

The suite verifies manifest compatibility, idempotent registration, unsupported capabilities, secret-free payloads, execution reporting, media cleanup, analytics ingestion, health, integrity, and import boundaries.
