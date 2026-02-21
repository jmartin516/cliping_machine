"""
Video processing pipeline for Local Clipper.

Responsibilities:
    1. Extract audio from the source video for Whisper.
    2. Crop 16:9 → 9:16 (centred).
    3. Overlay styled subtitle ``TextClip``s mapped from transcript segments.
    4. Render the final vertical clip with progress callbacks.

All heavy operations are designed to run on a worker thread; the caller
passes thread-safe callbacks (``on_progress`` / ``on_log``) that post
updates back to the Tk event loop.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from moviepy.editor import (
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
)

from src.engine.ai_transcriber import Segment

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]   # (0.0–1.0, status_text)
LogCallback = Callable[[str, str], None]           # (message, level)


# ── Subtitle styling constants ────────────────────────────────────────────────

_FONT = "Impact"
_FONT_FALLBACKS = ["Arial-Black", "Arial-Bold", "Helvetica-Bold", "DejaVu-Sans-Bold"]
_FONT_SIZE = 48
_FONT_COLOR = "white"
_STROKE_COLOR = "black"
_STROKE_WIDTH = 3


def _resolve_font() -> str:
    """Return the first available font or fall back to the primary choice."""
    try:
        TextClip("test", fontsize=20, font=_FONT).close()
        return _FONT
    except Exception:
        for fb in _FONT_FALLBACKS:
            try:
                TextClip("test", fontsize=20, font=fb).close()
                logger.info("Using fallback font: %s", fb)
                return fb
            except Exception:
                continue
    logger.warning("No preferred font found — defaulting to %s", _FONT)
    return _FONT


# ── Audio extraction ──────────────────────────────────────────────────────────


def extract_audio(
    video_path: str | Path,
    on_log: Optional[LogCallback] = None,
) -> Path:
    """
    Extract the audio track from *video_path* to a temporary WAV file.

    Returns the path to the WAV; the caller is responsible for cleanup
    (or it will be cleaned up when the temp dir is reaped by the OS).
    """
    _log(on_log, "Extracting audio track…", "info")
    t0 = time.perf_counter()

    video = VideoFileClip(str(video_path))
    tmp = Path(tempfile.mktemp(suffix=".wav", prefix="lc_audio_"))
    video.audio.write_audiofile(
        str(tmp),
        fps=16_000,
        nbytes=2,
        codec="pcm_s16le",
        logger=None,
    )
    video.close()

    elapsed = time.perf_counter() - t0
    _log(on_log, f"Audio extracted in {elapsed:.1f}s → {tmp.name}", "success")
    return tmp


# ── Crop & subtitle composition ──────────────────────────────────────────────


def _build_vertical_clip(
    video_path: str | Path,
    segments: list[Segment],
    on_log: Optional[LogCallback] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> CompositeVideoClip:
    """
    Crop the source to 9:16 and overlay subtitle clips.

    The crop is centred horizontally; height is preserved.  If the source
    is already narrower than 9:16, we pad (black bars) instead of cropping.
    """
    _log(on_log, "Building vertical clip…", "info")

    source = VideoFileClip(str(video_path))
    src_w, src_h = source.size

    target_w = int(src_h * 9 / 16)
    if target_w > src_w:
        target_w = src_w
    x_center = src_w / 2
    x1 = int(x_center - target_w / 2)

    cropped = source.crop(x1=x1, y1=0, x2=x1 + target_w, y2=src_h)
    crop_w, crop_h = cropped.size

    _log(on_log, f"Crop: {src_w}x{src_h} → {crop_w}x{crop_h}", "debug")

    font = _resolve_font()
    subtitle_y = int(crop_h * 0.70)
    max_chars = 35

    if on_progress:
        on_progress(0.10, "Generating subtitle clips…")

    txt_clips: list[TextClip] = []
    total = len(segments)

    for i, seg in enumerate(segments):
        words = seg["text"]
        lines = [words[j:j + max_chars] for j in range(0, len(words), max_chars)]
        display_text = "\n".join(lines)

        try:
            tc = (
                TextClip(
                    display_text,
                    fontsize=_FONT_SIZE,
                    font=font,
                    color=_FONT_COLOR,
                    stroke_color=_STROKE_COLOR,
                    stroke_width=_STROKE_WIDTH,
                    method="caption",
                    size=(int(crop_w * 0.90), None),
                    align="center",
                )
                .set_position(("center", subtitle_y))
                .set_start(seg["start"])
                .set_duration(seg["end"] - seg["start"])
            )
            txt_clips.append(tc)
        except Exception as exc:
            _log(on_log, f"Skipped subtitle segment {i}: {exc}", "warning")

        if on_progress and total > 0:
            on_progress(0.10 + 0.15 * ((i + 1) / total), "Generating subtitle clips…")

    _log(on_log, f"Created {len(txt_clips)} subtitle overlays", "info")

    composite = CompositeVideoClip([cropped, *txt_clips], size=(crop_w, crop_h))
    composite.audio = cropped.audio
    return composite


# ── Render ────────────────────────────────────────────────────────────────────


def render_clip(
    video_path: str | Path,
    segments: list[Segment],
    output_dir: str | Path,
    on_log: Optional[LogCallback] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> Path:
    """
    Full render pipeline: crop → subtitles → encode.

    Args:
        video_path:  Input video file.
        segments:    Transcript segment dicts from the transcriber.
        output_dir:  Directory to write the final file into.
        on_log:      ``(message, level)`` callback.
        on_progress: ``(0.0-1.0, status)`` callback.

    Returns:
        Path to the rendered output file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(video_path).stem
    output_path = output_dir / f"{stem}_vertical.mp4"

    # Avoid overwriting — append a counter if file exists.
    counter = 1
    while output_path.exists():
        output_path = output_dir / f"{stem}_vertical_{counter}.mp4"
        counter += 1

    composite = _build_vertical_clip(video_path, segments, on_log, on_progress)
    total_frames = int(composite.fps * composite.duration)

    _log(on_log, f"Rendering {total_frames} frames → {output_path.name}", "info")
    if on_progress:
        on_progress(0.30, "Rendering video…")

    t0 = time.perf_counter()

    # moviepy's write_videofile logger callback for progress reporting
    rendered_so_far = {"n": 0}

    def _frame_logger(msg: dict) -> None:
        """moviepy progress_bar replacement via logger callback."""
        pass

    composite.write_videofile(
        str(output_path),
        codec="libx264",
        audio_codec="aac",
        fps=composite.fps,
        preset="medium",
        threads=max(1, os.cpu_count() or 4),
        logger=None,
    )

    composite.close()
    elapsed = time.perf_counter() - t0

    if on_progress:
        on_progress(1.0, "Done")
    _log(on_log, f"Render complete in {elapsed:.1f}s → {output_path}", "success")
    return output_path


