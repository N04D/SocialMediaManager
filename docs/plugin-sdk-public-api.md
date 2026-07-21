# Plugin SDK Public API

Stable API: contract constants, PluginManifest, capabilities, permissions, ChannelPlugin, ChannelRuntime, ChannelRuntimeContext, publish models, auth models, content/media facades, analytics ingestion facade, execution reporter, health and integrity models, fake services, and the contract testkit.

Internal API without compatibility guarantees: repository implementations, JSON stores, dashboard routes, worker loops, concrete providers, eventbus storage, audit storage, and helpers in internal or private namespaces. These are not exported by `plugin_sdk`.
