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


# Hook keywords by category for better TikTok optimization
_HOOK_KEYWORDS = frozenset({
    "incredible", "mistake", "secret", "trick", "why", "here's", "watch",
    "listen", "important", "never", "always", "everyone", "nobody", "wrong",
    "right", "truth", "lie", "actually", "really", "best", "worst", "first",
    "last", "only", "every", "stop", "wait", "look", "imagine", "what if",
    "did you know", "the reason", "this is why", "you won't believe",
})

_HOOK_KEYWORDS_ES = frozenset({
    "increíble", "increible", "error", "secreto", "truco", "por qué", "porque",
    "mira", "escucha", "importante", "nunca", "siempre", "todos", "nadie",
    "mal", "bien", "verdad", "mentira", "realmente", "de verdad", "mejor",
    "peor", "primero", "último", "solo", "cada", "para", "espera", "fíjate",
    "fijate", "fijate", "imagina", "qué pasaría", "sabías que", "la razón",
    "esto es por qué", "no vas a creer", "no te vas a creer", "sorprendente",
    "increíble", "brutal", "increíble", "increíble", "flipa", "flipas",
})

_HOOK_KEYWORDS_PT = frozenset({
    "incrível", "erro", "segredo", "truque", "por que", "olha", "escuta",
    "importante", "nunca", "sempre", "todos", "ninguém", "mal", "bem",
    "verdade", "mentira", "realmente", "melhor", "pior", "primeiro", "último",
    "só", "cada", "pare", "espera", "olhe", "imagine", "você não vai acreditar",
})

# Hook categories for TikTok viral scoring
_HOOK_CATEGORIES = {
    "curiosity_gap": {
        "en": frozenset({"secret", "why", "here's", "what if", "did you know", 
                         "the reason", "this is why", "you won't believe", "imagine"}),
        "es": frozenset({"secreto", "por qué", "sabías que", "la razón", 
                         "esto es por qué", "no vas a creer", "imagina", "qué pasaría"}),
        "pt": frozenset({"segredo", "por que", "você sabia", "o motivo", 
                         "é por isso", "você não vai acreditar", "imagine"}),
    },
    "value_bomb": {
        "en": frozenset({"trick", "tip", "hack", "how to", "best way", "easiest",
                         "fastest", "most effective", "pro tip", "quick"}),
        "es": frozenset({"truco", "consejo", "tutorial", "cómo", "mejor manera",
                         "más fácil", "más rápido", "consejo pro"}),
        "pt": frozenset({"truque", "dica", "tutorial", "como", "melhor maneira",
                         "mais fácil", "mais rápido", "dica de profissional"}),
    },
    "emotion_peak": {
        "en": frozenset({"incredible", "amazing", "shocking", "hilarious", "emotional",
                         "heartbreaking", "mind blowing", "insane", "crazy"}),
        "es": frozenset({"increíble", "increible", "sorprendente", "gracioso", 
                         "emocionante", "desgarrador", "increíble", "brutal", "flipa"}),
        "pt": frozenset({"incrível", "surpreendente", "engraçado", "emocionante",
                         "de partir o coração", "incrível", "insano", "maluco"}),
    },
    "hot_take": {
        "en": frozenset({"wrong", "lie", "truth", "actually", "unpopular opinion",
                         "controversial", "hot take", "debate"}),
        "es": frozenset({"mal", "mentira", "verdad", "opinión impopular",
                         "controversial", "polémico"}),
        "pt": frozenset({"errado", "mentira", "verdade", "opinião impopular",
                         "controversial", "polêmico"}),
    },
    "trending_format": {
        "en": frozenset({"pov:", "storytime:", "day", "part", "get ready with me",
                         "grwm", "rating", "review", "rating my", "ranking"}),
        "es": frozenset({"pov:", "storytime:", "día", "parte", "preparándome",
                         "valorando", "reseña", "puntuando"}),
        "pt": frozenset({"pov:", "storytime:", "dia", "parte", "me preparando",
                         "avaliando", "resenha", "classificando"}),
    },
}

