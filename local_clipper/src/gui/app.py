"""
CustosAI Clipper — Main application window.

Houses three views that are swapped in-place:
    1. **LoginView**     – License key entry + activation.
    2. **SetupView**     – First-run dependency download (FFmpeg, optional Whisper).
    3. **DashboardView** – Video processing controls, progress, and log console.

Threading contract:
    - License validation runs on a daemon thread so the GUI never blocks.
    - Setup downloads run on daemon threads, posting progress updates
      back to the main loop via ``after_idle``.
    - Video processing runs on daemon threads, posting progress updates
      back to the main loop via ``after_idle``.
"""

from __future__ import annotations

import logging
import os
import platform
import threading
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from src.auth.license_storage import clear_license, load_license, save_license
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
from src.utils.paths import get_assets_path, get_bundled_ffmpeg_dir, get_icon_source

logger = logging.getLogger(__name__)

_APP_TITLE = "CustosAI Clipper"
_WINDOW_SIZE = "900x680"
_MIN_SIZE = (780, 600)

_ASSETS = get_assets_path()

# Set to True to skip Whop license validation during development.
_DEV_SKIP_LOGIN = False


def _apply_icon(window: ctk.CTk) -> None:
    try:
        if platform.system() == "Windows":
            ico = _ASSETS / "icon.ico"
            if ico.exists():
                window.iconbitmap(str(ico))
        else:
            icon_path = get_icon_source()
            if icon_path:
                from PIL import Image
                from PIL import ImageTk
                img = Image.open(icon_path).convert("RGBA")
                photo = ImageTk.PhotoImage(img)
                window.iconphoto(True, photo)
    except Exception:
        logger.debug("Window icon not applied — non-critical, skipping")


# ══════════════════════════════════════════════════════════════════════════════
#  Login View
# ══════════════════════════════════════════════════════════════════════════════


class LoginView(ctk.CTkFrame):
    """Minimalist centered card with a license-key field and Activate button."""

    def __init__(
        self,
        master: LocalClipperApp,
        initial_key: Optional[str] = None,
        auto_validate: bool = False,
        status_message: Optional[str] = None,
        **kwargs,
    ):
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
        card.configure(height=380)
        card.grid_rowconfigure(6, weight=1)
        card.grid_columnconfigure(0, weight=1)

        # Logo from assets
        row = 0
        logo_path = get_icon_source()
        if logo_path:
            try:
                from PIL import Image
                pil_img = Image.open(logo_path).convert("RGBA").resize((64, 64))
                logo_img = ctk.CTkImage(
                    light_image=pil_img,
                    dark_image=pil_img,
                    size=(64, 64),
                )
                ctk.CTkLabel(card, image=logo_img, text="").grid(row=row, column=0, pady=(24, 8))
                row += 1
            except Exception as exc:
                logger.debug("Logo not displayed: %s", exc)

        ctk.CTkLabel(
            card,
            text="CustosAI Clipper",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=COLORS["text_primary"],
        ).grid(row=row, column=0, pady=(36 if row == 0 else 0, 2))
        row += 1

        ctk.CTkLabel(
            card,
            text="Enter your license key to continue",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
        ).grid(row=row, column=0, pady=(0, 24))
        row += 1

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
        self._key_entry.grid(row=row, column=0, pady=(0, 16))
        if initial_key:
            self._key_entry.insert(0, initial_key)
        self._key_entry.bind("<Return>", lambda _: self._on_activate())
        row += 1

        self._status_message = status_message

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
        self._activate_btn.grid(row=row, column=0, pady=(0, 12))
        row += 1

        self._status = ctk.CTkLabel(
            card,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"],
            wraplength=300,
        )
        self._status.grid(row=row, column=0, pady=(0, 20))

        if status_message and not (auto_validate and initial_key):
            self._show_status(status_message, COLORS["error"])

        if auto_validate and initial_key:
            self._activate_btn.configure(state="disabled", text="Validating…")
            self._show_status(
                status_message or "Checking saved license…",
                COLORS["text_muted"],
            )
            threading.Thread(
                target=self._validate_worker,
                args=(initial_key,),
                daemon=True,
            ).start()

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
            save_license(result.license_key)
            self._show_status(result.message, COLORS["success"])
            logger.info("License validated — transitioning to setup")
            self.after(600, lambda: self._app.show_setup(result.license_key))
        else:
            if result.error_code == "LICENSE_EXPIRED":
                clear_license()
                self._show_status(
                    "License expired. Please renew and enter your new license.",
                    COLORS["error"],
                )
                self._key_entry.delete(0, "end")
            else:
                self._show_status(result.message, COLORS["error"])
            logger.warning("Validation failed [%s]: %s", result.error_code, result.message)

    def _show_status(self, text: str, color: str) -> None:
        self._status.configure(text=text, text_color=color)


