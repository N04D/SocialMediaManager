"""Child runtime logging.

Stdout is reserved for JSON-RPC frames. Diagnostics are written to stderr in
small redacted lines.
"""

from __future__ import annotations

import sys


def log_safe(message: str) -> None:
    redacted = message.replace("token", "[redacted]").replace("secret", "[redacted]")
    print(redacted[:1000], file=sys.stderr, flush=True)


__all__ = ["log_safe"]
