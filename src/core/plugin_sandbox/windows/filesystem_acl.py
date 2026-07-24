"""Windows filesystem ACL policy metadata."""

from __future__ import annotations


def acl_policy_summary() -> dict[str, str]:
    return {"environment": "read_only", "temp": "scoped_rw", "home": "deny", "content": "deny", "drafts": "deny"}


__all__ = ["acl_policy_summary"]
