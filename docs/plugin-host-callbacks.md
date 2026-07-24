# Plugin Host Callbacks

Plugins reach application services only through scoped callbacks. `PluginHostCallContext` binds host session, plugin, version, workspace, account, operation, capability, publication target, execution attempt, deadline, allowed callbacks, secrets, media, and browser provider. Late or cross-scope callbacks are rejected.
