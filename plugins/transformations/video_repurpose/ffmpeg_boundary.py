from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class FFmpegBoundaryError(RuntimeError):
    pass


@dataclass(frozen=True)
class FFmpegResult:
    args: tuple[str, ...]
    stdout: str
    stderr: str


def run_ffmpeg(args: list[str], *, timeout: int = 60) -> FFmpegResult:
    if not args or args[0] != "ffmpeg":
        raise FFmpegBoundaryError("ffmpeg_boundary.invalid_binary")
    if any(part == "" for part in args):
        raise FFmpegBoundaryError("ffmpeg_boundary.empty_arg")
    result = subprocess.run(args, capture_output=True, check=False, text=True, timeout=timeout)
    if result.returncode != 0:
        raise FFmpegBoundaryError(result.stderr.strip() or "ffmpeg_boundary.failed")
    return FFmpegResult(args=tuple(args), stdout=result.stdout, stderr=result.stderr)


def run_ffprobe_json(args: list[str], *, timeout: int = 20) -> dict[str, Any]:
    if not args or args[0] != "ffprobe":
        raise FFmpegBoundaryError("ffmpeg_boundary.invalid_binary")
    if any(part == "" for part in args):
        raise FFmpegBoundaryError("ffmpeg_boundary.empty_arg")
    result = subprocess.run(args, capture_output=True, check=False, text=True, timeout=timeout)
    if result.returncode != 0:
        raise FFmpegBoundaryError(result.stderr.strip() or "ffprobe_boundary.failed")
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FFmpegBoundaryError("ffprobe_boundary.invalid_json") from exc


def ensure_managed_path(path: Path, *, root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if root_resolved != resolved and root_resolved not in resolved.parents:
        raise FFmpegBoundaryError("ffmpeg_boundary.path_outside_managed_root")
    return resolved
