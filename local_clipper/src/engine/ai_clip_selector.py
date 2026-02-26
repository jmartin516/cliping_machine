"""
AI-powered clip selection using Llama 3.2-1B (local LLM).

Uses llama-cpp-python with a quantized GGUF model. Runs on CPU with
~1GB RAM. Multilingual: understands transcripts in any language
(Whisper detects language automatically).

Uses a hybrid approach: algorithm pre-filters candidates, then AI
re-ranks them. This keeps the prompt small and avoids context overflow.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Callable, Optional

from src.engine.clip_selector import ClipRegion

logger = logging.getLogger(__name__)

_MODEL_CACHE_DIR = Path.home() / ".cache" / "local_clipper" / "llama32"
_MODEL_REPO = "bartowski/Llama-3.2-1B-Instruct-GGUF"
_MODEL_FILENAME = "Llama-3.2-1B-Instruct-Q4_K_S.gguf"

# Map Whisper language codes to full names for clearer AI prompts
_LANG_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ar": "Arabic",
    "hi": "Hindi",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "th": "Thai",
    "ca": "Catalan",
    "el": "Greek",
    "he": "Hebrew",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "no": "Norwegian",
    "cs": "Czech",
    "ro": "Romanian",
    "hu": "Hungarian",
}

LogCallback = Callable[[str, str], None]
CheckCancelledCallback = Callable[[], None]


@contextmanager
def _suppress_llama_output():
    """Suppress verbose llama.cpp stderr/stdout during model load."""
    import os
    with open(os.devnull, "w") as devnull:
        with redirect_stdout(devnull), redirect_stderr(devnull):
            yield


_OLD_SMOLLM_CACHE = Path.home() / ".cache" / "local_clipper" / "smollm"


def _ensure_model(on_log: Optional[LogCallback] = None) -> Path:
    """Download model from Hugging Face if not cached. Returns path to GGUF."""
    # Remove old SmolLM2 cache if present (one-time migration)
    if _OLD_SMOLLM_CACHE.exists():
        try:
            import shutil
            shutil.rmtree(_OLD_SMOLLM_CACHE)
            logger.info("Removed legacy SmolLM2 cache")
        except Exception:
            pass

    _MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local_path = _MODEL_CACHE_DIR / _MODEL_FILENAME

    if local_path.exists():
        if on_log:
            on_log(f"Llama 3.2-1B model cached: {local_path.name}", "info")
        return local_path

    if on_log:
        on_log("Downloading Llama 3.2-1B (~776MB). One-time setup…", "info")

    try:
        from huggingface_hub import hf_hub_download

        path = hf_hub_download(
            repo_id=_MODEL_REPO,
            filename=_MODEL_FILENAME,
            local_dir=str(_MODEL_CACHE_DIR),
            local_dir_use_symlinks=False,
        )
        if on_log:
            on_log("Llama 3.2-1B model downloaded successfully.", "success")
        return Path(path)
    except Exception as exc:
        logger.exception("Llama 3.2-1B download failed")
        if on_log:
            on_log(f"Failed to download model: {exc}", "error")
        raise RuntimeError(
            "Could not download Llama 3.2-1B model. Check your internet connection."
        ) from exc


def _lang_name(code: str) -> str:
    """Return full language name for prompt clarity."""
    return _LANG_NAMES.get(code.lower(), code.upper() if code else "unknown")


# Hook keywords (English) — segments starting with these get priority
_HOOK_KEYWORDS = frozenset({
    "incredible", "mistake", "secret", "trick", "why", "here's", "watch",
    "listen", "important", "never", "always", "everyone", "nobody", "wrong",
    "right", "truth", "lie", "actually", "really", "best", "worst", "first",
    "last", "only", "every", "nobody", "everyone", "stop", "wait", "look",
})

_DEAD_AIR_THRESHOLD_S = 1.5  # Segments starting with silence > this get penalized


def _prioritize_candidates(
    candidates: list[ClipRegion],
    audio_path: Optional[Path] = None,
) -> list[ClipRegion]:
    """
    Pre-AI prioritization: keyword boost, dead air filter, energy (RMS) boost.
    Reorders candidates so the AI sees the most promising ones first.
    """
    if not candidates:
        return []

    # Compute energy (RMS) per region if we have audio
    energy_scores: list[float] = []
    if audio_path and audio_path.exists():
        try:
            energy_scores = _compute_rms_per_regions(audio_path, candidates)
        except Exception as e:
            logger.debug("RMS analysis skipped: %s", e)
            energy_scores = [0.0] * len(candidates)

    if len(energy_scores) != len(candidates):
        energy_scores = [0.0] * len(candidates)

    # Baseline: median energy for "normal" segments
    baseline = 0.0
    if energy_scores:
        sorted_e = sorted(energy_scores)
        baseline = sorted_e[len(sorted_e) // 2] if sorted_e else 0.0

    scored: list[tuple[float, int, ClipRegion]] = []
    for i, region in enumerate(candidates):
        score = 0.0

        # Keyword boost: first words of first segment
        text_parts = [s.get("text", "").strip() for s in region.segments if s.get("text")]
        first_text = " ".join(text_parts).lower()[:80]
        first_words = set(first_text.split()[:5])
        if first_words & _HOOK_KEYWORDS:
            score += 2.0

        # Dead air: penalize if first segment starts late (silence at region start)
        first_speech_start = None
        for seg in region.segments:
            seg_start = seg.get("start")
            if seg_start is not None:
                first_speech_start = seg_start
                break
        if first_speech_start is not None and first_speech_start > _DEAD_AIR_THRESHOLD_S:
            score -= 1.5

        # Energy boost: +20% above baseline (laughter, emphasis)
        if baseline > 0 and energy_scores[i] > baseline * 1.2:
            score += 1.5

        scored.append((score, i, region))

    # Sort by score descending (best first), then by original index for ties
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [r for _, _, r in scored]


def _compute_rms_per_regions(audio_path: Path, regions: list[ClipRegion]) -> list[float]:
    """Compute RMS (loudness) for each region. Returns list of floats.
    Returns [] if numpy is not available (energy boost skipped)."""
    try:
        import numpy as np
    except ImportError:
        logger.warning("numpy not available — skipping RMS energy analysis")
        return []

    import wave
    with wave.open(str(audio_path), "rb") as wav:
        sr = wav.getframerate()
        nch = wav.getnchannels()
        n_frames = wav.getnframes()
        data = wav.readframes(n_frames)

    samples = np.frombuffer(data, dtype=np.int16)
    if nch == 2:
        samples = samples[::2]
    samples = samples.astype(np.float32) / 32768.0

    result = []
    for r in regions:
        start_samp = int(r.start * sr)
        end_samp = int(r.end * sr)
        start_samp = max(0, min(start_samp, len(samples)))
        end_samp = max(start_samp, min(end_samp, len(samples)))
        chunk = samples[start_samp:end_samp]
        if len(chunk) == 0:
            result.append(0.0)
            continue
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        result.append(rms)
    return result


def _build_prompt_from_candidates(
    candidates: list[ClipRegion],
    video_duration: float,
    max_clips: int,
    language: str,
) -> str:
    """
    Build prompt with Llama 3 chat format. English prompt for best results
    with English-speaking users. 300-char limit per candidate.
    """
    lang_name = _lang_name(language)
    lines = []
    for i, region in enumerate(candidates, 1):
        text = " ".join([s.get("text", "").strip() for s in region.segments])[:300]
        if not text:
            text = "(no speech)"
        dur = region.end - region.start
        lines.append(f"ID: {i} | Duration: {dur:.1f}s | Text: {text}")

    candidates_text = "\n".join(lines)

    system_content = f"""You are an expert Social Media Video Editor (TikTok, Reels, Shorts). Your goal is to identify segments with the highest "Virality Score" from a transcript in {lang_name}.

