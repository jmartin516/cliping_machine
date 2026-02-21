"""
Local Clipper — Main application window.

Houses two views that are swapped in-place:
    1. **LoginView**     – License key entry + activation.
    2. **DashboardView** – Video processing controls, progress, and log console.

Threading contract:
    - License validation runs on a daemon thread so the GUI never blocks.
    - Video processing (Phase 3) will follow the same pattern, posting
      progress updates back to the main loop via ``after_idle``.
"""

from __future__ import annotations

import logging
import platform
import threading
from pathlib import Path
from typing import Optional

print("[DEBUG app.py] Importing customtkinter...")
import customtkinter as ctk
print(f"[DEBUG app.py] customtkinter imported: {ctk.__version__ if hasattr(ctk, '__version__') else 'unknown'}")

print("[DEBUG app.py] Importing whop_api...")
try:
    from src.auth.whop_api import ValidationFailure, ValidationSuccess, validate_license
    print("[DEBUG app.py] whop_api imported OK")
except Exception as e:
    print(f"[DEBUG app.py] whop_api import FAILED: {e}")
    import traceback; traceback.print_exc()

print("[DEBUG app.py] Importing components...")
try:
    from src.gui.components import (
        COLORS,
        LabeledOptionMenu,
        LogConsole,
        PathSelector,
        StatusProgressBar,
    )
    print(f"[DEBUG app.py] Components imported OK. COLORS keys: {list(COLORS.keys())}")
except Exception as e:
    print(f"[DEBUG app.py] Components import FAILED: {e}")
    import traceback; traceback.print_exc()

logger = logging.getLogger(__name__)

_APP_TITLE = "Local Clipper"
_WINDOW_SIZE = "900x680"
_MIN_SIZE = (780, 600)

# Cross-platform icon handling
_ASSETS = Path(__file__).resolve().parents[2] / "assets"


def _apply_icon(window: ctk.CTk) -> None:
    """Set the window icon, gracefully handling missing files or unsupported OS."""
    try:
        if platform.system() == "Windows":
            ico = _ASSETS / "icon.ico"
            if ico.exists():
                window.iconbitmap(str(ico))
        elif platform.system() == "Darwin":
            pass  # macOS uses .icns embedded at bundle level; Tk ignores iconbitmap
    except Exception:
        logger.debug("Window icon not applied — non-critical, skipping")


# ══════════════════════════════════════════════════════════════════════════════
#  Login View
# ══════════════════════════════════════════════════════════════════════════════


