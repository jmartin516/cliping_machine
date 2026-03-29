"""
AI transcription engine powered by faster-whisper.

Handles model loading (with local caching), CUDA/CPU auto-detection,
and segment extraction into a clean list-of-dicts format consumed by
the video processor.

Apple Silicon note:
    M-series Macs have no CUDA. The module gracefully falls back to
    ``device="cpu", compute_type="int8"`` which leverages Apple's
    Accelerate framework through CTranslate2's optimised kernels.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Optional

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# Persistent model cache inside the user's home directory so a PyInstaller
# bundle never re-downloads on each launch.
_MODEL_CACHE_DIR = Path.home() / ".cache" / "local_clipper" / "whisper_models"

# Type alias for the transcript segment dictionaries.
Segment = dict  # {"start": float, "end": float, "text": str}

# Type alias for the progress callback: (message, level)
ProgressCallback = Callable[[str, str], None]


# ── Device detection ──────────────────────────────────────────────────────────


def _detect_device() -> tuple[str, str]:
    """
    Return ``(device, compute_type)`` based on available hardware.

    Tries CUDA first (float16 for speed on NVIDIA GPUs), falls back to
    CPU int8 which is the best option for Apple Silicon and older x86.
    """
    try:
        import ctranslate2

        if "cuda" in (ctranslate2.get_supported_compute_types("cuda") or []):
            logger.info("CUDA detected — using GPU with float16")
            return "cuda", "float16"
    except Exception:
        pass

    logger.info("CUDA not available — using CPU with int8 quantization")
    return "cpu", "int8"


# ── Public API ────────────────────────────────────────────────────────────────


def load_model(
    model_size: str = "base",
    on_progress: Optional[ProgressCallback] = None,
) -> WhisperModel:
    """
    Load (or download) a faster-whisper model.

    Args:
        model_size: One of ``tiny``, ``base``, ``small``, ``medium``,
                    ``large-v2``.
        on_progress: Optional callback ``(message, level)`` for UI updates.

    Returns:
        An initialised ``WhisperModel`` ready for transcription.
    """
    _log(on_progress, f"Loading Whisper model '{model_size}'…", "info")

    _MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    device, compute_type = _detect_device()
    _log(on_progress, f"Device: {device}  |  Compute: {compute_type}", "debug")

    t0 = time.perf_counter()
    model = WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
        download_root=str(_MODEL_CACHE_DIR),
    )
    elapsed = time.perf_counter() - t0
    _log(on_progress, f"Model loaded in {elapsed:.1f}s", "success")
    return model


# Callable that raises if cancelled (no args, no return)
CheckCancelledCallback = Callable[[], None]


def transcribe(
    model: WhisperModel,
    audio_path: str | Path,
    on_progress: Optional[ProgressCallback] = None,
    check_cancelled: Optional[CheckCancelledCallback] = None,
) -> tuple[list[Segment], str]:
    """
    Transcribe *audio_path* and return segments plus detected language.

    Each segment is a dict with keys ``start`` (float), ``end`` (float),
    and ``text`` (str, uppercased for subtitle styling).

    Args:
        model: A pre-loaded ``WhisperModel``.
        audio_path: Path to a WAV/MP3/M4A/etc. file.
        on_progress: Optional callback for UI updates.

    Returns:
        Tuple of (segment list, language code), e.g.
        ``([{"start": 0.0, "end": 2.0, "text": "HELLO WORLD"}, …], "en")``
    """
    _log(on_progress, "Starting transcription…", "info")
    t0 = time.perf_counter()

    segments_iter, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        best_of=5,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=400,
            speech_pad_ms=200,
            threshold=0.45,
        ),
        word_timestamps=True,
        condition_on_previous_text=True,
        no_speech_threshold=0.5,
    )

    _log(
        on_progress,
        f"Detected language: {info.language} (probability {info.language_probability:.0%})",
        "info",
    )

    segments: list[Segment] = []
    for seg in segments_iter:
        if check_cancelled:
            check_cancelled()
        text = seg.text.strip()
        if not text:
            continue
        seg_dict: dict = {
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": text.upper(),
        }
        if seg.words:
            seg_dict["words"] = [
                {"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)}
                for w in seg.words
                if w.word.strip()
            ]
        segments.append(seg_dict)

    elapsed = time.perf_counter() - t0
    language = getattr(info, "language", "en") or "en"
    _log(
        on_progress,
        f"Transcription complete — {len(segments)} segments in {elapsed:.1f}s",
        "success",
    )
    return segments, language


# ── Helpers ───────────────────────────────────────────────────────────────────


def _log(cb: Optional[ProgressCallback], msg: str, level: str) -> None:
    """Forward to both the stdlib logger and an optional GUI callback."""
    getattr(logger, level if level != "success" else "info")(msg)
    if cb:
        cb(msg, level)