# Filler words that hurt retention at the start
_FILLER_WORDS = frozenset({
    "um", "uh", "eh", "ah", "bueno", "entonces", "pues", "mira", "o sea",
    "vale", "okey", "okay", "ok", "bien", "so", "well", "you know", "like",
    "basicamente", "básicamente", "digamos", "tipo", "entonces", "bueno pues",
    "este", "esta", "esto", "mm", "mmm", "hmm", "huh",
})

_DEAD_AIR_THRESHOLD_S = 1.5  # Segments starting with silence > this get penalized
_TIKTOK_HOOK_WINDOW_S = 3.0  # First 3 seconds are critical for retention


def _detect_language_from_text(text: str) -> str:
    """Detect language from text for hook keyword matching."""
    text_lower = text.lower()
    
    # Count matches for each language
    es_count = sum(1 for word in _HOOK_KEYWORDS_ES if word in text_lower)
    pt_count = sum(1 for word in _HOOK_KEYWORDS_PT if word in text_lower)
    en_count = sum(1 for word in _HOOK_KEYWORDS if word in text_lower)
    
    if es_count >= en_count and es_count >= pt_count:
        return "es"
    elif pt_count >= en_count:
        return "pt"
    return "en"


def _analyze_hook_strength(text: str, lang: str = "en") -> tuple[float, dict]:
    """
    Analyze hook strength with categorization for TikTok.
    Returns (score_boost, category_info).
    """
    text_lower = text.lower()
    words = set(text_lower.split()[:10])  # First 10 words
    
    score = 0.0
    categories_found = {}
    
    for category, langs in _HOOK_CATEGORIES.items():
        category_words = langs.get(lang, langs.get("en", set()))
        matches = words & category_words
        if matches:
            # Curiosity gap is strongest for retention
            if category == "curiosity_gap":
                score += 4.0
                categories_found[category] = list(matches)
            elif category == "trending_format":
                score += 3.5
                categories_found[category] = list(matches)
            elif category == "hot_take":
                score += 3.0
                categories_found[category] = list(matches)
            elif category == "emotion_peak":
                score += 2.5
                categories_found[category] = list(matches)
            elif category == "value_bomb":
                score += 2.0
                categories_found[category] = list(matches)
    
    return score, categories_found


def _analyze_first_3_seconds(
    region: ClipRegion,
    first_segment: Optional[dict] = None,
) -> tuple[float, dict]:
    """
    Analyze the critical first 3 seconds for TikTok retention.
    Returns (penalty_or_boost, analysis_info).
    """
    score_adjustment = 0.0
    analysis = {
        "has_immediate_start": False,
        "starts_with_filler": False,
        "hook_in_first_3s": False,
        "first_speech_delay": 0.0,
    }
    
    if not region.segments:
        return -5.0, analysis  # Severe penalty for no speech
    
    first_seg = region.segments[0]
    analysis["first_speech_delay"] = first_seg.get("start", 0.0)
    
    # Check immediate start (within 0.5s)
    if first_seg.get("start", 0.0) <= 0.5:
        analysis["has_immediate_start"] = True
        score_adjustment += 1.0
    elif first_seg.get("start", 0.0) <= 1.0:
        score_adjustment += 0.5
    else:
        # Penalize late starts
        delay = first_seg.get("start", 0.0)
        score_adjustment -= min(delay * 0.8, 3.0)  # Up to -3.0 penalty
    
    # Check for filler words at start
    first_text = first_seg.get("text", "").strip().lower()
    first_words = first_text.split()[:3]
    
    filler_count = sum(1 for word in first_words if word in _FILLER_WORDS)
    if filler_count > 0:
        analysis["starts_with_filler"] = True
        score_adjustment -= filler_count * 1.5  # -1.5 per filler word (hard retention killer)
    
    # Check if hook is in first 3 seconds
    text_in_3s = " ".join([
        s.get("text", "") for s in region.segments 
        if s.get("end", 0) <= _TIKTOK_HOOK_WINDOW_S
    ]).lower()
    
    if text_in_3s:
        lang = _detect_language_from_text(text_in_3s)
        hook_score, hook_cats = _analyze_hook_strength(text_in_3s, lang)
        if hook_score > 0:
            analysis["hook_in_first_3s"] = True
            analysis["hook_categories"] = hook_cats
            score_adjustment += hook_score * 1.5  # 1.5x boost for early hooks
    
    return score_adjustment, analysis


