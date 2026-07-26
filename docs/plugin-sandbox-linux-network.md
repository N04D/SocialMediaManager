# Linux Network Sandbox

Each external plugin host uses direct network default-deny. `outbound_network` means brokered HTTP through the controller-side `host.http.request` callback.

The sandbox policy blocks direct TCP, direct UDP, listening sockets, host loopback access, plugin-side DNS, and host Unix sockets where technically blockable. Browser traffic remains brokered through `host.browser.*`.

Phase 20.1 requires a real network namespace for production readiness. The doctor distinguishes `network_default_deny` as configured from network namespace creation as verified. If UID/GID mapping prevents network namespace setup, activation remains fail-closed.
