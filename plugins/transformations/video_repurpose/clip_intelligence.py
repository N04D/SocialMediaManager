from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from plugins.transformations.video_repurpose.ffmpeg_boundary import FFmpegBoundaryError, run_ffmpeg
from src.core.content import TimelineSegment

SIGNAL_VERSION = "phase38_signal_v1"
FUSION_VERSION = "multimodal_fusion_v1"


@dataclass(frozen=True)
class ClipSignalResult:
    signal_id: str
    candidate_id: str
    start_time: float
    end_time: float
    score: float | None
    status: str = "available"
    confidence: float | None = None
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.status == "available":
            if self.score is None or not 0.0 <= self.score <= 1.0:
                raise ValueError("clip_signal.invalid_score")

    def available(self) -> bool:
        return self.status == "available"


@dataclass(frozen=True)
class AudioSignalWindow:
    start: float
    end: float
    energy: float
    silence_ratio: float


@dataclass(frozen=True)
class SceneChange:
    timestamp: float
    strength: float


@dataclass(frozen=True)
class FusionConfig:
    semantic_weight: float = 0.30
    hook_weight: float = 0.25
    completeness_weight: float = 0.20
    audio_weight: float = 0.10
    scene_weight: float = 0.10
    speaker_weight: float = 0.05

    def weights(self) -> dict[str, float]:
        return {
            "clip.signal.semantic": self.semantic_weight,
            "clip.signal.hook": self.hook_weight,
            "clip.signal.completeness": self.completeness_weight,
            "clip.signal.audio_energy": self.audio_weight,
            "clip.signal.scene_boundary": self.scene_weight,
            "clip.signal.speaker_boundary": self.speaker_weight,
        }

    def validate(self) -> None:
        values = self.weights()
        if any(weight < 0 for weight in values.values()):
            raise ValueError("clip_fusion.negative_weight")
        if not any(weight > 0 for weight in values.values()):
            raise ValueError("clip_fusion.no_active_weight")


@dataclass(frozen=True)
class RankedClipCandidate:
    candidate: Any
    final_score: float
    rank: int
    reason_summary: tuple[str, ...]
    signal_contributions: dict[str, float]
    signals_unavailable: tuple[str, ...]
    provenance: dict[str, Any]
    selection_status: str = "recommended"
    selected_at: str = ""
    user_adjustment: dict[str, Any] = field(default_factory=dict)

    def to_candidate_with_provenance(self) -> Any:
        provenance = dict(getattr(self.candidate, "provenance", {}) or {})
        provenance["ranking"] = self.provenance
        return replace(
            self.candidate,
            score=self.final_score,
            reason=" · ".join(self.reason_summary),
            provenance=provenance,
        )


CONTEXT_OPENERS = (
    "and then",
    "as i said",
    "like i said",
    "so anyway",
    "anyway",
    "this part",
    "that thing",
    "earlier",
)
HOOK_OPENERS = (
    "why ",
    "how ",
    "what ",
    "when ",
    "here is",
    "the simple",
    "the strongest",
    "the problem",
    "the mistake",
    "the reason",
    "imagine",
)
CONCLUSION_MARKERS = (
    "so ",
    "therefore",
    "that means",
    "the lesson",
    "in short",
    "remember",
    "finish",
)
PRONOUNS = {"it", "this", "that", "they", "those", "these", "he", "she"}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def first_sentence(text: str) -> str:
    normalized = normalize_text(text)
    parts = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)
    return parts[0] if parts else normalized


def tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9']+", text.lower())


