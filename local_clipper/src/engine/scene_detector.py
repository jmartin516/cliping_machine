"""
Scene change detection for CustosAI Clipper.

Compares colour histograms of sampled frames to find visual cuts.
Uses OpenCV with no GPU requirement — runs on CPU in seconds even
for long videos thanks to sequential reading with frame skipping.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

LogCallback = Callable[[str, str], None]

_SAMPLE_INTERVAL = 0.5   # seconds between sampled frames
_HIST_THRESHOLD = 0.55   # correlation below this = scene change
_HIST_BINS = 64


def detect_scene_changes(
    video_path: str | Path,
    sample_interval: float = _SAMPLE_INTERVAL,
    threshold: float = _HIST_THRESHOLD,
    on_log: Optional[LogCallback] = None,
) -> list[float]:
    """
    Return timestamps (in seconds) where a scene change is detected.

    Reads frames sequentially (fast) and only analyses every
    *sample_interval* seconds. Compares HSV colour histograms between
    consecutive sampled frames via correlation.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        if on_log:
            on_log("Could not open video for scene detection", "warning")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    frame_step = max(1, int(fps * sample_interval))

    prev_hist: Optional[np.ndarray] = None
    scene_changes: list[float] = []
    frame_idx = 0
    next_log_pct = 25

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_idx % frame_step == 0:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist(
                [hsv], [0, 1], None,
                [_HIST_BINS, _HIST_BINS],
                [0, 180, 0, 256],
            )
            cv2.normalize(hist, hist)

            if prev_hist is not None:
                corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                if corr < threshold:
                    t = frame_idx / fps
                    scene_changes.append(round(t, 3))

            prev_hist = hist

            if total_frames > 0 and on_log:
                pct = int(frame_idx / total_frames * 100)
                if pct >= next_log_pct:
                    on_log(
                        f"Scene detection: {pct}% "
                        f"({len(scene_changes)} cuts so far)",
                        "debug",
                    )
                    next_log_pct = pct + 25

        frame_idx += 1

    cap.release()

    logger.info(
        "Scene detection: %d cuts in %.0fs video (sampled every %.1fs)",
        len(scene_changes), duration, sample_interval,
    )
    if on_log:
        on_log(
            f"Detected {len(scene_changes)} scene changes in {duration:.0f}s video",
            "info",
        )

    return scene_changes
