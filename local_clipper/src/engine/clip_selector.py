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

_WORD_DENSITY_WEIGHT = 0.35
_COVERAGE_WEIGHT = 0.25
_SCENE_DENSITY_WEIGHT = 0.20
_ENGAGEMENT_WEIGHT = 0.20
_WINDOW_STEP_S = 2.0

_MAX_CLIP_DURATION_S = 90  # Hard cap: never exceed 90 seconds

# Content type patterns for TikTok optimization
_CONTENT_TYPE_PATTERNS = {
    "quick_tip": {
        "patterns": [
            r"\btrick\b", r"\btip\b", r"\bhack\b", r"\bhow to\b", 
            r"\btruco\b", r"\bconsejo\b", r"\bcomo\s+hacer\b",
            r"\bdica\b", r"\btruque\b", r"\btutorial\b",
        ],
        "optimal_duration": (30, 60),
    },
    "storytime": {
        "patterns": [
            r"\bstorytime\b", r"\bcuento\b", r"\bhistoria\b", r"\bme pas[oó]\b",
            r"\bstory\s*time\b", r"\bel otro d[ií]a\b", r"\buna vez\b",
        ],
        "optimal_duration": (45, 90),
    },
    "reaction": {
        "patterns": [
            r"\breaction\b", r"\breacci[oó]n\b", r"\breacting\b", r"\breact\b",
            r"\bmira esto\b", r"\bves esto\b",
        ],
        "optimal_duration": (20, 60),
    },
    "debate": {
        "patterns": [
            r"\bopinion\b", r"\bopini[oó]n\b", r"\bdebate\b", r"\bcontroversi",
            r"\bpol[eé]mic", r"\bhot take\b", r"\bno estoy de acuerdo\b",
            r"\bdisagree\b",
        ],
        "optimal_duration": (30, 75),
    },
    "pov": {
        "patterns": [
            r"\bpov\s*:?\b", r"\bpoint of view\b", r"\bcuando\s+eres\b",
            r"\bese momento\b",
        ],
        "optimal_duration": (15, 45),
    },
    "transformation": {
        "patterns": [
            r"\btransformation\b", r"\bantes\s+y\s+despu[eé]s\b", r"\bantes y despues\b",
            r"\bresultado\b", r"\bantes de\b",
        ],
        "optimal_duration": (25, 60),
    },
    "ranking": {
        "patterns": [
            r"\branking\b", r"\btop\s+\d+\b", r"\bmejores\b", r"\bpeores\b",
            r"\brating\b", r"\bpuntuando\b", r"\bvalorando\b",
        ],
        "optimal_duration": (30, 75),
    },
}

_EMOTION_INDICATORS = {
    "laughter": {
        "patterns": [r"\bjaja", r"\blol\b", r"\blmao\b", r"\bhaha", r"\brisa\b",
                     r"\bgracioso\b", r"\bfunny\b", r"\bjeje", r"\bkkkk"],
        "weight": 2.5,
    },
    "surprise": {
        "patterns": [r"\bwow\b", r"\boh my\b", r"\bomg\b", r"\bno way\b",
                     r"\bincre[ií]ble\b", r"\bno me lo creo\b", r"\bwhat\?!",
                     r"\bqu[eé]\?", r"\bno puede ser\b", r"\bimposible\b"],
        "weight": 2.0,
    },
    "excitement": {
        "patterns": [r"\byes!?\b", r"\blet'?s go\b", r"\bvamos\b", r"\byeah\b",
                     r"\bwoohoo\b", r"\bdale\b", r"\bgenial\b", r"\bamazing\b",
                     r"\bbrilliant\b", r"\bbrutal\b", r"\bflipa\b"],
        "weight": 1.8,
    },
    "controversy": {
        "patterns": [r"\bwrong\b", r"\blie\b", r"\btruth\b", r"\bmentira\b",
                     r"\bverdad\b", r"\bno estoy de acuerdo\b", r"\bdisagree\b",
                     r"\bobviously\b", r"\bobviamente\b", r"\bestupidez\b"],
        "weight": 2.2,
    },
    "tension": {
        "patterns": [r"\bbut\b", r"\bpero\b", r"\bhowever\b", r"\bsin embargo\b",
                     r"\bplot twist\b", r"\bthe thing is\b", r"\bel problema es\b",
                     r"\baquí viene\b", r"\bhere'?s the catch\b"],
        "weight": 1.5,
    },
    "payoff": {
        "patterns": [r"\bfinally\b", r"\bfinalmente\b", r"\bit worked\b",
                     r"\bfuncion[oó]\b", r"\band that'?s\b", r"\by eso es\b",
                     r"\bthe answer is\b", r"\bla respuesta es\b", r"\bresulta que\b",
                     r"\bturns out\b"],
        "weight": 1.8,
    },
}

