"""Technical consent modes for instrumentation."""

VALID_CONSENT_MODES = {"disabled", "always_enabled", "after_external_consent"}


def default_consent_allowed(mode: str) -> bool:
    if mode not in VALID_CONSENT_MODES:
        return False
    return mode == "always_enabled"


__all__ = ["VALID_CONSENT_MODES", "default_consent_allowed"]
