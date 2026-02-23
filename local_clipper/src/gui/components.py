"""
Reusable CustomTkinter widgets for CustosAI Clipper.

All widgets in this module are self-contained, dark-mode-aware, and
designed to be dropped into any CTkFrame without external styling.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog
from datetime import datetime
from typing import Optional

import customtkinter as ctk


# ── Color palette (Apple-esque dark theme) ────────────────────────────────────

COLORS = {
    "bg_dark": "#1C1C1E",
    "bg_card": "#2C2C2E",
    "bg_input": "#3A3A3C",
    "accent": "#0A84FF",
    "accent_hover": "#409CFF",
    "text_primary": "#FFFFFF",
    "text_secondary": "#8E8E93",
    "text_muted": "#636366",
    "success": "#30D158",
    "error": "#FF453A",
    "warning": "#FFD60A",
    "border": "#48484A",
}


# ── LogConsole ────────────────────────────────────────────────────────────────


class LogConsole(ctk.CTkFrame):
    """
    Scrollable, read-only terminal-style log output.

    Supports timestamped messages with severity-based coloring.
    Thread-safe: call ``write()`` from any thread — it schedules the
    actual insert on the main Tk event loop via ``after_idle``.
    """

    _TAG_COLORS = {
        "info": COLORS["text_primary"],
        "success": COLORS["success"],
        "warning": COLORS["warning"],
        "error": COLORS["error"],
        "debug": COLORS["text_muted"],
    }

    def __init__(self, master: ctk.CTkBaseClass, height: int = 200, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_card"], corner_radius=10, **kwargs)

        self._label = ctk.CTkLabel(
            self,
            text="Console Output",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        self._label.pack(fill="x", padx=14, pady=(10, 4))

        self._textbox = ctk.CTkTextbox(
            self,
            height=height,
            font=ctk.CTkFont(family="Menlo, Consolas, monospace", size=12),
            fg_color=COLORS["bg_dark"],
            text_color=COLORS["text_primary"],
            corner_radius=8,
            wrap="word",
            activate_scrollbars=True,
        )
        self._textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._textbox.configure(state="disabled")

        for tag, color in self._TAG_COLORS.items():
            self._textbox._textbox.tag_configure(tag, foreground=color)

    def write(self, message: str, level: str = "info") -> None:
        """
        Append a timestamped line. Safe to call from worker threads.

        Args:
            message: Text to display.
            level:   One of ``info``, ``success``, ``warning``, ``error``, ``debug``.
        """
        tag = level if level in self._TAG_COLORS else "info"
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}]  {message}\n"

        def _insert() -> None:
            self._textbox.configure(state="normal")
            self._textbox._textbox.insert("end", line, tag)
            self._textbox._textbox.see("end")
            self._textbox.configure(state="disabled")

        try:
            self._textbox.after_idle(_insert)
        except RuntimeError:
            pass

    def clear(self) -> None:
        self._textbox.configure(state="normal")
        self._textbox._textbox.delete("1.0", "end")
        self._textbox.configure(state="disabled")


# ── StatusProgressBar ─────────────────────────────────────────────────────────


class StatusProgressBar(ctk.CTkFrame):
    """
    Combined progress bar + percentage label + status text.

    Exposes ``set_progress(value, status_text)`` that is thread-safe.
    *value* is a float in [0.0, 1.0].
    """

    def __init__(self, master: ctk.CTkBaseClass, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        self._status_label = ctk.CTkLabel(
            self,
            text="Ready",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        self._status_label.pack(fill="x", padx=4, pady=(0, 4))

        bar_frame = ctk.CTkFrame(self, fg_color="transparent")
        bar_frame.pack(fill="x")

        self._bar = ctk.CTkProgressBar(
            bar_frame,
            height=14,
            corner_radius=7,
            fg_color=COLORS["bg_input"],
            progress_color=COLORS["accent"],
        )
        self._bar.pack(side="left", fill="x", expand=True, padx=(4, 8))
        self._bar.set(0)

        self._pct_label = ctk.CTkLabel(
            bar_frame,
            text="0 %",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_primary"],
            width=48,
            anchor="e",
        )
        self._pct_label.pack(side="right", padx=(0, 4))

    def set_progress(self, value: float, status: Optional[str] = None) -> None:
        """Thread-safe progress update (value in 0.0–1.0)."""
        value = max(0.0, min(1.0, value))

        def _update() -> None:
            self._bar.set(value)
            self._pct_label.configure(text=f"{int(value * 100)} %")
            if status:
                self._status_label.configure(text=status)

        try:
            self._bar.after_idle(_update)
        except RuntimeError:
            pass

    def reset(self, status: str = "Ready") -> None:
        self.set_progress(0.0, status)


# ── LabeledOptionMenu ────────────────────────────────────────────────────────


class LabeledOptionMenu(ctk.CTkFrame):
    """Label + dropdown combo packed into a single frame."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        label: str,
        values: list[str],
        default: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)

        self._label = ctk.CTkLabel(
            self,
            text=label,
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        self._label.pack(fill="x", padx=4, pady=(0, 4))

        self._var = ctk.StringVar(value=default or values[0])
        self._menu = ctk.CTkOptionMenu(
            self,
            variable=self._var,
            values=values,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS["bg_input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["bg_card"],
            dropdown_hover_color=COLORS["accent"],
            corner_radius=8,
        )
        self._menu.pack(fill="x", padx=4)

    def get(self) -> str:
        return self._var.get()


# ── PathSelector ──────────────────────────────────────────────────────────────


class PathSelector(ctk.CTkFrame):
    """
    Label + read-only path display + Browse button.

    *dialog_type*: ``"file"`` opens a file dialog, ``"directory"`` opens
    a directory chooser.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        label: str,
        dialog_type: str = "file",
        filetypes: Optional[list[tuple[str, str]]] = None,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._dialog_type = dialog_type
        self._filetypes = filetypes or [("Video files", "*.mp4 *.mov *.avi *.mkv")]

        self._label = ctk.CTkLabel(
            self,
            text=label,
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        self._label.pack(fill="x", padx=4, pady=(0, 4))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x")

        self._path_var = ctk.StringVar(value="No file selected")
        self._entry = ctk.CTkEntry(
            row,
            textvariable=self._path_var,
            state="readonly",
            font=ctk.CTkFont(size=12),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            corner_radius=8,
        )
        self._entry.pack(side="left", fill="x", expand=True, padx=(4, 8))

        self._btn = ctk.CTkButton(
            row,
            text="Browse",
            width=90,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            corner_radius=8,
            command=self._browse,
        )
        self._btn.pack(side="right", padx=(0, 4))

    def _browse(self) -> None:
        if self._dialog_type == "directory":
            path = filedialog.askdirectory()
        else:
            path = filedialog.askopenfilename(filetypes=self._filetypes)

        if path:
            self._path_var.set(path)

    def get(self) -> Optional[str]:
        val = self._path_var.get()
        return None if val == "No file selected" else val


# ── YouTubeInput ─────────────────────────────────────────────────────────────


class YouTubeInput(ctk.CTkFrame):
    """Editable URL entry for pasting a YouTube link."""

    def __init__(self, master: ctk.CTkBaseClass, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        self._label = ctk.CTkLabel(
            self,
            text="YouTube URL",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        self._label.pack(fill="x", padx=4, pady=(0, 4))

        self._entry = ctk.CTkEntry(
            self,
            height=36,
            placeholder_text="https://youtube.com/watch?v=...",
            font=ctk.CTkFont(size=12),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            corner_radius=8,
        )
        self._entry.pack(fill="x", padx=4)

    def get(self) -> Optional[str]:
        val = self._entry.get().strip()
        return val if val else None


# ── LabeledSlider ────────────────────────────────────────────────────────────


class LabeledSlider(ctk.CTkFrame):
    """Label + slider + live value display."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        label: str,
        from_: int = 30,
        to: int = 60,
        default: int = 45,
        suffix: str = "s",
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)

        self._suffix = suffix

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=4)

        self._label = ctk.CTkLabel(
            header,
            text=label,
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        self._label.pack(side="left")

        self._value_label = ctk.CTkLabel(
            header,
            text=f"{default}{suffix}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text_primary"],
            anchor="e",
        )
        self._value_label.pack(side="right")

        self._var = ctk.IntVar(value=default)
        self._slider = ctk.CTkSlider(
            self,
            from_=from_,
            to=to,
            number_of_steps=to - from_,
            variable=self._var,
            fg_color=COLORS["bg_input"],
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            command=self._on_change,
        )
        self._slider.pack(fill="x", padx=4, pady=(4, 0))

    def _on_change(self, _value: float) -> None:
        self._value_label.configure(text=f"{self._var.get()}{self._suffix}")

    def get(self) -> int:
        return self._var.get()