CRITERIA FOR SELECTION:
1. THE HOOK: Does it start with a bold statement, a surprising fact, or an emotional peak in the first 2 seconds?
2. RETENTION: Is the segment self-contained? Does it deliver a "Value Bomb", a punchline, or an "Aha!" moment?
3. PACING: Avoid segments with long silence or filler words at the start.
4. TRANSITIONS: Pick segments that have a clear beginning and a satisfying end.

INSTRUCTIONS:
- Review the {len(candidates)} candidate segments provided.
- Select the {max_clips} best ones.
- Return ONLY a JSON array of the chosen IDs. Example: [2, 5, 12]
- NO CONVERSATION. NO EXPLANATIONS. ONLY THE JSON ARRAY."""

    user_content = f"""VIDEO DURATION: {video_duration:.1f}s
CANDIDATES:
---
{candidates_text}
---
Selection:"""

    return system_content, user_content


def _parse_llm_response_indices(response: str, num_candidates: int) -> list[int]:
    """Extract segment indices from LLM output. Returns 0-based indices."""
    match = re.search(r'\[[\s\S]*?\]', response)
    if not match:
        return []

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return []

    result = []
    for item in data:
        try:
            idx = int(item)
            if 1 <= idx <= num_candidates:
                result.append(idx - 1)  # Convert to 0-based
        except (TypeError, ValueError):
            continue

    return result


def select_clips_with_ai(
    candidates: list[ClipRegion],
    video_duration: float,
    max_clips: int = 5,
    language: str = "en",
    audio_path: Optional[Path] = None,
    on_log: Optional[LogCallback] = None,
    check_cancelled: Optional[CheckCancelledCallback] = None,
) -> list[ClipRegion]:
    """
    Use Llama 3.2-1B to re-rank algorithm candidates. Keeps prompt small.
    Pre-IA prioritization (keyword boost, dead air filter, energy) reorders
    candidates before sending to the model.

    Args:
        candidates: Pre-filtered ClipRegions from algorithm (e.g. 15).
        video_duration: Total video length in seconds.
        max_clips: Maximum number of clips to return.
        language: Detected language code (e.g. "en", "es").
        audio_path: Optional path to WAV for RMS energy analysis.
        on_log: Optional callback for UI updates.

    Returns:
        List of ClipRegion sorted by start time.
    """
    if not candidates or video_duration <= 0:
        return []

    if check_cancelled:
        check_cancelled()

    # Pre-IA prioritization: keyword boost, dead air, energy
    candidates = _prioritize_candidates(candidates, audio_path)

    if check_cancelled:
        check_cancelled()
    model_path = _ensure_model(on_log)

    with _suppress_llama_output():
        try:
            from llama_cpp import Llama
        except ImportError:
            if on_log:
                on_log("llama-cpp-python not installed. Run: pip install llama-cpp-python", "error")
            raise RuntimeError(
                "llama-cpp-python is required for AI clip selection. "
                "Install it with: pip install llama-cpp-python"
            ) from None

        llm = Llama(
            model_path=str(model_path),
            n_ctx=4096,
            n_threads=4,
            n_gpu_layers=-1,
            verbose=False,
        )

    system_content, user_content = _build_prompt_from_candidates(
        candidates, video_duration, max_clips, language
    )

    if on_log:
        on_log("AI analyzing transcript…", "info")

    if check_cancelled:
        check_cancelled()
    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
        max_tokens=256,
        temperature=0.3,
        stop=["```", "\n\n\n"],
    )

    text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
    indices = _parse_llm_response_indices(text, len(candidates))

    if not indices:
        if on_log:
            on_log("AI returned no valid selection. Falling back to algorithm.", "warning")
        return candidates[:max_clips]

    # Map indices back to ClipRegions (indices refer to reordered candidates)
    seen = set()
    regions: list[ClipRegion] = []
    for idx in indices:
        if idx in seen or idx >= len(candidates):
            continue
        seen.add(idx)
        regions.append(candidates[idx])
        if len(regions) >= max_clips:
            break

    regions.sort(key=lambda r: r.start)

    if on_log:
        on_log(f"AI selected {len(regions)} clip(s)", "success")

    return regions
