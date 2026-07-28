"""Replay prevention helpers."""

from __future__ import annotations

from .errors import CertificationEvidenceError


def assert_no_replay(existing_checksum: str | None, incoming_checksum: str) -> None:
    if existing_checksum and existing_checksum != incoming_checksum:
        raise CertificationEvidenceError(
            "certification.replay_conflict", "Package ID replayed with a different checksum."
        )


__all__ = ["assert_no_replay"]
