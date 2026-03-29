"""
Smart face-tracking crop for CustosAI Clipper.

Instead of a static centre-crop, this module:
    1. Samples frames at regular intervals and detects faces (Haar cascade).
    2. Falls back to motion-energy analysis when no face is found.
    3. Applies exponential-moving-average (EMA) smoothing so the virtual
       camera pans smoothly instead of jumping between frames.
    4. Returns a moviepy ``VideoClip`` whose horizontal crop position tracks
       the detected subject on every frame.

Only requires ``opencv-python-headless`` (already a project dependency).
"""

from __future__ import annotations

import logging
import sys
from typing import Callable, Optional

import cv2
import numpy as np
from moviepy.editor import VideoClip, VideoFileClip

from src.utils.paths import get_base_path

logger = logging.getLogger(__name__)

LogCallback = Callable[[str, str], None]

_SAMPLE_INTERVAL = 0.5           # seconds between analysed frames (fewer = less jumpy)
_DOWNSCALE_WIDTH = 320           # resize width for face detection (speed)
_EMA_ALPHA = 0.15                # smoothing factor (lower = smoother pan, less dizzy)
_FACE_SCALE_FACTOR = 1.15
_FACE_MIN_NEIGHBOURS = 5
_FACE_MIN_SIZE_RATIO = 0.06     # min face size as fraction of frame width
_ZOOM_OUT_FACTOR = 1.15          # capture 15 % wider than 9:16, then resize


def _get_cascade_path() -> str:
    """Return path to haarcascade_frontalface_default.xml (works when bundled)."""
    if getattr(sys, "frozen", False):
        return str(get_base_path() / "cv2" / "data" / "haarcascade_frontalface_default.xml")
    return cv2.data.haarcascades + "haarcascade_frontalface_default.xml"


# ── Trajectory computation ───────────────────────────────────────────────────


def compute_crop_trajectory(
    video_path: str,
    canvas_w: int,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    sample_interval: float = _SAMPLE_INTERVAL,
    on_log: Optional[LogCallback] = None,
) -> list[tuple[float, int]]:
    """Analyse the portion of *video_path* between *start_time* and
    *end_time* and return ``[(relative_timestamp, x_offset), ...]``.

    Returned timestamps start at 0 (relative to the subclip) so they can
    be used directly with the moviepy subclip.  x_offsets are EMA-smoothed
    and clamped to valid pixel ranges.
    """
    _log(on_log, "Analysing face positions for smart crop…", "info")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        _log(on_log, "Could not open video for smart crop — falling back to centre", "warning")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    duration = total_frames / fps if fps > 0 else 0.0

    if end_time is None or end_time > duration:
        end_time = duration

    frame_step = max(1, int(fps * sample_interval))

    if canvas_w >= src_w:
        cap.release()
        _log(on_log, "Source width <= crop width — no panning needed", "debug")
        return []

    cascade = cv2.CascadeClassifier(_get_cascade_path())
    if cascade.empty():
        cap.release()
        _log(on_log, "Haar cascade not found — falling back to centre crop", "warning")
        return []

    min_face_px = max(20, int(src_w * _FACE_MIN_SIZE_RATIO))
    scale = _DOWNSCALE_WIDTH / src_w
    scaled_min_face = max(15, int(min_face_px * scale))
    default_x = (src_w - canvas_w) // 2

    start_frame = int(start_time * fps)
    end_frame = int(end_time * fps)
    clip_frames = end_frame - start_frame

    if start_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    raw_points: list[tuple[float, int]] = []
    prev_gray: Optional[np.ndarray] = None
    frame_idx = 0
    face_hits = 0
    motion_hits = 0
    next_log_pct = 25

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        abs_frame = start_frame + frame_idx
        if abs_frame >= end_frame:
            break

        if frame_idx % frame_step == 0:
            rel_t = frame_idx / fps
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (0, 0), fx=scale, fy=scale)

            x_center = _detect_faces(cascade, small, scale, src_w, scaled_min_face)
            if x_center is not None:
                face_hits += 1
            else:
                x_center = _detect_motion(small, prev_gray, scale, src_w)
                if x_center is not None:
                    motion_hits += 1

            prev_gray = small

            if x_center is not None:
                x_off = int(x_center - canvas_w / 2)
                x_off = max(0, min(x_off, src_w - canvas_w))
            else:
                x_off = default_x

            raw_points.append((rel_t, x_off))

            if clip_frames > 0 and on_log:
                pct = int(frame_idx / clip_frames * 100)
                if pct >= next_log_pct:
                    on_log(f"Smart crop: {pct}% analysed ({face_hits} face hits)", "debug")
                    next_log_pct = pct + 25

        frame_idx += 1

    cap.release()

    if not raw_points:
        _log(on_log, "No frames sampled — falling back to centre crop", "warning")
        return []

    smoothed = _smooth_trajectory(raw_points, src_w, canvas_w)

    _log(
        on_log,
        f"Smart crop: {len(smoothed)} samples, "
        f"{face_hits} face detections, {motion_hits} motion fallbacks",
        "info",
    )
    return smoothed


