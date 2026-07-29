"""Call-scoped secret lease wrappers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .models import SecretLease


@dataclass
class SecretLeaseValue:
    lease: SecretLease
    value: bytearray
    _release: Callable[[SecretLease], None]

    def text(self) -> str:
        return bytes(self.value).decode("utf-8")

    def bytes(self) -> bytes:
        return bytes(self.value)

    def close(self) -> None:
        for index in range(len(self.value)):
            self.value[index] = 0
        self._release(self.lease)

    def __enter__(self) -> SecretLeaseValue:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()

    def __repr__(self) -> str:
        return f"SecretLeaseValue(reference={self.lease.secret_reference_id!r}, redacted=True)"


__all__ = ["SecretLeaseValue"]
