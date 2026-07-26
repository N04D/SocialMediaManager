# Sandbox Security Boundaries

The OS sandbox reduces impact; it does not prove a plugin is malware-free or incapable of escape. Kernel bugs, broker bugs, confused-deputy errors, and misuse of granted capabilities remain possible.

Sensitive operations stay brokered: HTTP, browser, secrets, media, analytics, execution reporting, events, audit, state, and clock.

Broker authorization still checks plugin ID, version, sandbox host, call context, workspace, account, operation, capability, permission, resource binding, and deadline.

Linux `OS sandbox enforced` means the current attestation verified namespace isolation, filesystem denial probes, network default-deny, `no_new_privs`, capability state, Landlock, seccomp, and the import gate. It still does not mean malware-free or impossible to escape.