class LoginView(ctk.CTkFrame):
    """Minimalist centered card with a license-key field and Activate button."""

    def __init__(self, master: LocalClipperApp, **kwargs):
        print("[DEBUG LoginView.__init__] Starting...")
        super().__init__(master, fg_color=COLORS["bg_dark"], **kwargs)
        self._app = master
        print("[DEBUG LoginView.__init__] Frame created")

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        print("[DEBUG LoginView.__init__] Creating card...")
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
        print(f"[DEBUG LoginView.__init__] Card created: {card}")

        # ── Title ────────────────────────────────────────────────────────
        print("[DEBUG LoginView.__init__] Creating title label...")
        ctk.CTkLabel(
            card,
            text="Local Clipper",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, pady=(36, 2))

        ctk.CTkLabel(
            card,
            text="Enter your license key to continue",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
        ).grid(row=1, column=0, pady=(0, 24))
        print("[DEBUG LoginView.__init__] Labels created")

        # ── Key input ────────────────────────────────────────────────────
        print("[DEBUG LoginView.__init__] Creating key entry...")
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
        print("[DEBUG LoginView.__init__] Key entry created")

        # ── Activate button ──────────────────────────────────────────────
        print("[DEBUG LoginView.__init__] Creating activate button...")
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
        print("[DEBUG LoginView.__init__] Button created")

        # ── Status message ───────────────────────────────────────────────
        self._status = ctk.CTkLabel(
            card,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"],
            wraplength=300,
        )
        self._status.grid(row=4, column=0, pady=(0, 20))
        print("[DEBUG LoginView.__init__] COMPLETED - all widgets created")

    # ── Actions ──────────────────────────────────────────────────────────

    def _on_activate(self) -> None:
        key = self._key_entry.get().strip()
        if not key:
            self._show_status("Please enter a license key.", COLORS["warning"])
            return

        self._activate_btn.configure(state="disabled", text="Validating…")
        self._show_status("Contacting license server…", COLORS["text_muted"])

        thread = threading.Thread(target=self._validate_worker, args=(key,), daemon=True)
        thread.start()

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
    Main workspace: file selectors, model picker, Generate button,
    progress bar, and live log console.
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
            text="Local Clipper",
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

        self._video_picker = PathSelector(
            controls,
            label="Input Video",
            dialog_type="file",
            filetypes=[("Video files", "*.mp4 *.mov *.avi *.mkv *.webm")],
        )
        self._video_picker.grid(row=0, column=0, **inner_pad, pady=(14, 8))

        self._output_picker = PathSelector(
            controls,
            label="Output Folder",
            dialog_type="directory",
        )
        self._output_picker.grid(row=1, column=0, **inner_pad, pady=(0, 8))

        options_row = ctk.CTkFrame(controls, fg_color="transparent")
        options_row.grid(row=2, column=0, **inner_pad, pady=(0, 14))
        options_row.grid_columnconfigure(0, weight=1)
        options_row.grid_columnconfigure(1, weight=0)

        self._model_menu = LabeledOptionMenu(
            options_row,
            label="Whisper Model",
            values=["tiny", "base", "small", "medium", "large-v2"],
            default="base",
        )
        self._model_menu.grid(row=0, column=0, sticky="ew", padx=(0, 12))

        btn_frame = ctk.CTkFrame(options_row, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="se")

        self._generate_btn = ctk.CTkButton(
            btn_frame,
            text="Generate Clip",
            width=160,
            height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            corner_radius=10,
            command=self._on_generate,
        )
        self._generate_btn.pack(anchor="se", pady=(18, 0))

        # ── Progress ─────────────────────────────────────────────────────
        self._progress = StatusProgressBar(self)
        self._progress.grid(row=2, column=0, **pad, pady=(0, 6))

        # ── Log console ──────────────────────────────────────────────────
        self._console = LogConsole(self, height=180)
        self._console.grid(row=3, column=0, **pad, pady=(0, 18), sticky="nsew")

        self._console.write("Local Clipper ready.", "success")
        self._console.write(f"License: {license_key[:8]}…", "debug")

    # ── Public interface for the engine layer (Phase 3) ──────────────────

    @property
    def console(self) -> LogConsole:
        return self._console

    @property
    def progress(self) -> StatusProgressBar:
        return self._progress

    def get_video_path(self) -> Optional[str]:
        return self._video_picker.get()

    def get_output_dir(self) -> Optional[str]:
        return self._output_picker.get()

    def get_model_size(self) -> str:
        return self._model_menu.get()

    def set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._generate_btn.configure(state=state)

    # ── Actions ──────────────────────────────────────────────────────────

    def _on_generate(self) -> None:
        video = self.get_video_path()
        output = self.get_output_dir()

        if not video:
            self._console.write("No input video selected.", "warning")
            return
        if not output:
            self._console.write("No output folder selected.", "warning")
            return

        self._console.write(f"Video:  {video}", "info")
        self._console.write(f"Output: {output}", "info")
        self._console.write(f"Model:  {self.get_model_size()}", "info")

        self.set_controls_enabled(False)
        self._progress.reset("Starting pipeline…")
        self._console.write("Launching processing pipeline…", "info")

        thread = threading.Thread(
            target=self._pipeline_worker,
            args=(video, output, self.get_model_size()),
            daemon=True,
        )
        thread.start()

    def _pipeline_worker(self, video: str, output: str, model_size: str) -> None:
        """Runs on a daemon thread — must not touch Tk widgets directly."""
        from src.engine.video_processor import run_pipeline

        try:
            result_path = run_pipeline(
                video_path=video,
                output_dir=output,
                model_size=model_size,
                on_log=self._console.write,
                on_progress=self._progress.set_progress,
            )
            self._console.write(f"Saved: {result_path}", "success")
        except Exception as exc:
            self._console.write(f"Pipeline failed: {exc}", "error")
            logger.exception("Pipeline error")
        finally:
            self.after_idle(lambda: self.set_controls_enabled(True))


# ══════════════════════════════════════════════════════════════════════════════
#  Application Root
# ══════════════════════════════════════════════════════════════════════════════


