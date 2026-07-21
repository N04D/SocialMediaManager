# Plugin Capabilities

Core channel capabilities are `channel.connect`, `channel.disconnect`, `channel.status`, `channel.publish.text`, `channel.publish.image`, `channel.metrics.collect`, and `channel.health`. Future channel capabilities such as video, polls, replies, update, delete, and messages are reserved and must not be claimed until introduced.

Custom capabilities must be namespaced below the plugin id, for example `channel.example.custom_operation`. Permissions are review metadata: outbound_network, browser_session, secret_storage, media_read, media_materialization, analytics_ingestion, execution_reporting, and account_configuration.
