# Plugin Fixtures and Doctors

Fixture convention: `integrations/<plugin-id>/fixture_server.py` or `fixture_site.py`, `doctor.py`, `README.md`, and deterministic scenarios. Scenarios cover healthy, auth failure, rate limit, malformed response or UI state, pre-mutation failure, post-mutation uncertainty, and metrics.

Doctor commands are read-only, safe when config is missing, emit PASS/WARN/FAIL, redact secrets, publish nothing, delete nothing, and document exit codes. Real connectivity checks must be explicitly opt-in and read-only.
