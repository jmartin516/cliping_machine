"""
YouTube video downloader powered by yt-dlp.

Downloads a video from a YouTube URL to a local file, reporting progress
via the same callback interface used by the rest of the pipeline.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from src.utils.paths import get_bundled_ffmpeg_dir

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]
LogCallback = Callable[[str, str], None]

_YT_URL_PATTERN = re.compile(
    r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+"
)

_BROWSER_PRIORITY = ["chrome", "firefox", "brave", "edge", "safari", "opera"]


def _detect_browser() -> Optional[str]:
    """Return the name of the first installed browser that yt-dlp can use."""
    for name in _BROWSER_PRIORITY:
        if shutil.which(name) or shutil.which(f"google-{name}") or shutil.which(f"google-{name}-stable"):
            return name
    return None


def is_youtube_url(url: str) -> bool:
    return bool(_YT_URL_PATTERN.match(url.strip()))


def download_video(
    url: str,
    on_log: Optional[LogCallback] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> Path:
    """
    Download a YouTube video as an mp4 file to a temp directory.

    Uses a dedicated temp dir to avoid path/permission issues when running
    from a bundled app (e.g. DMG on macOS). The caller should delete the
    file after processing.

    Args:
        url:         YouTube URL.
        on_log:      ``(message, level)`` callback for UI log lines.
        on_progress: ``(0.0-1.0, status)`` callback for the progress bar.

    Returns:
        Path to the downloaded ``.mp4`` file.

    Raises:
        ValueError:  If the URL doesn't look like a YouTube link.
        RuntimeError: If the download fails.
    """
    url = url.strip()
    if not is_youtube_url(url):
        raise ValueError(f"Not a valid YouTube URL: {url}")

    download_dir = Path(tempfile.gettempdir()) / "CustosAI-Clipper" / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    _log(on_log, f"Download dir: {download_dir}", "debug")

    _log(on_log, f"Downloading: {url}", "info")
    if on_progress:
        on_progress(0.0, "Connecting to YouTube…")

    t0 = time.perf_counter()

    def _progress_hook(d: dict) -> None:
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                pct = downloaded / total
                if on_progress:
                    on_progress(pct * 0.90, f"Downloading… {pct:.0%}")
        elif d["status"] == "finished":
            _log(on_log, "Download finished, merging…", "info")
            if on_progress:
                on_progress(0.92, "Merging audio + video…")

    outtmpl = str(download_dir / "%(title)s.%(ext)s")

    # yt-dlp needs ffmpeg to merge video+audio; use bundled or env path
    ffmpeg_path = os.environ.get("FFMPEG_BINARY") or os.environ.get("IMAGEIO_FFMPEG_EXE")
    if not ffmpeg_path:
        bundled = get_bundled_ffmpeg_dir()
        if bundled:
            ffmpeg_path = str(bundled / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"))
    if ffmpeg_path and os.path.isfile(ffmpeg_path):
        ffmpeg_path = str(Path(ffmpeg_path).resolve())
        _log(on_log, f"Using FFmpeg: {Path(ffmpeg_path).name}", "debug")

    ydl_opts: dict = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "progress_hooks": [_progress_hook],
        "quiet": True,
        "no_warnings": True,
    }
    if ffmpeg_path and os.path.isfile(ffmpeg_path):
        ydl_opts["ffmpeg_location"] = ffmpeg_path

    browser = _detect_browser()
    if browser:
        ydl_opts["cookiesfrombrowser"] = (browser,)
        _log(on_log, f"Using cookies from {browser} (for age-restricted videos)", "debug")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise RuntimeError("yt-dlp returned no info for this URL.")
            result = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    except Exception as first_err:
        if "cookiesfrombrowser" not in ydl_opts:
            raise RuntimeError(f"YouTube download failed: {first_err}") from first_err
        _log(on_log, "Cookie-based download failed, retrying without cookies…", "warning")
        ydl_opts.pop("cookiesfrombrowser", None)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise RuntimeError("yt-dlp returned no info for this URL.")
                result = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
        except Exception as exc:
            raise RuntimeError(f"YouTube download failed: {exc}") from exc

    if not result.exists():
        raise RuntimeError(f"Expected output not found: {result}")

    elapsed = time.perf_counter() - t0
    size_mb = result.stat().st_size / (1024 * 1024)
    _log(on_log, f"Downloaded {size_mb:.1f} MB in {elapsed:.1f}s → {result.name}", "success")

    if on_progress:
        on_progress(1.0, "Download complete")

    return result


def _log(cb: Optional[LogCallback], msg: str, level: str) -> None:
    getattr(logger, level if level != "success" else "info")(msg)
    if cb:
        cb(msg, level)
