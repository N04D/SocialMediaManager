"""Fake GitHub server placeholder.

Phase 29 tests use an in-process read-only source rather than a real HTTP
server, keeping required CI free of credentials and external network.
"""

FAKE_GITHUB_SERVER_MODE = "in_process_read_only"