def _calculate_retention_score(
    region: ClipRegion,
    energy_score: float,
    baseline_energy: float,
) -> tuple[float, dict]:
    """
    Calculate TikTok-specific retention score for a region.
    Returns (score, analysis_metadata).
    """
    score = 0.0
    analysis = {
        "hook_analysis": {},
        "first_3s_analysis": {},
        "duration_score": 0.0,
        "energy_score": 0.0,
    }
    
    # Get full text for hook analysis
    full_text = " ".join([s.get("text", "").strip() for s in region.segments]).lower()
    
    if not full_text:
        return -10.0, analysis  # Severe penalty for empty content
    
    # Detect language
    lang = _detect_language_from_text(full_text)
    analysis["detected_language"] = lang
    
    # Analyze hook strength in overall clip
    hook_score, hook_cats = _analyze_hook_strength(full_text[:200], lang)
    score += hook_score
    analysis["hook_analysis"] = {
        "categories": hook_cats,
        "raw_score": hook_score,
    }
    
    # CRITICAL: First 3 seconds analysis
    first_3s_score, first_3s_info = _analyze_first_3_seconds(region)
    score += first_3s_score
    analysis["first_3s_analysis"] = first_3s_info
    
    # Duration optimization for monetization (TikTok Creator Rewards: min 60s)
    duration = region.end - region.start
    if 60 <= duration <= 90:
        analysis["duration_score"] = 2.0  # Sweet spot for monetization
        score += 2.0
    elif 90 < duration <= 120:
        analysis["duration_score"] = 1.5
        score += 1.5
    elif 45 <= duration < 60:
        analysis["duration_score"] = 0.5  # Acceptable but below monetization floor
        score += 0.5
    elif duration > 120:
        analysis["duration_score"] = -0.5  # Slight penalty above 2 min
        score -= 0.5
    elif duration < 30:
        analysis["duration_score"] = -2.0  # Too short for monetization
        score -= 2.0
    
    # Energy analysis (laughter, emphasis)
    if baseline_energy > 0 and energy_score > 0:
        energy_ratio = energy_score / baseline_energy
        if energy_ratio > 1.5:
            analysis["energy_score"] = 2.0
            score += 2.0  # High energy = engagement
        elif energy_ratio > 1.2:
            analysis["energy_score"] = 1.0
            score += 1.0
        elif energy_ratio < 0.5:
            analysis["energy_score"] = -1.0
            score -= 1.0  # Low energy = boring
    
    # Legacy keyword detection for backward compatibility
    all_hooks = _HOOK_KEYWORDS | _HOOK_KEYWORDS_ES | _HOOK_KEYWORDS_PT
    first_words = set(full_text.split()[:5])
    if first_words & all_hooks:
        score += 1.0
    
    return score, analysis


