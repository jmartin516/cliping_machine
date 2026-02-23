"""
CustosAI Clipper — Main application window.

Houses two views that are swapped in-place:
    1. **LoginView**     – License key entry + activation.
    2. **DashboardView** – Video processing controls, progress, and log console.

Threading contract:
    - License validation runs on a daemon thread so the GUI never blocks.
    - Video processing runs on daemon threads, posting progress updates
      back to the main loop via ``after_idle``.
"""

from __future__ import annotations

import logging
import platform
import threading
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from src.auth.whop_api import ValidationFailure, ValidationSuccess, validate_license
from src.gui.components import (
    COLORS,
    LabeledOptionMenu,
    LabeledSlider,
    LogConsole,
    PathSelector,
    StatusProgressBar,
    YouTubeInput,
)

logger = logging.getLogger(__name__)

_APP_TITLE = "CustosAI Clipper"
_WINDOW_SIZE = "900x680"
_MIN_SIZE = (780, 600)

_ASSETS = Path(__file__).resolve().parents[2] / "assets"

# Set to True to skip Whop license validation during development.
_DEV_SKIP_LOGIN = True


def _apply_icon(window: ctk.CTk) -> None:
    try:
        if platform.system() == "Windows":
            ico = _ASSETS / "icon.ico"
            if ico.exists():
                window.iconbitmap(str(ico))
        else:
            png = _ASSETS / "icon.png"
            if png.exists():
                from tkinter import PhotoImage
                icon = PhotoImage(file=str(png))
                window.iconphoto(True, icon)
    except Exception:
        logger.debug("Window icon not applied — non-critical, skipping")


# ══════════════════════════════════════════════════════════════════════════════
#  Login View
# ══════════════════════════════════════════════════════════════════════════════