# ── Face detection ───────────────────────────────────────────────────────────


def _detect_faces(
    cascade: cv2.CascadeClassifier,
    small_gray: np.ndarray,
    scale: float,
    src_w: int,
    min_face: int,
) -> Optional[int]:
    """Return the x-centre of the largest face (main subject), or None."""
    faces = cascade.detectMultiScale(
        small_gray,
        scaleFactor=_FACE_SCALE_FACTOR,
        minNeighbors=_FACE_MIN_NEIGHBOURS,
        minSize=(min_face, min_face),
    )
    if len(faces) == 0:
        return None

    # Use largest face only — avoids jumpy pan when 2+ faces
    largest = max(faces, key=lambda f: f[2] * f[3])
    x, y, w, h = largest
    return int((x + w / 2) / scale)


# ── Motion fallback ──────────────────────────────────────────────────────────


def _detect_motion(
    small_gray: np.ndarray,
    prev_gray: Optional[np.ndarray],
    scale: float,
    src_w: int,
) -> Optional[int]:
    """Return the x-centre of the region with most motion, or None."""
    if prev_gray is None:
        return None
    if small_gray.shape != prev_gray.shape:
        return None

    diff = cv2.absdiff(small_gray, prev_gray)
    col_energy = diff.sum(axis=0).astype(np.float64)

    if col_energy.max() < 500:
        return None

    kernel_w = max(1, len(col_energy) // 6)
    kernel = np.ones(kernel_w) / kernel_w
    smoothed = np.convolve(col_energy, kernel, mode="same")

    peak_col = int(np.argmax(smoothed))
    return int(peak_col / scale)


# ── Smoothing ────────────────────────────────────────────────────────────────


def _smooth_trajectory(
    raw: list[tuple[float, int]],
    src_w: int,
    canvas_w: int,
) -> list[tuple[float, int]]:
    """Apply EMA smoothing and clamp offsets."""
    if not raw:
        return raw

    smoothed: list[tuple[float, int]] = []
    prev = raw[0][1]
    max_off = src_w - canvas_w

    for t, x in raw:
        s = _EMA_ALPHA * x + (1 - _EMA_ALPHA) * prev
        clamped = max(0, min(int(s), max_off))
        smoothed.append((t, clamped))
        prev = s

    return smoothed


# ── Apply crop ───────────────────────────────────────────────────────────────


def apply_smart_crop(
    source: VideoFileClip,
    trajectory: list[tuple[float, int]],
    canvas_w: int,
    canvas_h: Optional[int] = None,
) -> VideoClip:
    """Return a new clip dynamically cropped per-frame using *trajectory*.

    Captures a region wider than *canvas_w* (controlled by
    ``_ZOOM_OUT_FACTOR``) and resizes it down, giving a slight zoom-out
    so faces don't fill the entire frame.

    If *canvas_h* is given (split-screen mode), the vertical crop is also
    centre-based with that height. Otherwise the full source height is kept.
    """
    src_w, src_h = source.size
    out_h = canvas_h if canvas_h is not None else src_h

    capture_w = min(int(canvas_w * _ZOOM_OUT_FACTOR), src_w)
    capture_h = min(int(out_h * _ZOOM_OUT_FACTOR), src_h)
    y1 = max(0, (src_h - capture_h) // 2)

    times = np.array([t for t, _ in trajectory], dtype=np.float64)
    offsets = np.array([x for _, x in trajectory], dtype=np.float64)

    def _make_frame(t: float) -> np.ndarray:
        frame = source.get_frame(t)
        x = int(np.interp(t, times, offsets))
        x = max(0, min(x, src_w - capture_w))
        cropped = frame[y1 : y1 + capture_h, x : x + capture_w]
        return cv2.resize(cropped, (canvas_w, out_h), interpolation=cv2.INTER_AREA)

    result = VideoClip(_make_frame, duration=source.duration)
    result.fps = source.fps
    result.audio = source.audio
    return result


# ── Helpers ──────────────────────────────────────────────────────────────────


def _log(cb: Optional[LogCallback], msg: str, level: str) -> None:
    getattr(logger, level if level != "success" else "info")(msg)
    if cb:
        cb(msg, level)
