# Community Plugin Security

Community plugins are Python code and still require operator trust. Phase 18 did not provide sandboxing, subprocess isolation, dependency virtualization, resource limits, malware classification, or crash containment. Signatures prove provenance and integrity only.

Phase 19 changes external community plugins to run out of process in per-version virtual environments. This provides crash containment and dependency isolation, but it is still not a full OS sandbox and does not completely block direct filesystem or socket access.
