# Sandbox Security Boundaries

The OS sandbox reduces impact; it does not prove a plugin is malware-free or incapable of escape. Kernel bugs, broker bugs, confused-deputy errors, and misuse of granted capabilities remain possible.

Sensitive operations stay brokered: HTTP, browser, secrets, media, analytics, execution reporting, events, audit, state, and clock.

Broker authorization still checks plugin ID, version, sandbox host, call context, workspace, account, operation, capability, permission, resource binding, and deadline.
