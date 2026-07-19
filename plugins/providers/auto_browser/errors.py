from __future__ import annotations


class AutoBrowserError(RuntimeError):
    code = "auto_browser.error"

    def __init__(self, message: str = "", *, details: dict | None = None) -> None:
        super().__init__(message or "Auto Browser request failed.")
        self.details = details or {}


class AutoBrowserConnectionError(AutoBrowserError):
    code = "auto_browser.connection_error"


class AutoBrowserTimeoutError(AutoBrowserError):
    code = "auto_browser.timeout"


class AutoBrowserUnauthorizedError(AutoBrowserError):
    code = "auto_browser.unauthorized"


class AutoBrowserNotReadyError(AutoBrowserError):
    code = "auto_browser.not_ready"


class AutoBrowserVersionError(AutoBrowserError):
    code = "auto_browser.incompatible_version"


class AutoBrowserSessionNotFoundError(AutoBrowserError):
    code = "auto_browser.session_not_found"


class AutoBrowserSessionInterruptedError(AutoBrowserError):
    code = "auto_browser.session_interrupted"


class AutoBrowserTargetNotFoundError(AutoBrowserError):
    code = "auto_browser.target_not_found"


class AutoBrowserStaleElementError(AutoBrowserError):
    code = "auto_browser.stale_element"


class AutoBrowserApprovalRequiredError(AutoBrowserError):
    code = "auto_browser.approval_required"


class AutoBrowserUploadError(AutoBrowserError):
    code = "auto_browser.upload_failed"


class AutoBrowserTakeoverError(AutoBrowserError):
    code = "auto_browser.takeover_failed"


class AutoBrowserRateLimitError(AutoBrowserError):
    code = "auto_browser.rate_limited"


class AutoBrowserResponseError(AutoBrowserError):
    code = "auto_browser.response_error"
