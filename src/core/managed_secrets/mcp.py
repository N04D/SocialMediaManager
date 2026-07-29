"""MCP metadata helpers for managed secrets."""

from __future__ import annotations

from .service import configured_managed_secret_facade


class ManagedSecretsMcp:
    def __init__(self) -> None:
        self.facade = configured_managed_secret_facade()

    def get_managed_secret_references(self) -> dict:
        return self.facade.status()

    def get_secret_health(self, reference_id: str) -> dict:
        return self.facade.health(reference_id)

    def get_secret_consumers(self, reference_id: str) -> dict:
        return {"secret_reference_id": reference_id, "consumers": (), "secret_value_access": "never_exposed"}

    def get_secret_approval_status(self, reference_id: str) -> dict:
        reference = self.facade.repository.get_reference(reference_id)
        return {
            "secret_reference_id": reference_id,
            "status": reference["status"],
            "approved_by": reference["approved_by"],
        }

    def get_vault_health(self) -> dict:
        return self.facade.vault_health()

    def explain_secret_failure(self, reference_id: str) -> dict:
        return {"secret_reference_id": reference_id, "diagnostic": self.facade.health(reference_id)}

    def explain_signer_activation_blocker(self, reference_id: str) -> dict:
        return {"secret_reference_id": reference_id, "blockers": self.facade.health(reference_id)}

    def explain_ci_credential_status(self, reference_id: str) -> dict:
        return {
            "secret_reference_id": reference_id,
            "purpose": "github_actions_read",
            "health": self.facade.health(reference_id),
        }


__all__ = ["ManagedSecretsMcp"]