def clamp_score(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def sentence_boundary_score(text: str) -> float:
    normalized = normalize_text(text)
    if not normalized:
        return 0.0
    score = 0.45
    if normalized[:1].isupper() or normalized.lower().startswith(("why ", "how ", "what ", "when ", "here ")):
        score += 0.22
    if normalized.endswith((".", "?", "!")):
        score += 0.25
    if normalized.lower().startswith(CONTEXT_OPENERS):
        score -= 0.24
    if normalized.endswith((",", ";", ":", "and", "but", "or")):
        score -= 0.30
    return clamp_score(score)


class SemanticSignalAnalyzer:
    signal_id = "clip.signal.semantic"

    def score(self, candidate: Any, segments: list[TimelineSegment]) -> ClipSignalResult:
        text = normalize_text(candidate.transcript_excerpt)
        words = tokens(text)
        lowered = text.lower()
        unique_ratio = len(set(words)) / max(len(words), 1)
        score = 0.42
        if len(words) >= 18:
            score += 0.15
        if unique_ratio >= 0.55:
            score += 0.08
        if any(marker in lowered for marker in (" means ", " is ", " are ", " because ", " lesson", " choose ")):
            score += 0.14
        if any(marker in lowered for marker in CONCLUSION_MARKERS) or text.endswith(("!", "?")):
            score += 0.10
        if lowered.startswith(CONTEXT_OPENERS):
            score -= 0.28
        elif any(marker in lowered for marker in CONTEXT_OPENERS):
            score -= 0.10
        if words[:1] and words[0] in PRONOUNS:
            score -= 0.18
        if len(set(words).intersection(PRONOUNS)) >= 4:
            score -= 0.08
        reason = "Complete standalone thought" if score >= 0.68 else "Needs source context"
        return self._result(
            candidate, clamp_score(score), reason, {"word_count": len(words), "unique_ratio": unique_ratio}
        )

    def _result(self, candidate: Any, score: float, reason: str, evidence: dict[str, Any]) -> ClipSignalResult:
        return ClipSignalResult(
            signal_id=self.signal_id,
            candidate_id=candidate.candidate_id,
            start_time=candidate.start_time,
            end_time=candidate.end_time,
            score=score,
            reason=reason,
            evidence=evidence,
            provenance={"strategy": SIGNAL_VERSION},
        )


class HookSignalAnalyzer:
    signal_id = "clip.signal.hook"

    def score(self, candidate: Any, segments: list[TimelineSegment]) -> ClipSignalResult:
        opening = first_sentence(candidate.transcript_excerpt)
        lowered = opening.lower()
        word_count = len(tokens(opening))
        score = 0.36
        if "?" in opening:
            score += 0.24
        if lowered.startswith(HOOK_OPENERS):
            score += 0.22
        if any(word in lowered for word in ("never", "mistake", "problem", "secret", "simple", "why", "how")):
            score += 0.10
        if 4 <= word_count <= 16:
            score += 0.08
        if lowered.startswith(CONTEXT_OPENERS):
            score -= 0.34
        if word_count > 24:
            score -= 0.12
        reason = "Strong opening" if score >= 0.68 else "Weak opening"
        return ClipSignalResult(
            signal_id=self.signal_id,
            candidate_id=candidate.candidate_id,
            start_time=candidate.start_time,
            end_time=candidate.end_time,
            score=clamp_score(score),
            reason=reason,
            evidence={"opening": opening, "word_count": word_count},
            provenance={"strategy": SIGNAL_VERSION},
        )


class CompletenessSignalAnalyzer:
    signal_id = "clip.signal.completeness"

    def score(self, candidate: Any, segments: list[TimelineSegment]) -> ClipSignalResult:
        text = normalize_text(candidate.transcript_excerpt)
        score = sentence_boundary_score(text)
        evidence: dict[str, Any] = {
            "starts_on_sentence_boundary": bool(text[:1].isupper())
            or text.lower().startswith(("why ", "how ", "what ", "when ", "here ")),
            "ends_on_sentence_boundary": text.endswith((".", "?", "!")),
        }
        if not evidence["starts_on_sentence_boundary"]:
            evidence["suggested_start"] = candidate.start_time
        if not evidence["ends_on_sentence_boundary"]:
            evidence["suggested_end"] = candidate.end_time
        reason = "Natural sentence boundaries" if score >= 0.70 else "Abrupt or incomplete boundary"
        return ClipSignalResult(
            signal_id=self.signal_id,
            candidate_id=candidate.candidate_id,
            start_time=candidate.start_time,
            end_time=candidate.end_time,
            score=score,
            reason=reason,
            evidence=evidence,
            provenance={"strategy": SIGNAL_VERSION},
        )


class SpeakerBoundarySignalAnalyzer:
    signal_id = "clip.signal.speaker_boundary"

    def score(self, candidate: Any, segments: list[TimelineSegment]) -> ClipSignalResult:
        speakers = [getattr(segment, "speaker", None) for segment in segments]
        if not any(speakers):
            return ClipSignalResult(
                signal_id=self.signal_id,
                candidate_id=candidate.candidate_id,
                start_time=candidate.start_time,
                end_time=candidate.end_time,
                score=None,
                status="unavailable",
                reason="Speaker labels unavailable",
                evidence={},
                provenance={"strategy": SIGNAL_VERSION},
            )
        overlapping = [
            speaker
            for segment, speaker in zip(segments, speakers, strict=False)
            if speaker
            and float(segment.start_time) < candidate.end_time
            and float(segment.end_time) > candidate.start_time
        ]
        score = 0.75 if len(set(overlapping)) <= 1 else 0.48
        return ClipSignalResult(
            signal_id=self.signal_id,
            candidate_id=candidate.candidate_id,
            start_time=candidate.start_time,
            end_time=candidate.end_time,
            score=score,
            reason="Single speaker passage" if score >= 0.7 else "Speaker changes inside candidate",
            evidence={"speakers": sorted(set(overlapping))},
            provenance={"strategy": SIGNAL_VERSION},
        )


class AudioEnergySignalAnalyzer:
    signal_id = "clip.signal.audio_energy"

    def analyze_source(self, media_path: Path) -> tuple[AudioSignalWindow, ...]:
        try:
            result = run_ffmpeg(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-i",
                    str(media_path),
                    "-af",
                    "silencedetect=noise=-35dB:d=0.30",
                    "-f",
                    "null",
                    "-",
                ],
                timeout=60,
            )
        except FFmpegBoundaryError:
            raise
        duration = self._duration_from_log(result.stderr)
        silences = self._parse_silences(result.stderr)
        if duration <= 0:
            return ()
        windows: list[AudioSignalWindow] = []
        window_size = 2.0
        cursor = 0.0
        while cursor < duration:
            end = min(duration, cursor + window_size)
            silence_ratio = self._silence_ratio(cursor, end, silences)
            windows.append(
                AudioSignalWindow(
                    start=round(cursor, 3),
                    end=round(end, 3),
                    energy=clamp_score(1.0 - silence_ratio),
                    silence_ratio=clamp_score(silence_ratio),
                )
            )
            cursor = end
        return tuple(windows)

    def score(self, candidate: Any, windows: Iterable[AudioSignalWindow] | None) -> ClipSignalResult:
        if windows is None:
            return self.unavailable(candidate, "Audio analysis unavailable")
        relevant = [
            window for window in windows if window.start < candidate.end_time and window.end > candidate.start_time
        ]
        if not relevant:
            return self.unavailable(candidate, "No audio windows overlap candidate")
        avg_energy = sum(window.energy for window in relevant) / len(relevant)
        avg_silence = sum(window.silence_ratio for window in relevant) / len(relevant)
        score = clamp_score(avg_energy - max(0.0, avg_silence - 0.25) * 0.35)
        reason = "Steady speech energy" if score >= 0.62 else "Long silence or low energy"
        return ClipSignalResult(
            signal_id=self.signal_id,
            candidate_id=candidate.candidate_id,
            start_time=candidate.start_time,
            end_time=candidate.end_time,
            score=score,
            reason=reason,
            evidence={
                "window_count": len(relevant),
                "average_energy": round(avg_energy, 4),
                "silence_ratio": round(avg_silence, 4),
                "windows": [asdict(window) for window in relevant[:5]],
            },
            provenance={"strategy": SIGNAL_VERSION, "analyzer": "ffmpeg_silencedetect"},
        )

    def unavailable(self, candidate: Any, reason: str) -> ClipSignalResult:
        return ClipSignalResult(
            signal_id=self.signal_id,
            candidate_id=candidate.candidate_id,
            start_time=candidate.start_time,
            end_time=candidate.end_time,
            score=None,
            status="unavailable",
            reason=reason,
            provenance={"strategy": SIGNAL_VERSION},
        )

    @staticmethod
    def _duration_from_log(log: str) -> float:
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", log)
        if not match:
            return 0.0
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    @staticmethod
    def _parse_silences(log: str) -> tuple[tuple[float, float], ...]:
        silences: list[tuple[float, float]] = []
        current: float | None = None
        for line in log.splitlines():
            start = re.search(r"silence_start:\s*([0-9.]+)", line)
            if start:
                current = float(start.group(1))
                continue
            end = re.search(r"silence_end:\s*([0-9.]+)", line)
            if end and current is not None:
                silences.append((current, float(end.group(1))))
                current = None
        return tuple(silences)

    @staticmethod
    def _silence_ratio(start: float, end: float, silences: Iterable[tuple[float, float]]) -> float:
        duration = max(end - start, 0.001)
        total = 0.0
        for silence_start, silence_end in silences:
            overlap = min(end, silence_end) - max(start, silence_start)
            if overlap > 0:
                total += overlap
        return max(0.0, min(1.0, total / duration))


