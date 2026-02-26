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


def _build_prompt_from_candidates(
    candidates: list[ClipRegion],
    video_duration: float,
    max_clips: int,
    language: str,
) -> str:
    """Build prompt from pre-filtered algorithm candidates. Keeps context small."""
    lang_name = _lang_name(language)
    lines = []
    for i, region in enumerate(candidates, 1):
        text_parts = [s.get("text", "").strip() for s in region.segments if s.get("text")]
        text = " ".join(text_parts)[:200]  # Limit per candidate
        if not text:
            text = "(no speech)"
        lines.append(f"{i}. [{region.start:.1f}s - {region.end:.1f}s] {text}")

    candidates_text = "\n".join(lines)

    return f"""You are a clip selection assistant for short-form vertical videos (TikTok, Reels, Shorts).

The transcript is in {lang_name}. Pick the {max_clips} best segments for clips.
Prioritize: hooks, punchlines, key insights, emotional moments, clear narratives, viral-worthy moments.

VIDEO DURATION: {video_duration:.1f} seconds

CANDIDATE SEGMENTS (pick the best {max_clips} by number):
---
{candidates_text}
---

Return ONLY a JSON array of the segment numbers you chose, e.g. [3, 1, 7] for segments 3, 1, 7.
Pick exactly {max_clips} segments. No other text."""


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
    on_log: Optional[LogCallback] = None,
    check_cancelled: Optional[CheckCancelledCallback] = None,
) -> list[ClipRegion]:
    """
    Use Llama 3.2-1B to re-rank algorithm candidates. Keeps prompt small.

    Args:
        candidates: Pre-filtered ClipRegions from algorithm (e.g. 15).
        video_duration: Total video length in seconds.
        max_clips: Maximum number of clips to return.
        language: Detected language code (e.g. "en", "es").
        on_log: Optional callback for UI updates.

    Returns:
        List of ClipRegion sorted by start time.
    """
    if not candidates or video_duration <= 0:
        return []

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
            verbose=False,
        )

    prompt = _build_prompt_from_candidates(
        candidates, video_duration, max_clips, language
    )

    if on_log:
        on_log("AI analyzing transcript…", "info")

    if check_cancelled:
        check_cancelled()
    # Llama 3.2 Instruct expects chat format for best results
    response = llm.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
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

    # Map indices back to ClipRegions, preserving order
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