def _prioritize_candidates(
    candidates: list[ClipRegion],
    audio_path: Optional[Path] = None,
) -> list[ClipRegion]:
    """
    Pre-AI prioritization with TikTok-optimized scoring.
    Analyzes: hook categories, first 3s retention, energy, duration.
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

    scored: list[tuple[float, int, ClipRegion, dict]] = []
    for i, region in enumerate(candidates):
        # Calculate comprehensive TikTok retention score
        score, analysis = _calculate_retention_score(region, energy_scores[i], baseline)
        
        # Attach analysis metadata to region for potential use by AI
        region._tiktok_analysis = analysis
        
        scored.append((score, i, region, analysis))

    # Sort by score descending (best first), then by original index for ties
    scored.sort(key=lambda x: (-x[0], x[1]))
    
    # Log top candidates for debugging
    if scored:
        logger.debug("Top TikTok candidate: score=%.2f, analysis=%s", 
                    scored[0][0], scored[0][3])
    
    return [r for _, _, r, _ in scored]


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
    Build TikTok-optimized prompt with Llama 3 chat format.
    Focuses on retention patterns, hook strength, and viral potential.
    300-char limit per candidate.
    """
    lang_name = _lang_name(language)
    
    # Build candidate descriptions with TikTok metadata
    lines = []
    for i, region in enumerate(candidates, 1):
        text = " ".join([s.get("text", "").strip() for s in region.segments])[:300]
        if not text:
            text = "(no speech)"
        dur = region.end - region.start
        
        # Include TikTok analysis metadata if available
        analysis = getattr(region, '_tiktok_analysis', {})
        metadata_parts = []
        
        first_3s = analysis.get('first_3s_analysis', {})
        if first_3s.get('hook_in_first_3s'):
            metadata_parts.append("HOOK@3s")
        if first_3s.get('has_immediate_start'):
            metadata_parts.append("IMMEDIATE_START")
        if first_3s.get('starts_with_filler'):
            metadata_parts.append("⚠️FILLER")
        
        hook_cats = analysis.get('hook_analysis', {}).get('categories', {})
        if hook_cats:
            cats = ",".join(hook_cats.keys())[:30]
            metadata_parts.append(f"CAT:{cats}")
        
        metadata = f" [{'; '.join(metadata_parts)}]" if metadata_parts else ""
        lines.append(f"ID:{i} | {dur:.0f}s{metadata} | {text}")

    candidates_text = "\n".join(lines)

    system_content = f"""You are an elite TikTok Content Strategist with millions of views under your belt. Your ONLY goal is to identify clips with MAXIMUM VIRAL POTENTIAL.

LANGUAGE: {lang_name}

TIKTOK VIRALITY CRITERIA (ranked by importance):

1. RETENTION HOOK (Critical - First 1-3 seconds)
   - Does it IMMEDIATELY grab attention with a bold statement, controversial take, or curiosity gap?
   - Look for segments marked "HOOK@3s" or "IMMEDIATE_START"
   - AVOID segments marked "FILLER" (start with "um", "well", "bueno", etc.)

2. SELF-CONTAINED STORY (Essential)
   - Can someone understand this WITHOUT watching the full video?
   - Does it have a clear beginning → middle → satisfying end/punchline?
   - Does it deliver a "Value Bomb", "Aha!" moment, or emotional payoff?

3. SHAREABILITY FACTOR (High impact)
   - Would someone send this to a friend? (relatable, shocking, funny, useful)
   - Does it trigger an emotional response? (laughter, surprise, outrage, inspiration)
   - Is it a "hot take" or unpopular opinion that sparks debate?

4. LOOP POTENTIAL (Nice to have)
   - Does the ending naturally connect back to the beginning?
   - Would viewers watch it twice?

5. CAPTION-FRIENDLY
   - Does the audio work well with auto-captions?
   - Is the speech clear without visual context?

SELECTION STRATEGY:
- DIVERSITY: Pick clips with DIFFERENT hook types (not all the same)
- ENERGY: Prefer high-energy moments (laughter, excitement, emphasis)
- PACING: Avoid segments starting with silence or hesitation
- CLARITY: The clip should make sense as a standalone piece

INSTRUCTIONS:
- Review {len(candidates)} candidate segments
- Select ONLY the {max_clips} with HIGHEST viral potential
- Prioritize: HOOK@3s + Self-contained + Shareable
- Return ONLY a JSON array of chosen IDs: [1, 3, 7]
- NO explanations. NO conversation. ONLY JSON."""

    user_content = f"""VIDEO: {video_duration:.0f}s total | TARGET: {max_clips} clips

CANDIDATES:
{candidates_text}

Select the {max_clips} clips with maximum TikTok viral potential:"""

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
