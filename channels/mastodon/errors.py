from __future__ import annotations

from typing import Any


class MastodonError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        retryable: bool = False,
        mutation_state: str = "not_started",
        http_status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable
        self.mutation_state = mutation_state
        self.http_status = http_status
        self.details = _redact(details or {})


def _redact(payload: Any) -> Any:
    if isinstance(payload, dict):
        safe = {}
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(secret in lowered for secret in ("token", "secret", "code", "verifier", "authorization")):
                safe[str(key)] = "[REDACTED]"
            else:
                safe[str(key)] = _redact(value)
        return safe
    if isinstance(payload, list):
        return [_redact(item) for item in payload]
    if isinstance(payload, str) and len(payload) > 500:
        return payload[:500] + "..."
    return payload


class MastodonConfigurationError(MastodonError):
    pass


class MastodonUnsafeInstanceError(MastodonError):
    pass


class MastodonInstanceUnreachableError(MastodonError):
    pass


class MastodonInstanceIncompatibleError(MastodonError):
    pass


class MastodonOAuthError(MastodonError):
    pass


class MastodonOAuthStateError(MastodonOAuthError):
    pass


class MastodonOAuthExpiredError(MastodonOAuthError):
    pass


class MastodonTokenError(MastodonError):
    pass


class MastodonScopeError(MastodonError):
    pass


class MastodonAccountMismatchError(MastodonError):
    pass


class MastodonRateLimitError(MastodonError):
    pass


class MastodonApiError(MastodonError):
    pass


class MastodonResponseValidationError(MastodonError):
    pass


class MastodonContentRequirementError(MastodonError):
    pass


class MastodonMediaRequirementError(MastodonError):
    pass


class MastodonMediaProcessingError(MastodonError):
    pass


class MastodonPublishError(MastodonError):
    pass


class MastodonPublishUncertainError(MastodonPublishError):
    pass


class MastodonRemoteStatusNotFoundError(MastodonError):
    pass


class MastodonMetricsError(MastodonError):
    pass
