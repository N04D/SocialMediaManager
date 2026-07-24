"""Length-prefixed JSON-RPC framing."""

from __future__ import annotations

import json
import struct
from typing import Any, BinaryIO

from .errors import PluginHostFrameError

DEFAULT_MAX_FRAME_BYTES = 1024 * 1024


def encode_frame(payload: dict[str, Any], *, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > max_frame_bytes:
        raise PluginHostFrameError("plugin_host.frame.too_large", "RPC frame exceeds the configured limit.")
    return struct.pack(">I", len(body)) + body


def read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise PluginHostFrameError("plugin_host.frame.eof", "RPC stream ended before a complete frame.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def decode_frame(stream: BinaryIO, *, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> dict[str, Any]:
    header = read_exact(stream, 4)
    (length,) = struct.unpack(">I", header)
    if length > max_frame_bytes:
        raise PluginHostFrameError("plugin_host.frame.too_large", "RPC frame exceeds the configured limit.")
    try:
        payload = json.loads(read_exact(stream, length).decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise PluginHostFrameError("plugin_host.frame.invalid_utf8", "RPC frame is not valid UTF-8.") from exc
    except json.JSONDecodeError as exc:
        raise PluginHostFrameError("plugin_host.frame.invalid_json", "RPC frame is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise PluginHostFrameError("plugin_host.frame.invalid_payload", "RPC frame payload must be an object.")
    return payload


__all__ = ["DEFAULT_MAX_FRAME_BYTES", "decode_frame", "encode_frame", "read_exact"]
