# Community Plugin Security

Community plugins run as Python code in the application process after activation. Phase 18 does not provide sandboxing, subprocess isolation, dependency virtualization, resource limits, malware classification, or crash containment. Signatures prove provenance and integrity only. Future work should add out-of-process plugin hosting.
