from __future__ import annotations

import struct

from channel_store import now_iso

from .errors import MediaValidationError
from .models import ImageInspectionResult
from .utils import sha256_bytes


class ImageInspector:
    inspector_id = "media.image.inspector.basic"

    def inspect_bytes(self, data: bytes, *, mime_type: str) -> ImageInspectionResult:
        normalized_mime = mime_type.strip().lower()
        try:
            if normalized_mime == "image/png":
                width, height = self._png_dimensions(data)
            elif normalized_mime == "image/jpeg":
                width, height = self._jpeg_dimensions(data)
            else:
                raise MediaValidationError(
                    "media.inspection_unsupported_mime",
                    "Image inspection only supports JPEG and PNG.",
                    {"mime_type": normalized_mime},
                )
        except MediaValidationError as exc:
            return ImageInspectionResult(
                mime_type=normalized_mime,
                width=0,
                height=0,
                file_size=len(data),
                checksum=sha256_bytes(data),
                status="failed",
                inspector_id=self.inspector_id,
                inspected_at=now_iso(),
                errors=(exc.code,),
            )
        return ImageInspectionResult(
            mime_type=normalized_mime,
            width=width,
            height=height,
            file_size=len(data),
            checksum=sha256_bytes(data),
            status="passed",
            inspector_id=self.inspector_id,
            inspected_at=now_iso(),
        )

    @staticmethod
    def _png_dimensions(data: bytes) -> tuple[int, int]:
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise MediaValidationError("media.invalid_png", "PNG data is not valid.")
        width, height = struct.unpack(">II", data[16:24])
        if width < 1 or height < 1:
            raise MediaValidationError("media.invalid_png_dimensions", "PNG dimensions are invalid.")
        return int(width), int(height)

    @staticmethod
    def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
        if len(data) < 4 or data[:2] != b"\xff\xd8":
            raise MediaValidationError("media.invalid_jpeg", "JPEG data is not valid.")
        index = 2
        while index + 9 <= len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            while index < len(data) and data[index] == 0xFF:
                index += 1
            if index >= len(data):
                break
            marker = data[index]
            index += 1
            if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
                continue
            if index + 2 > len(data):
                break
            segment_length = int.from_bytes(data[index : index + 2], "big")
            if segment_length < 2 or index + segment_length > len(data):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if segment_length < 7:
                    break
                height = int.from_bytes(data[index + 3 : index + 5], "big")
                width = int.from_bytes(data[index + 5 : index + 7], "big")
                if width < 1 or height < 1:
                    break
                return int(width), int(height)
            index += segment_length
        raise MediaValidationError("media.jpeg_dimensions_missing", "JPEG dimensions could not be inspected.")