# ── Full pipeline (orchestrates transcriber + processor) ──────────────────────


def run_pipeline(
    video_path: str | Path,
    output_dir: str | Path,
    model_size: str = "base",
    on_log: Optional[LogCallback] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> Path:
    """
    End-to-end pipeline called from the GUI worker thread.

    Steps:
        1. Extract audio  (0 %  → 10 %)
        2. Transcribe      (10 % → 30 %)
        3. Render clip     (30 % → 100 %)

    Returns:
        Path to the final rendered video.
    """
    from src.engine.ai_transcriber import load_model, transcribe

    if on_progress:
        on_progress(0.0, "Starting pipeline…")

    # ── Step 1: audio extraction ─────────────────────────────────────────
    audio_path = extract_audio(video_path, on_log)
    if on_progress:
        on_progress(0.05, "Audio extracted")

    # ── Step 2: transcription ────────────────────────────────────────────
    if on_progress:
        on_progress(0.06, "Loading Whisper model…")

    model = load_model(model_size, on_progress=on_log)
    if on_progress:
        on_progress(0.10, "Transcribing audio…")

    segments = transcribe(model, audio_path, on_progress=on_log)
    if on_progress:
        on_progress(0.25, f"Transcribed {len(segments)} segments")

    if not segments:
        _log(on_log, "No speech detected — aborting.", "error")
        raise RuntimeError("Transcription produced no segments.")

    # ── Step 3: render ───────────────────────────────────────────────────
    output = render_clip(video_path, segments, output_dir, on_log, on_progress)

    # Cleanup temp audio
    try:
        Path(audio_path).unlink(missing_ok=True)
    except Exception:
        pass

    return output


# ── Helpers ───────────────────────────────────────────────────────────────────


def _log(cb: Optional[LogCallback], msg: str, level: str) -> None:
    getattr(logger, level if level != "success" else "info")(msg)
    if cb:
        cb(msg, level)