# ── ClipPreviewPanel ─────────────────────────────────────────────────────────


class ClipPreviewPanel(ctk.CTkFrame):
    """
    Displays clip candidates with checkboxes so the user can pick
    which ones to render. Call ``set_clips()`` to populate.
    """

    def __init__(self, master: ctk.CTkBaseClass, **kwargs):
        super().__init__(
            master,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )
        self._header = ctk.CTkLabel(
            self,
            text="Clip Preview — select which clips to render",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        self._header.pack(fill="x", padx=14, pady=(10, 6))

        self._rows_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._rows_frame.pack(fill="x", padx=10, pady=(0, 10))

        self._check_vars: list[ctk.BooleanVar] = []
        self._render_btn: Optional[ctk.CTkButton] = None
        self._on_render_cb: Optional[object] = None

    def set_clips(
        self,
        clips: list[dict],
        on_render: object,
    ) -> None:
        """
        Populate the panel.

        Args:
            clips:     List of dicts with keys ``index``, ``start``, ``end``,
                       ``duration``, ``score``.
            on_render: Callable invoked when user clicks 'Render Selected'.
        """
        for child in self._rows_frame.winfo_children():
            child.destroy()
        self._check_vars.clear()
        self._on_render_cb = on_render

        for clip in clips:
            var = ctk.BooleanVar(value=True)
            self._check_vars.append(var)

            row = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            ctk.CTkCheckBox(
                row,
                text="",
                variable=var,
                width=24,
                checkbox_width=20,
                checkbox_height=20,
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                border_color=COLORS["border"],
            ).pack(side="left", padx=(4, 8))

            def _fmt_time(s: float) -> str:
                m, sec = divmod(int(s), 60)
                return f"{m}:{sec:02d}"

            label_text = (
                f"Clip {clip['index']}  |  "
                f"{_fmt_time(clip['start'])} – {_fmt_time(clip['end'])}  |  "
                f"{clip['duration']:.0f}s  |  "
                f"score {clip['score']:.2f}"
            )
            ctk.CTkLabel(
                row,
                text=label_text,
                font=ctk.CTkFont(family="Menlo, Consolas, monospace", size=12),
                text_color=COLORS["text_primary"],
                anchor="w",
            ).pack(side="left", fill="x", expand=True)

        btn_row = ctk.CTkFrame(self._rows_frame, fg_color="transparent")
        btn_row.pack(fill="x", pady=(8, 0))

        self._render_btn = ctk.CTkButton(
            btn_row,
            text="Render Selected",
            width=180,
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            corner_radius=10,
            command=self._on_render_click,
        )
        self._render_btn.pack(anchor="e", padx=4)

    def _on_render_click(self) -> None:
        if self._on_render_cb:
            self._on_render_cb()

    def get_selected_indices(self) -> list[int]:
        """Return 0-based indices of checked clips."""
        return [i for i, var in enumerate(self._check_vars) if var.get()]

    def set_enabled(self, enabled: bool) -> None:
        if self._render_btn:
            self._render_btn.configure(state="normal" if enabled else "disabled")
