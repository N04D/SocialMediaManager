# Plugin Host Framework v0.1

External community plugins run in a separate process and versioned virtual environment. The host process registers local proxies only; it does not import external entrypoints. Signed, compatible, or installed plugins are not automatically trusted or enabled.

Phase 20 adds an OS Sandbox Framework gate before external plugin import. External plugins now require a compiled sandbox plan, platform preparation, and sandbox attestation before the JSON-RPC handshake may complete. If a required sandbox control is unavailable, community activation fails closed unless a local development override is explicitly enabled.