class SceneBoundarySignalAnalyzer:
    signal_id = "clip.signal.scene_boundary"

    def analyze_source(self, media_path: Path) -> tuple[SceneChange, ...]:
        try:
            result = run_ffmpeg(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-i",
                    str(media_path),
                    "-vf",
                    "select='gt(scene,0.18)',showinfo",
                    "-f",
                    "null",
                    "-",
                ],
                timeout=60,
            )
        except FFmpegBoundaryError:
            raise
        changes = []
        for line in result.stderr.splitlines():
            match = re.search(r"pts_time:([0-9.]+)", line)
            if match:
                changes.append(SceneChange(timestamp=round(float(match.group(1)), 3), strength=0.7))
        return tuple(changes)

    def score(self, candidate: Any, changes: Iterable[SceneChange] | None) -> ClipSignalResult:
        if changes is None:
            return self.unavailable(candidate, "Scene analysis unavailable")
        changes = tuple(changes)
        if not changes:
            return self.unavailable(candidate, "No scene boundaries detected")
        nearest_start = min((abs(change.timestamp - candidate.start_time) for change in changes), default=math.inf)
        nearest_end = min((abs(change.timestamp - candidate.end_time) for change in changes), default=math.inf)
        start_bonus = max(0.0, 1.0 - nearest_start / 3.0)
        end_bonus = max(0.0, 1.0 - nearest_end / 3.0)
        score = clamp_score(0.35 + start_bonus * 0.35 + end_bonus * 0.20)
        reason = "Natural visual boundary" if score >= 0.62 else "No nearby visual boundary"
        return ClipSignalResult(
            signal_id=self.signal_id,
            candidate_id=candidate.candidate_id,
            start_time=candidate.start_time,
            end_time=candidate.end_time,
            score=score,
            reason=reason,
            evidence={
                "nearest_start_delta": None if math.isinf(nearest_start) else round(nearest_start, 3),
                "nearest_end_delta": None if math.isinf(nearest_end) else round(nearest_end, 3),
                "scene_changes": [asdict(change) for change in changes[:10]],
            },
            provenance={"strategy": SIGNAL_VERSION, "analyzer": "ffmpeg_scene_select"},
        )

    def unavailable(self, candidate: Any, reason: str) -> ClipSignalResult:
        return ClipSignalResult(
            signal_id=self.signal_id,
            candidate_id=candidate.candidate_id,
            start_time=candidate.start_time,
            end_time=candidate.end_time,
            score=None,
            status="unavailable",
            reason=reason,
            provenance={"strategy": SIGNAL_VERSION},
        )


