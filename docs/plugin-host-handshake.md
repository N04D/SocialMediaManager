# Plugin Host Handshake

The controller sends `host.initialize` with protocol, SDK, expected plugin identity, manifest checksum, artifact checksum, entrypoint, capabilities, permissions, frame size, nonce, and environment checksum. The child returns `plugin.ready`; mismatches quarantine the plugin and no in-process fallback is attempted.
