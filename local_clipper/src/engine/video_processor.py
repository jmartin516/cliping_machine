"""
Video processing pipeline for CustosAI Clipper.

Responsibilities:
    1. Extract audio from the source video for Whisper.
    2. Select top clip regions by speech density.
    3. For each region: crop 16:9 -> 9:16, overlay interactive subtitles, render.

Subtitles are rendered with Pillow (no ImageMagick required). Words appear
in small groups and the current word is highlighted in a contrasting colour,
producing the popular TikTok / Reels "karaoke" style.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from moviepy.editor import (
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    vfx,
)
from PIL import Image, ImageDraw, ImageFont

from src.engine.ai_transcriber import Segment
from src.engine.clip_selector import ClipRegion

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]   # (0.0-1.0, status_text)
LogCallback = Callable[[str, str], None]           # (message, level)


# ── Interactive subtitle constants ────────────────────────────────────────────

_HIGHLIGHT_COLOR = (255, 255, 0)        # Yellow for the spoken word
_NORMAL_COLOR = (255, 255, 255)         # White for other words
_STROKE_RGB = (0, 0, 0)                 # Black outline
_STROKE_WIDTH = 4
_WORDS_PER_GROUP = 3
_SUBTITLE_Y_RATIO = 0.68               # Vertical position (% of frame height)

# Split-screen layout: top portion gets main content, bottom gets background
_SPLIT_MAIN_RATIO = 0.55               # Top 55 % for main clip
_SUBTITLE_Y_RATIO_SPLIT = 0.60         # Subtitles sit lower in the top half

_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "C:\\Windows\\Fonts\\impact.ttf",
]


# ── Text helpers ──────────────────────────────────────────────────────────────


def _clean_text(text: str) -> str:
    """Remove emojis and special symbols, keep letters (including accents),
    digits, spaces, and basic punctuation."""
    text = re.sub(r'[\U00010000-\U0010ffff]', '', text)
    text = re.sub(r"[^\w\s.,!?'\"]+", '', text, flags=re.UNICODE)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _find_bold_font(size: int) -> ImageFont.FreeTypeFont:
    """Locate a bold TrueType font on the system."""
    for p in _FONT_PATHS:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    logger.warning("No bold font found on system — using Pillow default")
    return ImageFont.load_default(size=size)


# ── Pillow-based subtitle rendering ──────────────────────────────────────────


def _render_word_group_frame(
    words: list[str],
    highlight_idx: int,
    frame_width: int,
    font: ImageFont.FreeTypeFont,
) -> np.ndarray:
    """Render a group of words with one highlighted. Returns RGBA numpy array."""
    probe = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(probe)

    space_w = draw.textlength(" ", font=font)
    word_widths = [draw.textlength(w, font=font) for w in words]
    total_text_w = sum(word_widths) + space_w * max(len(words) - 1, 0)

    ascent, descent = font.getmetrics()
    text_h = ascent + descent
    pad = _STROKE_WIDTH + 6
    img_h = text_h + pad * 2

    img = Image.new("RGBA", (frame_width, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    x = (frame_width - total_text_w) / 2.0
    y = float(pad)

    for i, word in enumerate(words):
        color = _HIGHLIGHT_COLOR if i == highlight_idx else _NORMAL_COLOR
        draw.text(
            (x, y),
            word,
            font=font,
            fill=(*color, 255),
            stroke_width=_STROKE_WIDTH,
            stroke_fill=(*_STROKE_RGB, 255),
        )
        x += word_widths[i] + space_w

    return np.array(img)


def _build_interactive_subtitles(
    segments: list[Segment],
    clip_width: int,
    clip_height: int,
    on_log: Optional[LogCallback] = None,
    y_ratio: Optional[float] = None,
) -> list[ImageClip]:
    """
    Create word-by-word highlighted subtitle clips from transcript segments.

    Each segment is split into small groups of words. Within each group the
    current word is highlighted while the rest stay white, producing a
    karaoke-style reading effect.
    """
    font_size = max(32, int(clip_width * 0.054))
    font = _find_bold_font(font_size)
    y_pos = int(clip_height * (y_ratio or _SUBTITLE_Y_RATIO))

    clips: list[ImageClip] = []

    for seg in segments:
        text = _clean_text(seg["text"])
        words = text.split()
        if not words:
            continue

        seg_start: float = seg["start"]
        seg_duration: float = seg["end"] - seg_start
        if seg_duration <= 0:
            continue

        time_per_word = seg_duration / len(words)

        groups: list[list[str]] = []
        for i in range(0, len(words), _WORDS_PER_GROUP):
            groups.append(words[i : i + _WORDS_PER_GROUP])

        global_word_idx = 0
        for group in groups:
            for local_idx in range(len(group)):
                t_start = seg_start + global_word_idx * time_per_word

                frame_rgba = _render_word_group_frame(
                    group, local_idx, clip_width, font
                )
                rgb = frame_rgba[:, :, :3]
                alpha = frame_rgba[:, :, 3].astype(np.float64) / 255.0

                mask = ImageClip(alpha, ismask=True).set_duration(time_per_word)
                clip = (
                    ImageClip(rgb)
                    .set_mask(mask)
                    .set_position((0, y_pos))
                    .set_start(t_start)
                    .set_duration(time_per_word)
                )
                clips.append(clip)
                global_word_idx += 1

    _log(on_log, f"Created {len(clips)} interactive subtitle frames", "info")
    return clips


# ── Audio extraction ──────────────────────────────────────────────────────────


def extract_audio(
    video_path: str | Path,
    on_log: Optional[LogCallback] = None,
) -> Path:
    """Extract the audio track from *video_path* to a temporary WAV file."""
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
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    subtitles: bool = True,
    background_video: Optional[str | Path] = None,
    on_log: Optional[LogCallback] = None,
) -> CompositeVideoClip:
    """Crop a time range of the source to 9:16, optionally overlay subtitles.

    When *background_video* is provided the output is split-screen: the main
    content occupies the top portion and the background fills the bottom.

    Uses face-tracking smart crop so the virtual camera follows the subject
    instead of always cropping to the dead centre of the frame.
    """
    from src.engine.smart_crop import apply_smart_crop, compute_crop_trajectory

    _log(on_log, "Building vertical clip…", "info")

    source = VideoFileClip(str(video_path))
    real_end = min(end_time, source.duration) if end_time is not None else source.duration
    source = source.subclip(start_time, real_end) if end_time or start_time else source

    clip_dur = source.duration
    src_w, src_h = source.size

    canvas_w = int(src_h * 9 / 16)
    if canvas_w > src_w:
        canvas_w = src_w
    canvas_h = src_h

    # Compute face-tracking trajectory for the wider capture window
    from src.engine.smart_crop import _ZOOM_OUT_FACTOR
    capture_w = min(int(canvas_w * _ZOOM_OUT_FACTOR), src_w)
    trajectory = compute_crop_trajectory(
        str(video_path), capture_w,
        start_time=start_time, end_time=real_end,
        on_log=on_log,
    )

    if background_video:
        return _build_split_screen(
            source, canvas_w, canvas_h, clip_dur, segments,
            subtitles, background_video, trajectory, on_log,
        )

    # ── Standard (full-frame) mode ───────────────────────────────────
    if trajectory:
        cropped = apply_smart_crop(source, trajectory, canvas_w)
    else:
        x_center = src_w / 2
        x1 = int(x_center - canvas_w / 2)
        cropped = source.crop(x1=x1, y1=0, x2=x1 + canvas_w, y2=canvas_h)

    _log(on_log, f"Crop: {src_w}x{src_h} → {canvas_w}x{canvas_h}", "debug")

    sub_clips: list[ImageClip] = []
    if subtitles and segments:
        sub_clips = _build_interactive_subtitles(
            segments, canvas_w, canvas_h, on_log
        )
    elif not subtitles:
        _log(on_log, "Subtitles disabled", "debug")

    composite = CompositeVideoClip([cropped, *sub_clips], size=(canvas_w, canvas_h))
    composite.audio = cropped.audio
    return composite


def _build_split_screen(
    source: VideoFileClip,
    canvas_w: int,
    canvas_h: int,
    clip_dur: float,
    segments: list[Segment],
    subtitles: bool,
    background_video: str | Path,
    trajectory: list[tuple[float, int]],
    on_log: Optional[LogCallback] = None,
) -> CompositeVideoClip:
    """Compose a split-screen clip: main content on top, background on bottom."""
    from src.engine.smart_crop import apply_smart_crop

    src_w, src_h = source.size
    top_h = int(canvas_h * _SPLIT_MAIN_RATIO)
    bot_h = canvas_h - top_h

    _log(on_log, f"Split screen: top={top_h}px, bottom={bot_h}px", "debug")

    # ── Top: main content (smart-crop to canvas_w × top_h) ───────────
    if trajectory:
        main_crop = apply_smart_crop(source, trajectory, canvas_w, canvas_h=top_h)
    else:
        x_center = src_w / 2
        x1 = int(x_center - canvas_w / 2)
        y_center = src_h / 2
        y1 = max(0, int(y_center - top_h / 2))
        y2 = min(src_h, y1 + top_h)
        if y2 - y1 < top_h:
            y1 = max(0, y2 - top_h)
        main_crop = source.crop(x1=x1, y1=y1, x2=x1 + canvas_w, y2=y2)

    main_crop = main_crop.set_position((0, 0))

    # ── Bottom: background video (resize + crop + loop) ──────────────
    bg_source = VideoFileClip(str(background_video))
    bg_w, bg_h = bg_source.size

    scale = max(canvas_w / bg_w, bot_h / bg_h)
    new_w = int(bg_w * scale)
    new_h = int(bg_h * scale)
    bg_resized = bg_source.resize((new_w, new_h))

    bx1 = (new_w - canvas_w) // 2
    by1 = (new_h - bot_h) // 2
    bg_cropped = bg_resized.crop(x1=bx1, y1=by1, x2=bx1 + canvas_w, y2=by1 + bot_h)

    if bg_cropped.duration < clip_dur:
        bg_cropped = bg_cropped.fx(vfx.loop, duration=clip_dur)
    else:
        bg_cropped = bg_cropped.subclip(0, clip_dur)

    bg_cropped = bg_cropped.set_position((0, top_h))

    # ── Subtitles (positioned in the top half) ───────────────────────
    sub_clips: list[ImageClip] = []
    if subtitles and segments:
        sub_clips = _build_interactive_subtitles(
            segments, canvas_w, top_h, on_log,
            y_ratio=_SUBTITLE_Y_RATIO_SPLIT,
        )
    elif not subtitles:
        _log(on_log, "Subtitles disabled", "debug")

    layers = [main_crop, bg_cropped, *sub_clips]
    composite = CompositeVideoClip(layers, size=(canvas_w, canvas_h))
    composite.audio = main_crop.audio
    return composite


# ── Render ────────────────────────────────────────────────────────────────────


class _RenderProgressLogger:
    """Minimal moviepy-compatible logger that forwards progress to the app console."""

    def __init__(self, on_log: Optional[LogCallback], label: str, total_frames: int):
        self._on_log = on_log
        self._label = label
        self._total = total_frames
        self._last_pct = -1

    def bars_callback(self, bar, attr, value, old_value=None):
        if attr == "index" and self._total > 0:
            pct = int(value / self._total * 100)
            if pct >= self._last_pct + 10:
                self._last_pct = pct
                _log(self._on_log, f"{self._label}: {pct}% encoded", "debug")

    # moviepy 1.x calls these; keep them as no-ops
    def callback(self, **kw):
        pass

    def __call__(self, *a, **kw):
        pass


def _render_single_clip(
    video_path: str | Path,
    segments: list[Segment],
    output_path: Path,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    subtitles: bool = True,
    background_video: Optional[str | Path] = None,
    on_log: Optional[LogCallback] = None,
) -> Path:
    """Build and encode a single vertical clip to *output_path*."""
    composite = _build_vertical_clip(
        video_path, segments, start_time, end_time,
        subtitles, background_video, on_log,
    )
    total_frames = int(composite.fps * composite.duration)
    start_m, start_s = divmod(int(start_time), 60)
    end_m, end_s = divmod(int(end_time or 0), 60)
    time_label = f"{start_m}:{start_s:02d}–{end_m}:{end_s:02d}"

    _log(on_log, f"Encoding {output_path.name} [{time_label}] — {total_frames} frames", "info")

    # Use writable temp dir for MoviePy temp files (avoids "Read-only file system" when running from DMG)
    _temp_dir = Path(tempfile.gettempdir()) / "CustosAI-Clipper" / "render"
    _temp_dir.mkdir(parents=True, exist_ok=True)
    _temp_audio = _temp_dir / f"temp_{output_path.stem}.m4a"

    t0 = time.perf_counter()
    composite.write_videofile(
        str(output_path),
        codec="libx264",
        audio_codec="aac",
        fps=composite.fps,
        preset="medium",
        threads=max(1, os.cpu_count() or 4),
        logger=None,
        temp_audiofile=str(_temp_audio),
        remove_temp=True,
    )
    composite.close()

    elapsed = time.perf_counter() - t0
    _log(on_log, f"Render complete in {elapsed:.1f}s → {output_path.name}", "success")
    return output_path


def _unique_path(output_dir: Path, stem: str, index: int) -> Path:
    """Generate a non-colliding output filename."""
    base = output_dir / f"{stem}_clip{index}.mp4"
    counter = 1
    while base.exists():
        base = output_dir / f"{stem}_clip{index}_{counter}.mp4"
        counter += 1
    return base


# ── Phase 1: Analyze (transcribe + select clips) ─────────────────────────────


def analyze_video(
    video_path: str | Path,
    model_size: str = "base",
    clip_length: int = 45,
    max_clips: int = 5,
    on_log: Optional[LogCallback] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> list[ClipRegion]:
    """
    Transcribe, detect scene changes, and select clip regions.

    Steps:
        1. Extract audio         (0%  - 10%)
        2. Transcribe            (10% - 65%)
        3. Detect scene changes  (65% - 85%)
        4. Select clip regions   (85% - 100%)

    Returns:
        List of ClipRegion candidates.
    """
    from src.engine.ai_transcriber import load_model, transcribe
    from src.engine.clip_selector import select_clips
    from src.engine.scene_detector import detect_scene_changes

    if on_progress:
        on_progress(0.0, "Starting analysis…")

    # ── Step 1: audio extraction ─────────────────────────────────────
    audio_path = extract_audio(video_path, on_log)
    if on_progress:
        on_progress(0.10, "Audio extracted")

    # ── Step 2: transcription ────────────────────────────────────────
    if on_progress:
        on_progress(0.12, "Loading Whisper model…")

    model = load_model(model_size, on_progress=on_log)
    if on_progress:
        on_progress(0.18, "Transcribing audio…")

    segments = transcribe(model, audio_path, on_progress=on_log)
    if on_progress:
        on_progress(0.65, f"Transcribed {len(segments)} segments")

    try:
        Path(audio_path).unlink(missing_ok=True)
    except Exception:
        pass

    if not segments:
        _log(on_log, "No speech detected — aborting.", "error")
        raise RuntimeError("Transcription produced no segments.")

    # ── Step 3: scene change detection ───────────────────────────────
    if on_progress:
        on_progress(0.67, "Detecting scene changes…")

    scene_changes = detect_scene_changes(video_path, on_log=on_log)
    if on_progress:
        on_progress(0.85, f"Found {len(scene_changes)} scene cuts")

    # ── Step 4: clip selection ───────────────────────────────────────
    source = VideoFileClip(str(video_path))
    video_duration = source.duration
    source.close()

    regions = select_clips(
        segments,
        video_duration=video_duration,
        clip_length=clip_length,
        max_clips=max_clips,
        scene_changes=scene_changes,
    )

    if not regions:
        _log(on_log, "No suitable clip regions found.", "error")
        raise RuntimeError("Clip selection produced no regions.")

    _log(on_log, f"Found {len(regions)} clip candidate(s):", "info")
    for i, r in enumerate(regions, 1):
        _log(
            on_log,
            f"  Clip {i}: {r.start:.1f}s – {r.end:.1f}s "
            f"({r.duration:.0f}s, score {r.score:.2f})",
            "info",
        )

    if on_progress:
        on_progress(1.0, "Analysis complete")

    return regions


# ── Phase 2: Render selected clips ───────────────────────────────────────────


def render_selected_clips(
    video_path: str | Path,
    regions: list[ClipRegion],
    output_dir: str | Path,
    subtitles: bool = True,
    background_video: Optional[str | Path] = None,
    on_log: Optional[LogCallback] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> list[Path]:
    """Render only the user-selected clip regions."""
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem

    results: list[Path] = []
    total = len(regions)

    for idx, region in enumerate(regions, 1):
        pct = (idx - 1) / total
        start_m, start_s = divmod(int(region.start), 60)
        end_m, end_s = divmod(int(region.end), 60)
        time_label = f"{start_m}:{start_s:02d} – {end_m}:{end_s:02d}"

        if on_progress:
            on_progress(pct, f"Rendering clip {idx}/{total} ({time_label})…")
        _log(on_log, f"Clip {idx}/{total}: {time_label} (score {region.score:.2f})", "info")

        out_path = _unique_path(output_dir, stem, idx)
        _render_single_clip(
            video_path=video_path,
            segments=region.segments,
            output_path=out_path,
            start_time=region.start,
            end_time=region.end,
            subtitles=subtitles,
            background_video=background_video,
            on_log=on_log,
        )
        results.append(out_path)

    if on_progress:
        on_progress(1.0, "Done")

    return results


# ── Helpers ───────────────────────────────────────────────────────────────────


def _log(cb: Optional[LogCallback], msg: str, level: str) -> None:
    getattr(logger, level if level != "success" else "info")(msg)
    if cb:
        cb(msg, level)
