from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integrations.managed_secrets.fixtures import encrypted_facade
from src.core.managed_secrets.errors import ManagedSecretError


class ManagedSecretApprovalsPhase30Test(unittest.TestCase):
    def test_roles_four_eyes_version_bound_approval_and_lease_purpose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            facade = encrypted_facade(root / "app.sqlite", root / "vault")
            facade.authz.grant_role("alice", "secret_operator")
            facade.authz.grant_role("bob", "security_approver")
            secret = facade.create_reference(
                secret_type="github_read_only_token",
                display_name="CI read token",
                purpose_allowlist=("github_actions_read",),
                created_by="alice",
            )["secret"]
            facade.set_value(secret["id"], b"ghp_synthetic_read_only", actor="alice")
            validated = facade.validate(secret["id"])["secret"]
            with self.assertRaises(ManagedSecretError) as self_approval:
                facade.approve(
                    secret["id"],
                    action_type="approve_github_credential",
                    requester_id="alice",
                    approver_id="alice",
                )
            self.assertEqual(self_approval.exception.code, "operator.role_required")
            facade.approve(
                secret["id"],
                action_type="approve_github_credential",
                requester_id="alice",
                approver_id="bob",
            )
            active = facade.activate(secret["id"], action_type="approve_github_credential")["secret"]
            self.assertEqual(active["status"], "active")
            with facade.acquire(secret["id"], "github_actions_read", consumer="github_actions") as lease:
                self.assertEqual(lease.text(), "ghp_synthetic_read_only")
            with self.assertRaises(ManagedSecretError):
                facade.acquire(secret["id"], "certification_signing", consumer="wrong")
            self.assertNotEqual(validated["safe_fingerprint"], "")


if __name__ == "__main__":
    unittest.main()
