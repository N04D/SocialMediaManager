"""Safe error types for Markdown Website publishing."""

from __future__ import annotations


class MarkdownWebsiteError(Exception):
    """Base error with a safe machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


class MarkdownWebsiteConfigError(MarkdownWebsiteError): ...


class MarkdownWebsitePathError(MarkdownWebsiteError): ...


class MarkdownWebsiteRenderError(MarkdownWebsiteError): ...


class MarkdownWebsiteGitError(MarkdownWebsiteError): ...


class MarkdownWebsiteVerificationError(MarkdownWebsiteError): ...


class MarkdownWebsiteDependencyError(MarkdownWebsiteError): ...