# ══════════════════════════════════════════════════════════════════════════════
#  Setup View — First-run dependency download
# ══════════════════════════════════════════════════════════════════════════════


class SetupView(ctk.CTkFrame):
    """
    First-run setup: downloads FFmpeg (and optionally pre-caches Whisper model)
    so the user has a seamless experience. Runs after successful login.
    """

    def __init__(self, master: LocalClipperApp, license_key: str, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_dark"], **kwargs)
        self._app = master
        self._license_key = license_key

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        card = ctk.CTkFrame(
            self,
            width=480,
            fg_color=COLORS["bg_card"],
            corner_radius=18,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.grid(row=0, column=0)
        card.grid_propagate(False)
        card.configure(height=280)
        card.grid_rowconfigure(4, weight=1)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text="Preparing your environment",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, pady=(32, 8))

        ctk.CTkLabel(
            card,
            text="Downloading required components. This may take a few minutes on first launch.",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
            wraplength=400,
        ).grid(row=1, column=0, pady=(0, 24))

        self._status_label = ctk.CTkLabel(
            card,
            text="Starting…",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_muted"],
        )
        self._status_label.grid(row=2, column=0, pady=(0, 12))

        self._progress = ctk.CTkProgressBar(
            card,
            width=360,
            height=8,
            corner_radius=4,
            fg_color=COLORS["bg_input"],
            progress_color=COLORS["accent"],
            mode="indeterminate",
        )
        self._progress.grid(row=3, column=0, pady=(0, 24))
        self._progress.start()

        threading.Thread(target=self._setup_worker, daemon=True).start()

    def _update_status(self, text: str) -> None:
        self.after_idle(lambda: self._status_label.configure(text=text))

    def _setup_worker(self) -> None:
        """Use bundled FFmpeg or download if not bundled. Pre-cache Whisper model."""
        try:
            # ── 1. FFmpeg (required for video processing) ─────────────────
            bundled = get_bundled_ffmpeg_dir()
            if bundled:
                self._update_status("Preparing video engine…")
                ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
                ffmpeg_path = bundled / ffmpeg_name
                if ffmpeg_path.exists():
                    os.environ["IMAGEIO_FFMPEG_EXE"] = str(ffmpeg_path)
                    os.environ["FFMPEG_BINARY"] = str(ffmpeg_path)
                    logger.info("FFmpeg ready (bundled): %s", ffmpeg_path)
                else:
                    self.after_idle(
                        lambda: self._app._show_setup_error("Bundled FFmpeg not found.")
                    )
                    return
            else:
                self._update_status("Downloading video engine (FFmpeg)…")
                try:
                    from static_ffmpeg import run

                    ffmpeg_path, _ = run.get_or_fetch_platform_executables_else_raise()
                    os.environ["IMAGEIO_FFMPEG_EXE"] = str(ffmpeg_path)
                    os.environ["FFMPEG_BINARY"] = str(ffmpeg_path)
                    logger.info("FFmpeg ready: %s", ffmpeg_path)
                except Exception as exc:
                    logger.exception("FFmpeg setup failed")
                    self.after_idle(
                        lambda: self._app._show_setup_error(
                            f"Could not download FFmpeg: {exc}"
                        )
                    )
                    return

            # ── 2. Pre-cache Whisper base model (optional, speeds up first clip) ─
            self._update_status("Preparing AI transcription model…")
            try:
                from src.engine.ai_transcriber import load_model

                load_model("base", on_progress=None)
                logger.info("Whisper base model cached")
            except Exception as exc:
                logger.warning("Whisper pre-cache failed (non-fatal): %s", exc)
                # Non-fatal — model will download on first Generate

            # ── 3. Done ───────────────────────────────────────────────────
            self._update_status("Ready!")
            self.after_idle(self._on_setup_complete)
        except Exception as exc:
            logger.exception("Setup failed")
            self.after_idle(
                lambda: self._app._show_setup_error(str(exc))
            )

    def _on_setup_complete(self) -> None:
        self._progress.stop()
        self._progress.set(1.0)
        self._progress.configure(mode="determinate")
        logger.info("Setup complete — transitioning to dashboard")
        self.after(400, lambda: self._app.show_dashboard(self._license_key))


class _SetupErrorView(ctk.CTkFrame):
    """Shown when setup fails. Offers return to login."""

    def __init__(self, master: LocalClipperApp, message: str, **kwargs):
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
            border_color=COLORS["error"],
        )
        card.grid(row=0, column=0)
        card.grid_propagate(False)
        card.configure(height=200)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text="Setup failed",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["error"],
        ).grid(row=0, column=0, pady=(24, 8))

        ctk.CTkLabel(
            card,
            text=message,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
            wraplength=360,
        ).grid(row=1, column=0, pady=(0, 20))

        ctk.CTkButton(
            card,
            text="Back to Login",
            width=200,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            command=lambda: self._app._show_login(),
        ).grid(row=2, column=0, pady=(0, 24))


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

        self._pipeline_running = False
        self._cancelled = False

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
        return 60

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
                row=5, column=0, padx=16, sticky="ew", pady=(0, 8)
            )
        else:
            self._bg_picker.grid_remove()

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable input controls. Cancel button stays enabled during run."""
        state = "normal" if enabled else "disabled"
        self._generate_btn.configure(state=state)

    def _set_generate_button_idle(self) -> None:
        """Reset button to normal 'Generate Clips' state."""
        self._generate_btn.configure(
            text="Generate Clips",
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            command=self._on_generate,
        )

    def _set_generate_button_running(self) -> None:
        """Show red Cancel button during pipeline (must stay enabled to cancel)."""
        self._generate_btn.configure(
            text="Cancel",
            fg_color=COLORS["error"],
            hover_color="#FF6B6B",
            command=self._on_cancel,
            state="normal",
        )

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

        output = str(Path(output).resolve())
        if bg_video:
            bg_video = str(Path(bg_video).resolve())

        self._console.write(f"Source: {source}", "info")
        self._console.write(f"Output: {output}", "info")
        self._console.write(f"Model:  {self.get_model_size()}", "info")
        self._console.write(
            f"Clip length: {clip_length}s  |  Clips: {num_clips}  |  Selection: AI",
            "info",
        )
        self._console.write(f"Subtitles: {'ON' if subtitles else 'OFF'}", "info")
        self._console.write(
            f"Split Screen: {'ON' if bg_video else 'OFF'}"
            + (f" ({Path(bg_video).name})" if bg_video else ""),
            "info",
        )

        self._set_controls_enabled(False)
        self._progress.reset("Validating license…")
        self._console.write("Validating license…", "info")

        params = (
            source, output, self.get_model_size(),
            clip_length, num_clips, subtitles, is_yt, bg_video,
        )

        def _validate_then_start() -> None:
            result = validate_license(self._license_key)
            def _on_result() -> None:
                if isinstance(result, ValidationSuccess):
                    self._pipeline_running = True
                    self._cancelled = False
                    self._set_generate_button_running()
                    self._progress.reset("Starting…")
                    self._console.write("Launching pipeline…", "info")
                    threading.Thread(
                        target=self._pipeline_worker,
                        args=params,
                        daemon=True,
                    ).start()
                elif result.error_code == "LICENSE_EXPIRED":
                    clear_license()
                    self._app._show_login(
                        status_message="License expired. Please renew and enter your new license.",
                    )
                else:
                    self._set_controls_enabled(True)
                    self._set_generate_button_idle()
                    self._console.write(result.message, "error")
            self.after(0, _on_result)

        threading.Thread(target=_validate_then_start, daemon=True).start()

    def _on_cancel(self) -> None:
        """Cancel the running pipeline."""
        if self._pipeline_running:
            self._cancelled = True
            self._console.write("Cancelling…", "warning")

    def _check_cancelled(self) -> None:
        """Raise if user cancelled. Call from progress callbacks."""
        if self._cancelled:
            raise RuntimeError("Cancelled by user")

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
                    self._check_cancelled()
                    self._progress.set_progress(value * 0.15, status)

                downloaded = download_video(
                    url=source,
                    on_log=self._console.write,
                    on_progress=_yt_progress,
                    check_cancelled=self._check_cancelled,
                )
                video_path = str(downloaded)

            # ── Analyze (15 % – 50 %) or (0 % – 50 %) ──────────────────
            def _analysis_progress(value: float, status: str) -> None:
                self._check_cancelled()
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
                check_cancelled=self._check_cancelled,
            )

            # ── Render (50 % – 100 %) — both modes, fully automatic ─────
            def _render_progress(value: float, status: str) -> None:
                self._check_cancelled()
                self._progress.set_progress(0.50 + value * 0.50, status)

            result_paths = render_selected_clips(
                video_path=video_path,
                regions=regions,
                output_dir=output,
                subtitles=subtitles,
                background_video=background_video,
                on_log=self._console.write,
                on_progress=_render_progress,
                check_cancelled=self._check_cancelled,
            )

            self._console.write(
                f"Generated {len(result_paths)} clip(s):", "success"
            )
            for p in result_paths:
                self._console.write(f"  → {p}", "success")

            if is_youtube:
                try:
                    Path(video_path).unlink(missing_ok=True)
                    self._console.write("Deleted source download", "debug")
                except Exception:
                    pass

            if not self._cancelled:
                self.after_idle(
                    lambda: self._on_pipeline_complete(len(result_paths))
                )

        except RuntimeError as exc:
            if "Cancelled" in str(exc):
                self._console.write("Cancelled.", "warning")
                self.after_idle(lambda: self._on_pipeline_complete(0, cancelled=True))
            else:
                raise
        except Exception as exc:
            self._console.write(f"Pipeline failed: {exc}", "error")
            logger.exception("Pipeline error")
            self.after_idle(lambda: self._on_pipeline_complete(0, failed=True))
        finally:
            self._pipeline_running = False
            self.after_idle(self._on_pipeline_finished)

    def _on_pipeline_complete(
        self, num_clips: int, cancelled: bool = False, failed: bool = False
    ) -> None:
        """Reset UI and show completion message."""
        if cancelled:
            self._progress.reset("Cancelled")
        elif failed:
            self._progress.reset("Failed")
        else:
            self._progress.reset("Clips generated")
            self._console.write("Clips generated.", "success")

    def _on_pipeline_finished(self) -> None:
        """Re-enable controls and reset button to Generate."""
        self._set_controls_enabled(True)
        self._set_generate_button_idle()


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
            self.show_setup("dev-key-local")
        else:
            saved = load_license()
            if saved:
                self._show_login(
                    initial_key=saved,
                    auto_validate=True,
                    status_message="Checking saved license…",
                )
            else:
                self._show_login()

    def _swap_view(self, new_view: ctk.CTkFrame) -> None:
        if self._current_view is not None:
            self._current_view.destroy()
        new_view.pack(fill="both", expand=True)
        self._current_view = new_view

    def _show_login(
        self,
        initial_key: Optional[str] = None,
        auto_validate: bool = False,
        status_message: Optional[str] = None,
    ) -> None:
        self._swap_view(
            LoginView(
                self,
                initial_key=initial_key,
                auto_validate=auto_validate,
                status_message=status_message,
            )
        )

    def show_setup(self, license_key: str) -> None:
        """Show first-run setup (FFmpeg + optional Whisper pre-cache)."""
        self._swap_view(SetupView(self, license_key))

    def _show_setup_error(self, message: str) -> None:
        """Show setup error and return to login."""
        self._swap_view(_SetupErrorView(self, message))

    def show_dashboard(self, license_key: str) -> None:
        self._dashboard = DashboardView(self, license_key)
        self._swap_view(self._dashboard)
        logger.info("Dashboard loaded")

    @property
    def dashboard(self) -> Optional[DashboardView]:
        return self._dashboard
