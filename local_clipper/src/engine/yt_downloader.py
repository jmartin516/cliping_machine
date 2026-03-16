"""
YouTube video downloader powered by yt-dlp.

Downloads a video from a YouTube URL to a local file, reporting progress
via the same callback interface used by the rest of the pipeline.

Prefers the standalone yt-dlp binary (fetched from custosai-clipper-config)
when available, so YouTube compatibility can be updated without rebuilding.
Falls back to the bundled Python library if the binary is unavailable.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from src.utils.paths import get_bundled_ffmpeg_dir
from src.utils.ytdlp_updater import get_or_update_ytdlp_binary

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]
LogCallback = Callable[[str, str], None]
CheckCancelledCallback = Callable[[], None]

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


_FORMAT = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best"


def _download_with_binary(
    url: str,
    download_dir: Path,
    ffmpeg_path: Optional[str],
    browser: Optional[str],
    on_log: Optional[LogCallback],
    on_progress: Optional[ProgressCallback],
    check_cancelled: Optional[CheckCancelledCallback] = None,
) -> Optional[Path]:
    """Download using the standalone yt-dlp binary. Returns Path on success, None to fall back."""
    ytdlp_path = get_or_update_ytdlp_binary(on_log=on_log)
    if not ytdlp_path or not ytdlp_path.exists():
        return None

    run_dir = download_dir / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(run_dir / "%(id)s.%(ext)s")

    cmd = [
        str(ytdlp_path),
        "-o", outtmpl,
        "-f", _FORMAT,
        "--merge-output-format", "mp4",
        "--no-warnings",
        "--quiet",
        url,
    ]
    if browser:
        cmd.extend(["--cookies-from-browser", browser])

    env = os.environ.copy()
    if ffmpeg_path:
        ffmpeg_dir = str(Path(ffmpeg_path).parent)
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")
        env["FFMPEG_BINARY"] = ffmpeg_path
    # When running from a PyInstaller/DMG bundle on macOS, inherited PATH can be minimal.
    # Ensure /usr/bin and /usr/local/bin are available for ffmpeg and other tools.
    if getattr(sys, "frozen", False) and sys.platform == "darwin":
        extra_paths = "/usr/bin:/usr/local/bin"
        env["PATH"] = env.get("PATH", "") + os.pathsep + extra_paths

    # The yt-dlp binary is also a PyInstaller build. If it inherits DYLD_LIBRARY_PATH etc.
    # from our app bundle, it loads the wrong Python runtime and fails with:
    # "Failed to allocate PyConfig structure! Unsupported python version?"
    for key in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
        env.pop(key, None)

    _log(on_log, f"Using yt-dlp binary: {ytdlp_path.name}", "debug")
    if on_progress:
        on_progress(0.1, "Downloading with yt-dlp…")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    stderr_output: str | None = None

    try:
        if check_cancelled:
            proc = subprocess.Popen(
                cmd,
                env=env,
                cwd=str(run_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
            while proc.poll() is None:
                if check_cancelled:
                    try:
                        check_cancelled()
                    except RuntimeError:
                        proc.terminate()
                        proc.wait(timeout=5)
                        raise
                time.sleep(0.5)
            if proc.stderr:
                stderr_output = proc.stderr.read().decode("utf-8", errors="replace").strip()
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=stderr_output or "")
        else:
            result = subprocess.run(
                cmd,
                env=env,
                cwd=str(run_dir),
                capture_output=True,
                timeout=3600,
                creationflags=creationflags,
            )
            if result.returncode != 0:
                stderr_output = result.stderr.decode("utf-8", errors="replace").strip() if result.stderr else ""
                raise subprocess.CalledProcessError(
                    result.returncode, cmd, stderr=stderr_output or ""
                )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        err_detail = ""
        if isinstance(exc, subprocess.CalledProcessError) and getattr(exc, "stderr", None):
            err_detail = f" | stderr: {exc.stderr[:800]}" if exc.stderr else ""
        _log(on_log, f"yt-dlp binary failed: {exc}{err_detail}", "warning")
        return None

    mp4_files = list(run_dir.glob("*.mp4"))
    if not mp4_files:
        _log(on_log, "yt-dlp binary produced no output file", "warning")
        return None

    src = mp4_files[0]
    # Move to main download_dir for consistency with library path
    dst = download_dir / src.name
    shutil.move(str(src), str(dst))
    try:
        shutil.rmtree(run_dir, ignore_errors=True)
    except Exception:
        pass
    return dst


def download_video(
    url: str,
    on_log: Optional[LogCallback] = None,
    on_progress: Optional[ProgressCallback] = None,
    check_cancelled: Optional[CheckCancelledCallback] = None,
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

    # Resolve FFmpeg path for both binary and library
    ffmpeg_path = os.environ.get("FFMPEG_BINARY") or os.environ.get("IMAGEIO_FFMPEG_EXE")
    if not ffmpeg_path:
        bundled = get_bundled_ffmpeg_dir()
        if bundled:
            ffmpeg_path = str(bundled / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"))
    if ffmpeg_path and os.path.isfile(ffmpeg_path):
        ffmpeg_path = str(Path(ffmpeg_path).resolve())
        _log(on_log, f"Using FFmpeg: {Path(ffmpeg_path).name}", "debug")

    browser = _detect_browser()
    if browser:
        _log(on_log, f"Using cookies from {browser} (for age-restricted videos)", "debug")

    # Try standalone binary first (allows updates without app rebuild)
    result = _download_with_binary(
        url, download_dir, ffmpeg_path, browser, on_log, on_progress, check_cancelled
    )
    if result is not None:
        elapsed = time.perf_counter() - t0
        size_mb = result.stat().st_size / (1024 * 1024)
        _log(on_log, f"Downloaded {size_mb:.1f} MB in {elapsed:.1f}s → {result.name}", "success")
        if on_progress:
            on_progress(1.0, "Download complete")
        return result

    # Fall back to bundled Python library
    _log(on_log, "Using bundled yt-dlp library", "debug")

    def _progress_hook(d: dict) -> None:
        if check_cancelled:
            check_cancelled()
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

    ydl_opts: dict = {
        "format": _FORMAT,
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "progress_hooks": [_progress_hook],
        "quiet": True,
        "no_warnings": True,
    }
    if ffmpeg_path and os.path.isfile(ffmpeg_path):
        ydl_opts["ffmpeg_location"] = ffmpeg_path

    if browser:
        ydl_opts["cookiesfrombrowser"] = (browser,)

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
