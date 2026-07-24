# Plugin Sandbox Architecture

External plugin activation now follows this sequence: verified installation, host environment preparation, sandbox policy compilation, immutable sandbox plan, platform capability inspection, sandbox preparation, sandboxed process launch, sandbox attestation, Plugin Host handshake, and proxy registration.

The external entrypoint is imported only inside the child runtime after sandbox attestation. There is no in-process fallback for external plugins. Built-in plugins remain in-process.
