"""
Clip selection engine for CustosAI Clipper.

Scores windows of the transcript by speech density, speech coverage, and
visual dynamism (scene change density). Pure Python — no LLM or external
service required.

TikTok Optimizations:
- Dynamic duration based on content type detection
- Emotion/sentiment analysis in scoring
- Hook detection for retention optimization
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from src.engine.ai_transcriber import Segment

logger = logging.getLogger(__name__)

_WORD_DENSITY_WEIGHT = 0.40
_COVERAGE_WEIGHT = 0.30
_SCENE_DENSITY_WEIGHT = 0.30
_WINDOW_STEP_S = 2.0

# Content type patterns for TikTok optimization
_CONTENT_TYPE_PATTERNS = {
    "quick_tip": {
        "patterns": [
            r"\btrick\b", r"\btip\b", r"\bhack\b", r"\bhow to\b", 
            r"\btruco\b", r"\bconsejo\b", r"\bcomo\s+hacer\b",
            r"\bdica\b", r"\btruque\b", r"\btutorial\b",
        ],
        "optimal_duration": (15, 25),  # Quick tips work best short
    },
    "storytime": {
        "patterns": [
            r"\bstorytime\b", r"\bcuento\b", r"\bhistoria\b", r"\bme pas[oó]\b",
            r"\bstory\s*time\b", r"\bel otro d[ií]a\b", r"\buna vez\b",
        ],
        "optimal_duration": (45, 60),  # Stories need more time
    },
    "reaction": {
        "patterns": [
            r"\breaction\b", r"\breacci[oó]n\b", r"\breacting\b", r"\breact\b",
            r"\bmira esto\b", r"\bves esto\b",
        ],
        "optimal_duration": (30, 45),
    },
    "pov": {
        "patterns": [
            r"\bpov\s*:?\b", r"\bpoint of view\b", r"\bcuando\s+eres\b",
            r"\bese momento\b",
        ],
        "optimal_duration": (15, 30),
    },
    "transformation": {
        "patterns": [
            r"\btransformation\b", r"\bantes\s+y\s+despu[eé]s\b", r"\bantes y despues\b",
            r"\bresultado\b", r"\bantes de\b",
        ],
        "optimal_duration": (20, 35),
    },
    "ranking": {
        "patterns": [
            r"\branking\b", r"\btop\s+\d+\b", r"\bmejores\b", r"\bpeores\b",
            r"\brating\b", r"\bpuntuando\b", r"\bvalorando\b",
        ],
        "optimal_duration": (30, 50),
    },
}

# Emotion indicators for engagement scoring
_EMOTION_INDICATORS = {
    "laughter": ["jaja", "lol", "lmao", "haha", "risa", "gracioso", "funny"],
    "surprise": ["wow", "oh my", "omg", "no way", "incre[ií]ble", "omg", "que\s+"],
    "excitement": ["yes!", "let's go", "vamos", "vamo", "yeah", "woohoo", "woohoo"],
    "controversy": ["wrong", "lie", "truth", "mentira", "verdad", "mal", "bien"],
}


@dataclass
class ClipRegion:
    start: float
    end: float
    score: float
    segments: list[Segment] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


def _detect_content_type(segments: list[Segment]) -> tuple[str, tuple[int, int]]:
    """
    Detect content type from transcript patterns.
    Returns (content_type, (min_duration, max_duration)).
    """
    full_text = " ".join([s.get("text", "").lower() for s in segments])
    
    for content_type, config in _CONTENT_TYPE_PATTERNS.items():
        for pattern in config["patterns"]:
            if re.search(pattern, full_text):
                return content_type, config["optimal_duration"]
    
    # Default: general content
    return "general", (25, 45)


def _calculate_emotion_score(segments: list[Segment], start: float, end: float) -> float:
    """Calculate emotion engagement score for a time window."""
    text = " ".join([
        s.get("text", "").lower() 
        for s in segments 
        if start <= s.get("start", 0) < end
    ])
    
    score = 0.0
    for emotion_type, indicators in _EMOTION_INDICATORS.items():
        for indicator in indicators:
            if re.search(indicator, text):
                if emotion_type == "laughter":
                    score += 2.0  # Laughter is highly engaging
                elif emotion_type == "surprise":
                    score += 1.5
                elif emotion_type == "excitement":
                    score += 1.0
                elif emotion_type == "controversy":
                    score += 1.2
    
    return score


def _calculate_tiktok_score(
    region: ClipRegion,
    segments: list[Segment],
    optimal_duration: tuple[int, int],
) -> float:
    """
    Calculate TikTok-specific score boost for a region.
    Considers: duration match, emotion, engagement patterns.
    """
    duration = region.end - region.start
    min_opt, max_opt = optimal_duration
    
    score = 0.0
    
    # Duration match bonus
    if min_opt <= duration <= max_opt:
        score += 2.0  # Perfect duration
    elif duration < min_opt:
        score -= (min_opt - duration) * 0.1  # Slight penalty for too short
    elif duration > max_opt:
        score -= (duration - max_opt) * 0.15  # Penalty for too long
    
    # Emotion score
    emotion_score = _calculate_emotion_score(segments, region.start, region.end)
    score += emotion_score
    
    # Hook at start bonus (check first 5 seconds)
    first_5s_text = " ".join([
        s.get("text", "").lower()
        for s in segments
        if region.start <= s.get("start", 0) < region.start + 5
    ])
    
    hook_keywords = [
        "imagine", "what if", "did you know", "secret", "surprising",
        "increible", "sorprendente", "secreto", "sabias que", "imagina",
    ]
    if any(kw in first_5s_text for kw in hook_keywords):
        score += 3.0  # Strong hook at start
    
    return score


def select_clips(
    segments: list[Segment],
    video_duration: float,
    clip_length: int = 45,
    max_clips: int = 5,
    merge_gap: float = 5.0,
    scene_changes: Optional[list[float]] = None,
    optimize_for_tiktok: bool = True,
) -> list[ClipRegion]:
    """
    Select the best clip regions from a transcript + scene data.

    Slides a window of *clip_length* seconds across the timeline, scores
    each position by speech density, coverage, and scene-change density,
    then returns up to *max_clips* non-overlapping regions ranked by score.

    Args:
        segments:       Transcript segments from Whisper.
        video_duration: Total video length in seconds.
        clip_length:    Target clip duration (30-60s).
        max_clips:      Maximum number of clips to return.
        merge_gap:      Merge windows closer than this (seconds).
        scene_changes:  Sorted list of scene-change timestamps (seconds).
                        Pass ``None`` to use speech-only scoring.
        optimize_for_tiktok: If True, applies TikTok-specific optimizations.

    Returns:
        List of ``ClipRegion`` sorted by start time.
    """
    if not segments or video_duration <= 0:
        return []
    
    # Detect content type for dynamic duration optimization
    content_type, optimal_duration = _detect_content_type(segments)
    logger.info(f"Detected content type: {content_type}, optimal duration: {optimal_duration}")
    
    # Adjust clip_length based on content type if TikTok optimization enabled
    if optimize_for_tiktok:
        target_duration = (optimal_duration[0] + optimal_duration[1]) // 2
        clip_length = max(10, min(target_duration, int(video_duration)))
        logger.info(f"TikTok optimization: adjusted clip length to {clip_length}s")

    clip_length = max(10, min(clip_length, int(video_duration)))

    windows = _score_windows(
        segments, video_duration, clip_length, scene_changes or []
    )
    if not windows:
        return []
    
    # Apply TikTok-specific scoring
    if optimize_for_tiktok:
        for window in windows:
            tiktok_boost = _calculate_tiktok_score(window, segments, optimal_duration)
            window.score += tiktok_boost * 0.1  # Weight TikTok factors at 10%

    selected = _non_max_suppression(windows, max_clips)
    merged = _merge_nearby(selected, merge_gap, video_duration)
    merged = _snap_to_sentences(merged, segments, video_duration)

    for region in merged:
        region.segments = _segments_in_range(segments, region.start, region.end)

    merged.sort(key=lambda r: r.start)

    logger.info(
        "Selected %d clip(s) from %d scored windows (content: %s)", 
        len(merged), len(windows), content_type
    )
    return merged


def _score_windows(
    segments: list[Segment],
    video_duration: float,
    clip_length: int,
    scene_changes: list[float],
) -> list[ClipRegion]:
    """Slide a window across the timeline and score each position."""
    use_scenes = len(scene_changes) > 0

    # Pre-compute max scene count across all windows for normalisation
    max_scenes_in_any_window = 0
    if use_scenes:
        sc = sorted(scene_changes)
        t = 0.0
        while t + clip_length <= video_duration:
            count = _count_in_range(sc, t, t + clip_length)
            if count > max_scenes_in_any_window:
                max_scenes_in_any_window = count
            t += _WINDOW_STEP_S

    windows: list[ClipRegion] = []
    t = 0.0

    while t + clip_length <= video_duration:
        w_start = t
        w_end = t + clip_length

        total_words = 0
        speech_duration = 0.0

        for seg in segments:
            overlap_start = max(seg["start"], w_start)
            overlap_end = min(seg["end"], w_end)
            if overlap_start >= overlap_end:
                continue

            overlap = overlap_end - overlap_start
            seg_duration = seg["end"] - seg["start"]
            if seg_duration <= 0:
                continue

            fraction = overlap / seg_duration
            total_words += int(len(seg["text"].split()) * fraction)
            speech_duration += overlap

        word_density = total_words / clip_length
        coverage = speech_duration / clip_length

        if use_scenes and max_scenes_in_any_window > 0:
            scene_count = _count_in_range(sc, w_start, w_end)
            scene_norm = scene_count / max_scenes_in_any_window
            score = (
                word_density * _WORD_DENSITY_WEIGHT
                + coverage * _COVERAGE_WEIGHT
                + scene_norm * _SCENE_DENSITY_WEIGHT
            )
        else:
            # Fallback: speech-only scoring (original weights)
            score = word_density * 0.6 + coverage * 0.4

        windows.append(ClipRegion(start=w_start, end=w_end, score=score))
        t += _WINDOW_STEP_S

    return windows


def _count_in_range(sorted_values: list[float], lo: float, hi: float) -> int:
    """Count how many values fall within [lo, hi) using binary search."""
    import bisect
    return bisect.bisect_left(sorted_values, hi) - bisect.bisect_left(sorted_values, lo)


def _non_max_suppression(
    windows: list[ClipRegion],
    max_clips: int,
) -> list[ClipRegion]:
    """Pick top-scoring non-overlapping windows."""
    ranked = sorted(windows, key=lambda w: w.score, reverse=True)
    selected: list[ClipRegion] = []

    for candidate in ranked:
        if len(selected) >= max_clips:
            break
        if any(_overlaps(candidate, s) for s in selected):
            continue
        selected.append(candidate)

    return selected


def _overlaps(a: ClipRegion, b: ClipRegion) -> bool:
    return a.start < b.end and b.start < a.end


def _merge_nearby(
    regions: list[ClipRegion],
    merge_gap: float,
    max_duration: float,
) -> list[ClipRegion]:
    """Merge regions that are within *merge_gap* seconds of each other."""
    if not regions:
        return []

    ordered = sorted(regions, key=lambda r: r.start)
    merged: list[ClipRegion] = [ordered[0]]

    for region in ordered[1:]:
        prev = merged[-1]
        if region.start - prev.end <= merge_gap:
            merged[-1] = ClipRegion(
                start=prev.start,
                end=min(region.end, max_duration),
                score=max(prev.score, region.score),
            )
        else:
            merged.append(region)

    return merged


_MAX_SNAP_S = 3.0


def _snap_to_sentences(
    regions: list[ClipRegion],
    segments: list[Segment],
    video_duration: float,
    max_adjust: float = _MAX_SNAP_S,
) -> list[ClipRegion]:
    """Nudge region boundaries so they align with sentence edges.

    Pulls ``start`` back to the beginning of the first overlapping segment
    and extends ``end`` to the end of the last overlapping segment, within
    *max_adjust* seconds, so clips never cut mid-sentence.
    """
    snapped: list[ClipRegion] = []

    for region in regions:
        new_start = region.start
        new_end = region.end

        for seg in segments:
            if seg["end"] <= region.start or seg["start"] >= region.end:
                continue
            if seg["start"] < region.start and region.start - seg["start"] <= max_adjust:
                new_start = min(new_start, seg["start"])
            if seg["end"] > region.end and seg["end"] - region.end <= max_adjust:
                new_end = max(new_end, seg["end"])

        new_start = max(0.0, new_start)
        new_end = min(video_duration, new_end)

        snapped.append(ClipRegion(
            start=round(new_start, 3),
            end=round(new_end, 3),
            score=region.score,
        ))

    return snapped


def _segments_in_range(
    segments: list[Segment],
    start: float,
    end: float,
) -> list[Segment]:
    """Return segments that overlap [start, end], with timestamps rebased to 0."""
    result: list[Segment] = []
    for seg in segments:
        if seg["end"] <= start or seg["start"] >= end:
            continue
        result.append({
            "start": round(max(seg["start"] - start, 0.0), 3),
            "end": round(min(seg["end"] - start, end - start), 3),
            "text": seg["text"],
        })
    return result