_SENTENCE_ENDINGS = re.compile(r'[.!?…](?:\s|$)')
_QUESTION_PATTERNS = re.compile(
    r'\b(?:why|how|what|when|who|where|which|por qu[eé]|c[oó]mo|cu[aá]ndo|'
    r'qu[eé]|d[oó]nde|cu[aá]l)\b', re.IGNORECASE
)


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
    
    # Default: general content target around 60 seconds
    return "general", (50, 75)


def _calculate_emotion_score(segments: list[Segment], start: float, end: float) -> float:
    """Calculate emotion engagement score for a time window."""
    text = " ".join([
        s.get("text", "").lower() 
        for s in segments 
        if start <= s.get("start", 0) < end
    ])
    
    score = 0.0
    for _emotion_type, config in _EMOTION_INDICATORS.items():
        for pattern in config["patterns"]:
            if re.search(pattern, text):
                score += config["weight"]
                break  # one hit per category is enough
    
    return score


def _analyze_narrative_completeness(
    region: ClipRegion,
    segments: list[Segment],
) -> float:
    """
    Score how 'complete' a moment feels as a standalone piece.
    Checks for narrative arc: opening hook -> development -> payoff/punchline.
    """
    segs_in_range = [
        s for s in segments
        if region.start <= s.get("start", 0) < region.end
    ]
    if len(segs_in_range) < 2:
        return -3.0

    full_text = " ".join(s.get("text", "") for s in segs_in_range).lower()
    score = 0.0

    sentences = _SENTENCE_ENDINGS.split(full_text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
    n_sentences = len(sentences)

    if n_sentences >= 3:
        score += 2.0
    elif n_sentences >= 2:
        score += 1.0

    if _QUESTION_PATTERNS.search(full_text[:150]):
        score += 2.0

    last_quarter_text = " ".join(
        s.get("text", "").lower() for s in segs_in_range[-(max(1, len(segs_in_range)//4)):]
    )
    for config in [_EMOTION_INDICATORS.get("payoff", {}), _EMOTION_INDICATORS.get("surprise", {})]:
        for pattern in config.get("patterns", []):
            if re.search(pattern, last_quarter_text):
                score += 2.5
                break

    first_seg_start = segs_in_range[0].get("start", region.start)
    if first_seg_start - region.start > 2.0:
        score -= 2.0

    last_seg_end = segs_in_range[-1].get("end", region.end)
    if region.end - last_seg_end > 3.0:
        score -= 1.5

    return score


def _calculate_speech_pacing(segments: list[Segment], start: float, end: float) -> float:
    """Reward clips with varied pacing (not monotonous)."""
    segs = [s for s in segments if start <= s.get("start", 0) < end]
    if len(segs) < 3:
        return 0.0

    durations = [s.get("end", 0) - s.get("start", 0) for s in segs]
    if not durations:
        return 0.0

    avg = sum(durations) / len(durations)
    if avg <= 0:
        return 0.0
    variance = sum((d - avg) ** 2 for d in durations) / len(durations)

    if variance > 2.0:
        return 1.5
    elif variance > 0.5:
        return 0.8
    return 0.0


def _calculate_tiktok_score(
    region: ClipRegion,
    segments: list[Segment],
    optimal_duration: tuple[int, int],
) -> float:
    """
    Comprehensive viral potential scoring.
    Weighs: narrative completeness, emotion peaks, pacing, duration, hook strength.
    """
    duration = region.end - region.start
    min_opt, max_opt = optimal_duration
    
    score = 0.0
    
    if duration > _MAX_CLIP_DURATION_S:
        score -= 20.0
        return score

    if min_opt <= duration <= max_opt:
        center = (min_opt + max_opt) / 2
        dist = abs(duration - center) / (max_opt - min_opt)
        score += 4.0 * (1.0 - dist)
    elif duration < min_opt:
        score -= (min_opt - duration) * 0.3
    elif duration > max_opt:
        score -= (duration - max_opt) * 0.15

    score += _calculate_emotion_score(segments, region.start, region.end)

    score += _analyze_narrative_completeness(region, segments)

    score += _calculate_speech_pacing(segments, region.start, region.end)

    first_3s_text = " ".join([
        s.get("text", "").lower()
        for s in segments
        if region.start <= s.get("start", 0) < region.start + 3
    ])
    
    hook_patterns = [
        r"\bimagine\b", r"\bwhat if\b", r"\bdid you know\b", r"\bsecret\b",
        r"\bhere'?s\b", r"\bwatch this\b", r"\blisten\b", r"\bstop\b",
        r"\bincreible\b", r"\bincre[ií]ble\b", r"\bsorprendente\b", r"\bsecreto\b",
        r"\bsab[ií]as que\b", r"\bimagina\b", r"\bmira\b", r"\bescucha\b",
        r"\bpara\b", r"\bnever\b", r"\bnunca\b", r"\balways\b", r"\bsiempre\b",
    ]
    for pat in hook_patterns:
        if re.search(pat, first_3s_text):
            score += 4.0
            break

    if _QUESTION_PATTERNS.search(first_3s_text):
        score += 2.5
    
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

    Uses multi-window scanning: runs three passes with different window sizes
    (short, medium, long) to catch both punchy highlights and longer moments.
    Hard cap at 90 seconds.

    Args:
        segments:       Transcript segments from Whisper.
        video_duration: Total video length in seconds.
        clip_length:    Target clip duration (ignored when optimize_for_tiktok).
        max_clips:      Maximum number of clips to return.
        merge_gap:      Merge windows closer than this (seconds).
        scene_changes:  Sorted list of scene-change timestamps (seconds).
        optimize_for_tiktok: If True, applies multi-window + viral scoring.

    Returns:
        List of ``ClipRegion`` sorted by start time.
    """
    if not segments or video_duration <= 0:
        return []
    
    content_type, optimal_duration = _detect_content_type(segments)
    logger.info("Detected content type: %s, optimal duration: %s", content_type, optimal_duration)

    if not optimize_for_tiktok:
        clip_length = max(10, min(clip_length, int(video_duration), _MAX_CLIP_DURATION_S))
        windows = _score_windows(segments, video_duration, clip_length, scene_changes or [])
        if not windows:
            return []
        selected = _non_max_suppression(windows, max_clips)
        merged = _merge_nearby(selected, merge_gap, video_duration)
        merged = _snap_to_sentences(merged, segments, video_duration)
        for region in merged:
            region.segments = _segments_in_range(segments, region.start, region.end)
        merged.sort(key=lambda r: r.start)
        return merged

    window_sizes = [
        max(10, min(25, int(video_duration))),
        max(10, min(45, int(video_duration))),
        max(10, min(75, int(video_duration))),
    ]
    window_sizes = sorted(set(window_sizes))

    all_windows: list[ClipRegion] = []
    for wsize in window_sizes:
        windows = _score_windows(segments, video_duration, wsize, scene_changes or [])
        for window in windows:
            tiktok_boost = _calculate_tiktok_score(window, segments, optimal_duration)
            window.score += tiktok_boost * 0.25
        all_windows.extend(windows)

    if not all_windows:
        return []

    candidate_pool = max_clips * 4
    selected = _non_max_suppression(all_windows, candidate_pool)
    merged = _merge_nearby(selected, merge_gap, video_duration)
    merged = _snap_to_sentences(merged, segments, video_duration)

    for region in merged:
        if region.end - region.start > _MAX_CLIP_DURATION_S:
            region.end = region.start + _MAX_CLIP_DURATION_S
        region.segments = _segments_in_range(segments, region.start, region.end)

    merged.sort(key=lambda r: r.score, reverse=True)
    merged = merged[:max(max_clips * 3, 15)]
    merged.sort(key=lambda r: r.start)

    logger.info(
        "Selected %d candidate(s) via multi-window scan (content: %s, windows: %s)", 
        len(merged), content_type, window_sizes,
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
            engagement = _calculate_emotion_score(segments, w_start, w_end)
            engagement_norm = min(engagement / 10.0, 1.0)
            score = (
                word_density * _WORD_DENSITY_WEIGHT
                + coverage * _COVERAGE_WEIGHT
                + scene_norm * _SCENE_DENSITY_WEIGHT
                + engagement_norm * _ENGAGEMENT_WEIGHT
            )
        else:
            engagement = _calculate_emotion_score(segments, w_start, w_end)
            engagement_norm = min(engagement / 10.0, 1.0)
            score = word_density * 0.45 + coverage * 0.30 + engagement_norm * 0.25

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
    """Merge regions within *merge_gap* seconds, capping at 90s."""
    if not regions:
        return []

    ordered = sorted(regions, key=lambda r: r.start)
    merged: list[ClipRegion] = [ordered[0]]

    for region in ordered[1:]:
        prev = merged[-1]
        proposed_end = min(region.end, max_duration)
        proposed_duration = proposed_end - prev.start

        if region.start - prev.end <= merge_gap and proposed_duration <= _MAX_CLIP_DURATION_S:
            merged[-1] = ClipRegion(
                start=prev.start,
                end=proposed_end,
                score=max(prev.score, region.score),
            )
        else:
            merged.append(region)

    return merged


_MAX_SNAP_S = 2.0


def _snap_to_sentences(
    regions: list[ClipRegion],
    segments: list[Segment],
    video_duration: float,
    max_adjust: float = _MAX_SNAP_S,
) -> list[ClipRegion]:
    """Nudge region boundaries to align with sentence/segment edges.

    Start: pulls back to include the full first overlapping segment so the
    clip opens with a complete thought instead of mid-sentence.

    End: extends to finish the last overlapping segment, but ONLY if the
    resulting clip stays under the 90s hard cap.
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
                candidate_end = max(new_end, seg["end"])
                if candidate_end - new_start <= _MAX_CLIP_DURATION_S:
                    new_end = candidate_end

        new_start = max(0.0, new_start)
        new_end = min(video_duration, new_end)

        if new_end - new_start > _MAX_CLIP_DURATION_S:
            new_end = new_start + _MAX_CLIP_DURATION_S

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
        entry: Segment = {
            "start": round(max(seg["start"] - start, 0.0), 3),
            "end": round(min(seg["end"] - start, end - start), 3),
            "text": seg["text"],
        }
        if seg.get("words"):
            entry["words"] = [
                {
                    "word": w["word"],
                    "start": round(max(w["start"] - start, 0.0), 3),
                    "end": round(min(w["end"] - start, end - start), 3),
                }
                for w in seg["words"]
                if w.get("start", 0) < end and w.get("end", 0) > start
            ]
        result.append(entry)
    return result