class LoginView(ctk.CTkFrame):
    """Minimalist centered card with a license-key field and Activate button."""

    def __init__(self, master: LocalClipperApp, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_dark"], **kwargs)
        self._app = master

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        card = ctk.CTkFrame(
            self,
            width=420,
            fg_color=COLORS["bg_card"],
            corner_radius=18,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.grid(row=0, column=0)
        card.grid_propagate(False)
        card.configure(height=340)
        card.grid_rowconfigure(5, weight=1)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text="CustosAI Clipper",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, pady=(36, 2))

        ctk.CTkLabel(
            card,
            text="Enter your license key to continue",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
        ).grid(row=1, column=0, pady=(0, 24))

        self._key_entry = ctk.CTkEntry(
            card,
            width=320,
            height=42,
            placeholder_text="XXXX-XXXX-XXXX-XXXX",
            font=ctk.CTkFont(size=14),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            corner_radius=10,
            justify="center",
        )
        self._key_entry.grid(row=2, column=0, pady=(0, 16))
        self._key_entry.bind("<Return>", lambda _: self._on_activate())

        self._activate_btn = ctk.CTkButton(
            card,
            text="Activate",
            width=320,
            height=42,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            corner_radius=10,
            command=self._on_activate,
        )
        self._activate_btn.grid(row=3, column=0, pady=(0, 12))

        self._status = ctk.CTkLabel(
            card,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"],
            wraplength=300,
        )
        self._status.grid(row=4, column=0, pady=(0, 20))

    def _on_activate(self) -> None:
        key = self._key_entry.get().strip()
        if not key:
            self._show_status("Please enter a license key.", COLORS["warning"])
            return
        self._activate_btn.configure(state="disabled", text="Validating…")
        self._show_status("Contacting license server…", COLORS["text_muted"])
        threading.Thread(target=self._validate_worker, args=(key,), daemon=True).start()

    def _validate_worker(self, key: str) -> None:
        result = validate_license(key)
        self.after_idle(self._handle_result, result)

    def _handle_result(self, result: ValidationSuccess | ValidationFailure) -> None:
        self._activate_btn.configure(state="normal", text="Activate")
        if isinstance(result, ValidationSuccess):
            self._show_status(result.message, COLORS["success"])
            logger.info("License validated — transitioning to dashboard")
            self.after(600, lambda: self._app.show_dashboard(result.license_key))
        else:
            self._show_status(result.message, COLORS["error"])
            logger.warning("Validation failed [%s]: %s", result.error_code, result.message)

    def _show_status(self, text: str, color: str) -> None:
        self._status.configure(text=text, text_color=color)


# ══════════════════════════════════════════════════════════════════════════════
#  Dashboard View
# ══════════════════════════════════════════════════════════════════════════════


class DashboardView(ctk.CTkFrame):
    """
    Main workspace: configure settings, click Generate, and the full
    pipeline (transcribe → select → render) runs automatically.
    """

    def __init__(self, master: LocalClipperApp, license_key: str, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_dark"], **kwargs)
        self._app = master
        self._license_key = license_key

        self.grid_rowconfigure(3, weight=1)  # log console expands
        self.grid_columnconfigure(0, weight=1)

        pad = {"padx": 24, "sticky": "ew"}

        # ── Header ───────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, **pad, pady=(18, 8))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="CustosAI Clipper",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Licensed",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["success"],
            anchor="e",
        ).grid(row=0, column=1, sticky="e")

        # ── Controls card ────────────────────────────────────────────────
        controls = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_card"],
            corner_radius=14,
            border_width=1,
            border_color=COLORS["border"],
        )
        controls.grid(row=1, column=0, **pad, pady=(0, 10))
        controls.grid_columnconfigure(0, weight=1)

        inner_pad = {"padx": 16, "sticky": "ew"}

        # ── Input source tabs ────────────────────────────────────────────
        self._input_tabs = ctk.CTkTabview(
            controls,
            height=100,
            fg_color=COLORS["bg_card"],
            segmented_button_fg_color=COLORS["bg_input"],
            segmented_button_selected_color=COLORS["accent"],
            segmented_button_selected_hover_color=COLORS["accent_hover"],
            segmented_button_unselected_color=COLORS["bg_input"],
            segmented_button_unselected_hover_color=COLORS["border"],
        )
        self._input_tabs.grid(row=0, column=0, **inner_pad, pady=(8, 4))

        tab_local = self._input_tabs.add("Local File")
        tab_yt = self._input_tabs.add("YouTube URL")

        self._video_picker = PathSelector(
            tab_local,
            label="Input Video",
            dialog_type="file",
            filetypes=[("Video files", "*.mp4 *.mov *.avi *.mkv *.webm")],
        )
        self._video_picker.pack(fill="x", padx=4, pady=4)

        self._yt_input = YouTubeInput(tab_yt)
        self._yt_input.pack(fill="x", padx=4, pady=4)

        # ── Output folder ────────────────────────────────────────────────
        self._output_picker = PathSelector(
            controls,
            label="Output Folder",
            dialog_type="directory",
        )
        self._output_picker.grid(row=1, column=0, **inner_pad, pady=(0, 8))

        # ── Options row 1: model + clip length ───────────────────────────
        row1 = ctk.CTkFrame(controls, fg_color="transparent")
        row1.grid(row=2, column=0, **inner_pad, pady=(0, 4))
        row1.grid_columnconfigure(0, weight=1)
        row1.grid_columnconfigure(1, weight=1)

        self._model_menu = LabeledOptionMenu(
            row1,
            label="Whisper Model",
            values=["tiny", "base", "small", "medium", "large-v2"],
            default="base",
        )
        self._model_menu.grid(row=0, column=0, sticky="ew", padx=(0, 12))

        self._clip_length_slider = LabeledSlider(
            row1,
            label="Clip Length",
            from_=30,
            to=60,
            default=45,
            suffix="s",
        )
        self._clip_length_slider.grid(row=0, column=1, sticky="ew")

        # ── Options row 2: num clips + toggles + generate ─────────────────
        row2 = ctk.CTkFrame(controls, fg_color="transparent")
        row2.grid(row=3, column=0, **inner_pad, pady=(0, 4))
        row2.grid_columnconfigure(0, weight=1)
        row2.grid_columnconfigure(1, weight=0)
        row2.grid_columnconfigure(2, weight=0)
        row2.grid_columnconfigure(3, weight=0)

        self._num_clips_slider = LabeledSlider(
            row2,
            label="Number of Clips",
            from_=1,
            to=10,
            default=5,
            suffix="",
        )
        self._num_clips_slider.grid(row=0, column=0, sticky="ew", padx=(0, 12))

        sub_frame = ctk.CTkFrame(row2, fg_color="transparent")
        sub_frame.grid(row=0, column=1, sticky="s", padx=(0, 12))

        ctk.CTkLabel(
            sub_frame,
            text="Subtitles",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
        ).pack(pady=(0, 6))

        self._subtitles_var = ctk.BooleanVar(value=True)
        self._subtitles_switch = ctk.CTkSwitch(
            sub_frame,
            text="",
            variable=self._subtitles_var,
            width=46,
            fg_color=COLORS["bg_input"],
            progress_color=COLORS["accent"],
            button_color=COLORS["text_primary"],
            button_hover_color=COLORS["accent_hover"],
        )
        self._subtitles_switch.pack()

        bg_frame = ctk.CTkFrame(row2, fg_color="transparent")
        bg_frame.grid(row=0, column=2, sticky="s", padx=(0, 12))

        ctk.CTkLabel(
            bg_frame,
            text="Split Screen",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
        ).pack(pady=(0, 6))

        self._bg_video_var = ctk.BooleanVar(value=False)
        self._bg_video_switch = ctk.CTkSwitch(
            bg_frame,
            text="",
            variable=self._bg_video_var,
            width=46,
            fg_color=COLORS["bg_input"],
            progress_color=COLORS["accent"],
            button_color=COLORS["text_primary"],
            button_hover_color=COLORS["accent_hover"],
            command=self._on_bg_toggle,
        )
        self._bg_video_switch.pack()

        btn_frame = ctk.CTkFrame(row2, fg_color="transparent")
        btn_frame.grid(row=0, column=3, sticky="se")

        self._generate_btn = ctk.CTkButton(
            btn_frame,
            text="Generate Clips",
            width=160,
            height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            corner_radius=10,
            command=self._on_generate,
        )
        self._generate_btn.pack(anchor="se", pady=(18, 0))

        # ── Background video picker (hidden by default) ──────────────────
        self._bg_picker = PathSelector(
            controls,
            label="Background Video (gameplay, satisfying, etc.)",
            dialog_type="file",
            filetypes=[("Video files", "*.mp4 *.mov *.avi *.mkv *.webm")],
        )
        # starts hidden; shown/hidden by _on_bg_toggle

        # ── Progress ─────────────────────────────────────────────────────
        self._progress = StatusProgressBar(self)
        self._progress.grid(row=2, column=0, **pad, pady=(0, 6))

        # ── Log console ──────────────────────────────────────────────────
        self._console = LogConsole(self, height=180)
        self._console.grid(row=3, column=0, padx=24, pady=(0, 18), sticky="nsew")

        self._console.write("CustosAI Clipper ready.", "success")
        self._console.write(f"License: {license_key[:8]}…", "debug")

    # ── Accessors ────────────────────────────────────────────────────────

    @property
    def console(self) -> LogConsole:
        return self._console

    @property
    def progress(self) -> StatusProgressBar:
        return self._progress

    def _is_youtube_mode(self) -> bool:
        return self._input_tabs.get() == "YouTube URL"

    def get_video_source(self) -> Optional[str]:
        if self._is_youtube_mode():
            return self._yt_input.get()
        return self._video_picker.get()

    def get_output_dir(self) -> Optional[str]:
        return self._output_picker.get()

    def get_model_size(self) -> str:
        return self._model_menu.get()

    def get_clip_length(self) -> int:
        return self._clip_length_slider.get()

    def get_num_clips(self) -> int:
        return self._num_clips_slider.get()

    def get_subtitles_enabled(self) -> bool:
        return self._subtitles_var.get()

    def get_background_video(self) -> Optional[str]:
        """Return the background video path, or None if split-screen is off."""
        if not self._bg_video_var.get():
            return None
        return self._bg_picker.get()

    def _on_bg_toggle(self) -> None:
        """Show/hide the background video file picker."""
        if self._bg_video_var.get():
            self._bg_picker.grid(
                row=4, column=0, padx=16, sticky="ew", pady=(0, 8)
            )
        else:
            self._bg_picker.grid_remove()

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._generate_btn.configure(state=state)

    # ── Pipeline ─────────────────────────────────────────────────────────

    def _on_generate(self) -> None:
        source = self.get_video_source()
        output = self.get_output_dir()
        is_yt = self._is_youtube_mode()

        if not source:
            msg = "No YouTube URL entered." if is_yt else "No input video selected."
            self._console.write(msg, "warning")
            return
        if not output:
            self._console.write("No output folder selected.", "warning")
            return

        clip_length = self.get_clip_length()
        num_clips = self.get_num_clips()
        subtitles = self.get_subtitles_enabled()
        bg_video = self.get_background_video()

        if self._bg_video_var.get() and not bg_video:
            self._console.write(
                "Split Screen is ON but no background video selected.",
                "warning",
            )
            return

        self._console.write(f"Source: {source}", "info")
        self._console.write(f"Output: {output}", "info")
        self._console.write(f"Model:  {self.get_model_size()}", "info")
        self._console.write(f"Clip length: {clip_length}s  |  Clips: {num_clips}", "info")
        self._console.write(f"Subtitles: {'ON' if subtitles else 'OFF'}", "info")
        self._console.write(
            f"Split Screen: {'ON' if bg_video else 'OFF'}"
            + (f" ({Path(bg_video).name})" if bg_video else ""),
            "info",
        )

        self._set_controls_enabled(False)
        self._progress.reset("Starting…")
        self._console.write("Launching pipeline…", "info")

        thread = threading.Thread(
            target=self._pipeline_worker,
            args=(source, output, self.get_model_size(),
                  clip_length, num_clips, subtitles, is_yt, bg_video),
            daemon=True,
        )
        thread.start()

    def _pipeline_worker(
        self,
        source: str,
        output: str,
        model_size: str,
        clip_length: int,
        max_clips: int,
        subtitles: bool,
        is_youtube: bool,
        background_video: Optional[str] = None,
    ) -> None:
        """Runs the full analyze → render pipeline on a daemon thread."""
        from src.engine.video_processor import analyze_video, render_selected_clips

        try:
            video_path = source

            # ── YouTube download (0 % – 15 %) ───────────────────────────
            if is_youtube:
                from src.engine.yt_downloader import download_video

                def _yt_progress(value: float, status: str) -> None:
                    self._progress.set_progress(value * 0.15, status)

                downloaded = download_video(
                    url=source,
                    output_dir=output,
                    on_log=self._console.write,
                    on_progress=_yt_progress,
                )
                video_path = str(downloaded)

            # ── Analyze (15 % – 50 %) or (0 % – 50 %) ──────────────────
            def _analysis_progress(value: float, status: str) -> None:
                offset = 0.15 if is_youtube else 0.0
                scale = 0.35 if is_youtube else 0.50
                self._progress.set_progress(offset + value * scale, status)

            regions = analyze_video(
                video_path=video_path,
                model_size=model_size,
                clip_length=clip_length,
                max_clips=max_clips,
                on_log=self._console.write,
                on_progress=_analysis_progress,
            )

            # ── Render (50 % – 100 %) ──────────────────────────────────
            def _render_progress(value: float, status: str) -> None:
                self._progress.set_progress(0.50 + value * 0.50, status)

            result_paths = render_selected_clips(
                video_path=video_path,
                regions=regions,
                output_dir=output,
                subtitles=subtitles,
                background_video=background_video,
                on_log=self._console.write,
                on_progress=_render_progress,
            )

            self._console.write(
                f"Generated {len(result_paths)} clip(s):", "success"
            )
            for p in result_paths:
                self._console.write(f"  → {p}", "success")

            # Clean up the full downloaded video (YouTube only)
            if is_youtube:
                try:
                    Path(video_path).unlink(missing_ok=True)
                    self._console.write("Deleted source download", "debug")
                except Exception:
                    pass

        except Exception as exc:
            self._console.write(f"Pipeline failed: {exc}", "error")
            logger.exception("Pipeline error")
        finally:
            self.after_idle(lambda: self._set_controls_enabled(True))


# ══════════════════════════════════════════════════════════════════════════════
#  Application Root
# ══════════════════════════════════════════════════════════════════════════════


class LocalClipperApp(ctk.CTk):
    """Top-level window. Owns the login/dashboard lifecycle."""

    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(_APP_TITLE)
        self.geometry(_WINDOW_SIZE)
        self.minsize(*_MIN_SIZE)
        self.configure(fg_color=COLORS["bg_dark"])
        _apply_icon(self)

        self._current_view: Optional[ctk.CTkFrame] = None
        self._dashboard: Optional[DashboardView] = None

        if _DEV_SKIP_LOGIN:
            self.show_dashboard("dev-key-local")
        else:
            self._show_login()

    def _swap_view(self, new_view: ctk.CTkFrame) -> None:
        if self._current_view is not None:
            self._current_view.destroy()
        new_view.pack(fill="both", expand=True)
        self._current_view = new_view

    def _show_login(self) -> None:
        self._swap_view(LoginView(self))

    def show_dashboard(self, license_key: str) -> None:
        self._dashboard = DashboardView(self, license_key)
        self._swap_view(self._dashboard)
        logger.info("Dashboard loaded")

    @property
    def dashboard(self) -> Optional[DashboardView]:
        return self._dashboard
