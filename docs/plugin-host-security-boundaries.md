# Plugin Host Security Boundaries

External code does not run in the main process. Process isolation contains crashes and hangs, while callbacks are the supported route to secrets, HTTP, media, browser, analytics, execution reporting, events, audit, state, and clock. Filesystem and network access are not fully isolated without a future OS sandbox.
