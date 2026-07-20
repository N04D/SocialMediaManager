from __future__ import annotations

from typing import Any


class MediaError(Exception):
    def __init__(self, code: str, user_message: str, details: dict[str, Any] | None = None, *, retryable: bool = False):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.details = details or {}
        self.retryable = retryable


class MediaValidationError(MediaError): ...


class MediaNotFoundError(MediaError): ...


class MediaUnavailableError(MediaError): ...


class MediaStorageError(MediaError): ...


class MediaStorageUnavailableError(MediaStorageError): ...


class MediaStorageConfigurationError(MediaStorageError): ...


class MediaStorageCapabilityError(MediaStorageError): ...


class MediaChecksumMismatchError(MediaValidationError): ...


class MediaMimeTypeError(MediaValidationError): ...


class MediaFileTooLargeError(MediaValidationError): ...


class MediaUnsafePathError(MediaValidationError): ...


class MediaOwnershipError(MediaValidationError): ...


class MediaMaterializationError(MediaStorageError): ...


class MediaDeleteConflictError(MediaStorageError): ...


class MediaProviderIncompatibleError(MediaStorageError): ...


class MediaVariantNotFoundError(MediaNotFoundError): ...