class LocalClipperApp(ctk.CTk):
    """
    Top-level window. Owns the login/dashboard lifecycle.

    The processing GUI is intentionally *not* loaded until the license is
    validated — ``show_dashboard`` is only called on ``ValidationSuccess``.
    """

    def __init__(self) -> None:
        print("[DEBUG App.__init__] Starting CTk super().__init__")
        super().__init__()
        print("[DEBUG App.__init__] CTk init done")

        import tkinter as _tk
        print(f"[DEBUG App.__init__] Tcl/Tk version: {_tk.TclVersion} / {_tk.TkVersion}")
        print(f"[DEBUG App.__init__] Tk patchlevel: {self.tk.call('info', 'patchlevel')}")
        print(f"[DEBUG App.__init__] Python version: {platform.python_version()}")
        print(f"[DEBUG App.__init__] customtkinter scaling: {ctk.ScalingTracker.get_widget_scaling(self)}")

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(_APP_TITLE)
        self.geometry(_WINDOW_SIZE)
        self.minsize(*_MIN_SIZE)
        self.configure(fg_color=COLORS["bg_dark"])
        _apply_icon(self)
        print("[DEBUG App.__init__] Window configured")

        self._current_view: Optional[ctk.CTkFrame] = None
        self._dashboard: Optional[DashboardView] = None

        print("[DEBUG App.__init__] About to call _show_login")
        self._show_login()
        print("[DEBUG App.__init__] _show_login completed")

        self.after(500, self._debug_post_mainloop)

    def _debug_post_mainloop(self) -> None:
        """Runs 500ms after mainloop starts to inspect actual widget state."""
        print("\n[DEBUG POST-MAINLOOP] === Checking widget state after mainloop started ===")
        print(f"[DEBUG POST-MAINLOOP] Window geometry: {self.geometry()}")
        print(f"[DEBUG POST-MAINLOOP] Window winfo_width: {self.winfo_width()}, winfo_height: {self.winfo_height()}")
        print(f"[DEBUG POST-MAINLOOP] Window state: {self.state()}")

        view = self._current_view
        if view:
            print(f"[DEBUG POST-MAINLOOP] Current view: {type(view).__name__}")
            print(f"[DEBUG POST-MAINLOOP] View winfo_ismapped: {view.winfo_ismapped()}")
            print(f"[DEBUG POST-MAINLOOP] View winfo_width: {view.winfo_width()}, winfo_height: {view.winfo_height()}")
            print(f"[DEBUG POST-MAINLOOP] View winfo_x: {view.winfo_x()}, winfo_y: {view.winfo_y()}")
            print(f"[DEBUG POST-MAINLOOP] View winfo_viewable: {view.winfo_viewable()}")
            print(f"[DEBUG POST-MAINLOOP] View pack_info: {view.pack_info()}")

            children = view.winfo_children()
            print(f"[DEBUG POST-MAINLOOP] View children count: {len(children)}")
            for i, child in enumerate(children):
                print(f"[DEBUG POST-MAINLOOP]   child[{i}]: {type(child).__name__} mapped={child.winfo_ismapped()} "
                      f"size={child.winfo_width()}x{child.winfo_height()} viewable={child.winfo_viewable()}")
                for j, grandchild in enumerate(child.winfo_children()):
                    print(f"[DEBUG POST-MAINLOOP]     grandchild[{j}]: {type(grandchild).__name__} "
                          f"mapped={grandchild.winfo_ismapped()} "
                          f"size={grandchild.winfo_width()}x{grandchild.winfo_height()}")
        else:
            print("[DEBUG POST-MAINLOOP] NO current view!")

    # ── View management ──────────────────────────────────────────────────

    def _swap_view(self, new_view: ctk.CTkFrame) -> None:
        print(f"[DEBUG _swap_view] Swapping to {type(new_view).__name__}")
        if self._current_view is not None:
            print(f"[DEBUG _swap_view] Destroying old view: {type(self._current_view).__name__}")
            self._current_view.destroy()
        new_view.pack(fill="both", expand=True)
        self._current_view = new_view
        print(f"[DEBUG _swap_view] New view packed: {type(new_view).__name__}")
        print(f"[DEBUG _swap_view] View winfo_ismapped: {new_view.winfo_ismapped()}")
        print(f"[DEBUG _swap_view] View winfo_width: {new_view.winfo_width()}, winfo_height: {new_view.winfo_height()}")

    def _show_login(self) -> None:
        print("[DEBUG _show_login] Creating LoginView...")
        try:
            view = LoginView(self)
            print(f"[DEBUG _show_login] LoginView created: {view}")
            print(f"[DEBUG _show_login] LoginView children: {view.winfo_children()}")
            self._swap_view(view)
        except Exception as e:
            print(f"[DEBUG _show_login] FAILED: {e}")
            import traceback; traceback.print_exc()

    def show_dashboard(self, license_key: str) -> None:
        """Transition to the main workspace. Only called after validation."""
        self._dashboard = DashboardView(self, license_key)
        self._swap_view(self._dashboard)
        logger.info("Dashboard loaded")

    @property
    def dashboard(self) -> Optional[DashboardView]:
        return self._dashboard
