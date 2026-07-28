"""MCP-style helpers for trusted signers."""

from __future__ import annotations

from .service import TrustedSignerService


class TrustedSignerMCP:
    def __init__(self, service: TrustedSignerService | None = None) -> None:
        self.service = service or TrustedSignerService()

    def get_certification_signers(self) -> dict:
        return self.service.status()

    def get_certification_signer_health(self, signer_id: str) -> dict:
        return self.service.health(signer_id)

    def explain_signer_status(self, signer_id: str) -> dict:
        return self.service.health(signer_id)


__all__ = ["TrustedSignerMCP"]