class ClipSignalFusionRanker:
    def __init__(self, config: FusionConfig | None = None) -> None:
        self.config = config or FusionConfig()
        self.config.validate()

    def rank(self, candidates: list[Any], signals: dict[str, list[ClipSignalResult]]) -> list[RankedClipCandidate]:
        ranked = [self._rank_one(candidate, signals) for candidate in candidates]
        ranked.sort(key=lambda item: (-item.final_score, item.candidate.start_time))
        return [replace(item, rank=index) for index, item in enumerate(ranked, start=1)]

    def _rank_one(self, candidate: Any, signals: dict[str, list[ClipSignalResult]]) -> RankedClipCandidate:
        weights = self.config.weights()
        contributions: dict[str, float] = {}
        unavailable: list[str] = []
        reasons: list[str] = []
        weighted_total = 0.0
        active_total = 0.0
        for signal_id, weight in weights.items():
            if weight <= 0:
                continue
            signal = self._find_signal(signal_id, candidate.candidate_id, signals)
            if signal is None:
                unavailable.append(signal_id)
                continue
            signal.validate()
            if not signal.available():
                unavailable.append(signal_id)
                continue
            weighted_total += float(signal.score) * weight
            active_total += weight
            contributions[signal_id] = round(float(signal.score), 4)
            if signal.reason and len(reasons) < 5:
                reasons.append(signal.reason)
        if active_total <= 0:
            final_score = 0.0
        else:
            final_score = round(weighted_total / active_total, 4)
        return RankedClipCandidate(
            candidate=candidate,
            final_score=final_score,
            rank=0,
            reason_summary=tuple(dict.fromkeys(reasons)) or ("Baseline transcript ranking",),
            signal_contributions=contributions,
            signals_unavailable=tuple(unavailable),
            provenance={
                "ranking_strategy": FUSION_VERSION,
                "ranking_version": FUSION_VERSION,
                "signals_used": tuple(contributions),
                "signals_unavailable": tuple(unavailable),
                "weights": weights,
                "final_score": final_score,
            },
        )

    @staticmethod
    def _find_signal(
        signal_id: str, candidate_id: str, signals: dict[str, list[ClipSignalResult]]
    ) -> ClipSignalResult | None:
        return next(
            (signal for signal in signals.get(signal_id, []) if signal.candidate_id == candidate_id),
            None,
        )


def select_with_user_feedback(
    ranked: RankedClipCandidate,
    *,
    selected_at: str,
    adjusted_start: float | None = None,
    adjusted_end: float | None = None,
) -> RankedClipCandidate:
    adjustment: dict[str, Any] = {}
    if adjusted_start is not None or adjusted_end is not None:
        adjustment = {
            "original_start": ranked.candidate.start_time,
            "original_end": ranked.candidate.end_time,
            "adjusted_start": adjusted_start,
            "adjusted_end": adjusted_end,
            "status": "manually_adjusted",
        }
    return replace(
        ranked,
        selection_status="selected" if not adjustment else "manually_adjusted",
        selected_at=selected_at,
        user_adjustment=adjustment,
    )


__all__ = [
    "AudioEnergySignalAnalyzer",
    "AudioSignalWindow",
    "ClipSignalFusionRanker",
    "ClipSignalResult",
    "CompletenessSignalAnalyzer",
    "FusionConfig",
    "HookSignalAnalyzer",
    "RankedClipCandidate",
    "SceneBoundarySignalAnalyzer",
    "SceneChange",
    "SemanticSignalAnalyzer",
    "SpeakerBoundarySignalAnalyzer",
    "select_with_user_feedback",
]
