"""
YouTube Playlist -> MP3 Downloader - GUI + Console Logging.
Run with:  py main.py
"""

import os
import sys
import json
import time
import logging
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
from pathlib import Path

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SRC_DIR)
_LOG_PATH = os.path.join(_PROJECT_DIR, "logs", "app.log")

# ── Configure logging (safe for all encodings) ───────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(stream=open(
            _LOG_PATH,
            "w", encoding="utf-8"
        )),
    ],
)

# Also log to console with safe encoding
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("[%(asctime)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
logging.getLogger().addHandler(console_handler)

logger = logging.getLogger("gui")

try:
    from downloader import (
        PlaylistDownloader, detect_browser, BROWSERS_TO_TRY,
        find_ffmpeg, FFMPEG_DIR, FFMPEG_EXE, _PROJECT_DIR,
    )
except ImportError as e:
    logger.fatal("Cannot import downloader module: %s", e)
    messagebox.showerror("Error", "Cannot find downloader.py")
    sys.exit(1)

# ── Config persistence ──────────────────────────────────────────────────────
_CONFIG_PATH = os.path.join(_PROJECT_DIR, "config.json")

def load_config() -> dict:
    """Load saved settings from config.json."""
    try:
        if os.path.isfile(_CONFIG_PATH):
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            logger.info("Config loaded: %s", _CONFIG_PATH)
            return cfg
    except Exception as e:
        logger.warning("Failed to load config: %s", e)
    return {}

def save_config(cfg: dict):
    """Save settings to config.json."""
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        logger.info("Config saved")
    except Exception as e:
        logger.warning("Failed to save config: %s", e)


# ── Colour palette ──────────────────────────────────────────────────────────
BG       = "#0f0f13"
SURFACE  = "#1a1a24"
CARD     = "#22222f"
ACCENT   = "#7c3aed"
ACCENT2  = "#a855f7"
GREEN    = "#22c55e"
RED      = "#ef4444"
YELLOW   = "#eab308"
TEXT     = "#f1f5f9"
SUBTEXT  = "#94a3b8"
BORDER   = "#2d2d3d"

FONT_FAMILY = "Segoe UI"


# ── Custom progress bar ──────────────────────────────────────────────────────
class GradientBar(tk.Canvas):
    def __init__(self, parent, height=10, **kwargs):
        super().__init__(parent, height=height, bg=SURFACE, highlightthickness=0, **kwargs)
        self._pct = 0.0
        self.bind("<Configure>", self._redraw)

    def set(self, pct: float):
        self._pct = max(0.0, min(100.0, pct))
        self._redraw()

    def _redraw(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2:
            return
        r = h // 2
        self._rounded_rect(0, 0, w, h, r, fill=BORDER, outline="")
        fill_w = int(w * self._pct / 100)
        if fill_w > r * 2:
            self._rounded_rect(0, 0, fill_w, h, r, fill=ACCENT, outline="")

    def _rounded_rect(self, x1, y1, x2, y2, r, **kw):
        r = min(r, (y2 - y1) // 2, max(1, (x2 - x1) // 2))
        pts = [
            x1 + r, y1, x2 - r, y1,
            x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r,
            x1, y1 + r, x1, y1,
        ]
        self.create_polygon(pts, smooth=True, **kw)


# ── Styled button ─────────────────────────────────────────────────────────────
class StyledBtn(tk.Button):
    def __init__(self, parent, text, command=None, color=ACCENT, hover=ACCENT2, **kwargs):
        super().__init__(
            parent, text=text, command=command,
            bg=color, fg=TEXT,
            activebackground=hover, activeforeground=TEXT,
            relief="flat", cursor="hand2",
            font=(FONT_FAMILY, 10, "bold"),
            padx=16, pady=8, bd=0,
            **kwargs,
        )
        self._color = color
        self._hover = hover
        self.bind("<Enter>", lambda e: self.config(bg=hover))
        self.bind("<Leave>", lambda e: self.config(bg=color))


# ── Track row widget ──────────────────────────────────────────────────────────
class TrackRow(tk.Frame):
    def __init__(self, parent, index: int, title: str, **kwargs):
        super().__init__(parent, bg=CARD, **kwargs)

        badge = tk.Label(self, text=f"{index:02d}", bg=SURFACE, fg=SUBTEXT,
                         font=(FONT_FAMILY, 9), width=3, pady=4, padx=6)
        badge.pack(side="left", padx=(8, 6), pady=6)

        self._title_lbl = tk.Label(self, text=title, bg=CARD, fg=TEXT,
                                   font=(FONT_FAMILY, 9), anchor="w")
        self._title_lbl.pack(side="left", fill="x", expand=True)

        self._status = tk.Label(self, text="...", bg=CARD, fg=SUBTEXT,
                                font=(FONT_FAMILY, 10), width=4)
        self._status.pack(side="right", padx=8)

        self._bar = GradientBar(self, height=4)
        self._bar_visible = False

    def set_downloading(self, pct: float):
        if not self._bar_visible:
            self._bar.pack(side="bottom", fill="x", padx=8, pady=(0, 4))
            self._bar_visible = True
        self._bar.set(pct)
        self._status.config(text=f"{pct:.0f}%", fg=ACCENT2)

    def set_done(self):
        if self._bar_visible:
            self._bar.pack_forget()
            self._bar_visible = False
        self._status.config(text="OK", fg=GREEN)

    def set_error(self):
        if self._bar_visible:
            self._bar.pack_forget()
            self._bar_visible = False
        self._status.config(text="ERR", fg=RED)


# ── Main Application Window ───────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Playlist -> MP3")
        self.geometry("780x720")
        self.minsize(640, 550)
        self.configure(bg=BG)
        self.resizable(True, True)

        self._downloader = None
        self._track_rows: list = []
        self._is_running = False
        self._detected_browser = None
        self._config = load_config()

        self._build_ui()
        self._restore_settings()
        logger.info("Application started")

        # Auto-detect browser cookies in background
        self._detect_browser_async()

        # Save settings on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=SURFACE)
        header.pack(fill="x")
        header_inner = tk.Frame(header, bg=SURFACE)
        header_inner.pack(fill="x", padx=20, pady=14)

        tk.Label(header_inner, text="YouTube -> MP3", bg=SURFACE, fg=TEXT,
                 font=(FONT_FAMILY, 16, "bold")).pack(side="left")
        tk.Label(header_inner, text="   powered by yt-dlp", bg=SURFACE, fg=SUBTEXT,
                 font=(FONT_FAMILY, 9)).pack(side="left", pady=4)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Main content
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=20, pady=16)

        # URL input card
        url_card = tk.Frame(main, bg=CARD, pady=14, padx=16)
        url_card.pack(fill="x", pady=(0, 12))

        tk.Label(url_card, text="YouTube Playlist URL", bg=CARD, fg=SUBTEXT,
                 font=(FONT_FAMILY, 9)).pack(anchor="w")

        url_row = tk.Frame(url_card, bg=CARD)
        url_row.pack(fill="x", pady=(6, 0))

        self._url_var = tk.StringVar()
        self._url_entry = tk.Entry(
            url_row, textvariable=self._url_var,
            bg=SURFACE, fg=SUBTEXT, insertbackground=TEXT,
            relief="flat", font=(FONT_FAMILY, 10), bd=0
        )
        self._url_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        self._url_entry.insert(0, self._PLACEHOLDER)
        self._url_entry.bind("<FocusIn>", self._clear_placeholder)
        self._url_entry.bind("<FocusOut>", self._on_url_focusout)

        StyledBtn(url_row, "Paste", command=self._paste_url).pack(side="left")
        StyledBtn(url_row, "Clear", command=self._clear_url,
                  color=SURFACE, hover=CARD).pack(side="left", padx=(4, 0))

        # Browser cookies selector
        cookie_card = tk.Frame(main, bg=CARD, pady=12, padx=16)
        cookie_card.pack(fill="x", pady=(0, 12))

        tk.Label(cookie_card, text="Browser for cookies (needed to bypass YouTube bot check)",
                 bg=CARD, fg=SUBTEXT, font=(FONT_FAMILY, 9)).pack(anchor="w")

        cookie_row = tk.Frame(cookie_card, bg=CARD)
        cookie_row.pack(fill="x", pady=(6, 0))

        browser_options = ["Auto-detect"] + [b.capitalize() for b in BROWSERS_TO_TRY] + ["None (no cookies)"]
        self._browser_var = tk.StringVar(value="Auto-detect")
        self._browser_menu = tk.OptionMenu(cookie_row, self._browser_var, *browser_options)
        self._browser_menu.config(
            bg=SURFACE, fg=TEXT, activebackground=ACCENT,
            activeforeground=TEXT, font=(FONT_FAMILY, 10),
            highlightthickness=0, relief="flat", bd=0
        )
        self._browser_menu["menu"].config(
            bg=SURFACE, fg=TEXT, activebackground=ACCENT,
            activeforeground=TEXT, font=(FONT_FAMILY, 9)
        )
        self._browser_menu.pack(side="left", padx=(0, 8))

        self._cookie_status = tk.Label(cookie_row, text="Detecting...", bg=CARD, fg=YELLOW,
                                        font=(FONT_FAMILY, 9))
        self._cookie_status.pack(side="left")

        # FFmpeg status card
        ffmpeg_card = tk.Frame(main, bg=CARD, pady=10, padx=16)
        ffmpeg_card.pack(fill="x", pady=(0, 12))

        ffmpeg_row = tk.Frame(ffmpeg_card, bg=CARD)
        ffmpeg_row.pack(fill="x")

        tk.Label(ffmpeg_row, text="FFmpeg:", bg=CARD, fg=SUBTEXT,
                 font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 8))

        if FFMPEG_DIR:
            src = "(local)" if _PROJECT_DIR in FFMPEG_DIR else "(system PATH)"
            ffmpeg_text = f"OK {src}  {FFMPEG_EXE}"
            ffmpeg_color = GREEN
        else:
            ffmpeg_text = f"NOT FOUND  ->  place ffmpeg.exe in: {_PROJECT_DIR}"
            ffmpeg_color = RED

        tk.Label(ffmpeg_row, text=ffmpeg_text, bg=CARD, fg=ffmpeg_color,
                 font=(FONT_FAMILY, 9)).pack(side="left")

        # Output folder
        dir_card = tk.Frame(main, bg=CARD, pady=12, padx=16)
        dir_card.pack(fill="x", pady=(0, 12))

        tk.Label(dir_card, text="Save to folder", bg=CARD, fg=SUBTEXT,
                 font=(FONT_FAMILY, 9)).pack(anchor="w")

        dir_row = tk.Frame(dir_card, bg=CARD)
        dir_row.pack(fill="x", pady=(6, 0))

        default_dir = str(Path.home() / "Music" / "YouTube MP3")
        self._dir_var = tk.StringVar(value=default_dir)
        self._dir_entry = tk.Entry(
            dir_row, textvariable=self._dir_var,
            bg=SURFACE, fg=TEXT, insertbackground=TEXT,
            relief="flat", font=(FONT_FAMILY, 10), bd=0,
        )
        self._dir_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))

        StyledBtn(dir_row, "Browse", command=self._pick_folder).pack(side="left")

        # Action buttons
        btn_row = tk.Frame(main, bg=BG)
        btn_row.pack(fill="x", pady=(0, 12))

        self._fetch_btn = StyledBtn(btn_row, "Check Playlist",
                                    command=self._fetch_info)
        self._fetch_btn.pack(side="left", padx=(0, 8))

        self._sync_btn = StyledBtn(btn_row, "Sync New Only",
                                   command=self._sync_download,
                                   color="#0d9488", hover="#0f766e")
        self._sync_btn.pack(side="left", padx=(0, 8))

        self._dl_btn = StyledBtn(btn_row, "Download All",
                                  command=lambda: self._start_download(skip_existing=False),
                                  color="#16a34a", hover="#15803d")
        self._dl_btn.pack(side="left", padx=(0, 8))

        self._cancel_btn = StyledBtn(btn_row, "Cancel",
                                      command=self._cancel,
                                      color="#7f1d1d", hover="#991b1b")
        self._cancel_btn.pack(side="left")
        self._cancel_btn.config(state="disabled")

        self._open_btn = StyledBtn(btn_row, "Open Folder",
                                    command=self._open_folder,
                                    color=SURFACE, hover=CARD)
        self._open_btn.pack(side="right")

        # Global progress
        prog_frame = tk.Frame(main, bg=BG)
        prog_frame.pack(fill="x", pady=(0, 6))

        self._progress_label = tk.Label(prog_frame, text="Ready",
                                         bg=BG, fg=SUBTEXT, font=(FONT_FAMILY, 9))
        self._progress_label.pack(side="left")

        self._pct_label = tk.Label(prog_frame, text="", bg=BG, fg=ACCENT2,
                                    font=(FONT_FAMILY, 9, "bold"))
        self._pct_label.pack(side="right")

        self._global_bar = GradientBar(main, height=10)
        self._global_bar.pack(fill="x", pady=(0, 12))

        # Track list
        list_label = tk.Label(main, text="Tracks", bg=BG, fg=SUBTEXT,
                              font=(FONT_FAMILY, 9))
        list_label.pack(anchor="w", pady=(0, 4))

        list_frame = tk.Frame(main, bg=BG)
        list_frame.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(list_frame, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self._canvas.yview)
        self._track_container = tk.Frame(self._canvas, bg=BG)

        self._track_container.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        )
        self._canvas_win = self._canvas.create_window((0, 0), window=self._track_container, anchor="nw")
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._canvas.bind("<Configure>",
                    lambda e: self._canvas.itemconfig(self._canvas_win, width=e.width))
        self._canvas.bind_all("<MouseWheel>",
                         lambda e: self._canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # Status bar
        status_bar = tk.Frame(self, bg=SURFACE, pady=5)
        status_bar.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(value="Paste a YouTube playlist URL and click Download All.")
        tk.Label(status_bar, textvariable=self._status_var, bg=SURFACE,
                 fg=SUBTEXT, font=(FONT_FAMILY, 8), anchor="w").pack(side="left", padx=12)

    # ── Placeholder helpers ───────────────────────────────────────────────────
    _PLACEHOLDER = "https://www.youtube.com/playlist?list=..."

    def _clear_url(self):
        self._url_entry.delete(0, "end")
        self._url_entry.insert(0, self._PLACEHOLDER)
        self._url_entry.config(fg=SUBTEXT)
        self._save_settings()

    def _on_url_focusout(self, _=None):
        self._restore_placeholder()
        self._save_settings()

    def _clear_placeholder(self, _=None):
        if self._url_var.get() == self._PLACEHOLDER:
            self._url_entry.delete(0, "end")
            self._url_entry.config(fg=TEXT)

    def _restore_placeholder(self, _=None):
        if not self._url_var.get().strip():
            self._url_entry.insert(0, self._PLACEHOLDER)
            self._url_entry.config(fg=SUBTEXT)

    def _paste_url(self):
        logger.info("Paste button clicked")
        try:
            txt = self.clipboard_get().strip()
            logger.info("Clipboard: %s", txt[:80])
            self._url_entry.delete(0, "end")
            self._url_entry.insert(0, txt)
            self._url_entry.config(fg=TEXT)
        except Exception as e:
            logger.error("Paste failed: %s", e)

    def _pick_folder(self):
        folder = filedialog.askdirectory(title="Select folder for MP3 files")
        if folder:
            self._dir_var.set(folder)
            logger.info("Output folder: %s", folder)
            self._save_settings()

    def _open_folder(self):
        folder = self._dir_var.get()
        if os.path.isdir(folder):
            os.startfile(folder)
        else:
            messagebox.showinfo("Folder", "Folder not created yet. Start a download first.")

    def _get_browser(self):
        """Get the selected browser name for cookies, or None."""
        val = self._browser_var.get()
        if val == "Auto-detect":
            return self._detected_browser
        elif val == "None (no cookies)":
            return None
        else:
            return val.lower()

    def _detect_browser_async(self):
        """Detect available browser for cookies in background."""
        def worker():
            logger.info("Auto-detecting browser for cookies...")
            browser = detect_browser()
            self._detected_browser = browser
            if browser:
                self.after(0, lambda: self._cookie_status.config(
                    text=f"OK: {browser}", fg=GREEN))
            else:
                self.after(0, lambda: self._cookie_status.config(
                    text="No cookies found. May get bot-blocked.", fg=RED))
        threading.Thread(target=worker, daemon=True).start()

    # ── Settings persistence ──────────────────────────────────────────────────
    def _save_settings(self):
        url = self._url_var.get().strip()
        if url == self._PLACEHOLDER:
            url = ""
        self._config["url"] = url
        self._config["folder"] = self._dir_var.get()
        self._config["browser"] = self._browser_var.get()
        save_config(self._config)

    def _restore_settings(self):
        url = self._config.get("url", "")
        folder = self._config.get("folder", "")
        browser = self._config.get("browser", "")

        if url:
            self._url_entry.delete(0, "end")
            self._url_entry.insert(0, url)
            self._url_entry.config(fg=TEXT)
            logger.info("Restored URL: %s", url[:60])

        if folder:
            self._dir_var.set(folder)
            logger.info("Restored folder: %s", folder)

        if browser:
            self._browser_var.set(browser)
            logger.info("Restored browser: %s", browser)

    def _on_close(self):
        self._save_settings()
        self.destroy()

    # ── Fetch info ────────────────────────────────────────────────────────────
    def _fetch_info(self):
        url = self._get_url()
        if not url:
            return
        logger.info("Fetch info: %s", url)
        self._set_status("Getting playlist info...")
        self._fetch_btn.config(state="disabled")
        self._dl_btn.config(state="disabled")

        browser = self._get_browser()
        def worker():
            try:
                d = PlaylistDownloader(self._dir_var.get(), browser=browser)
                tracks = d.fetch_playlist_info(url)
                self.after(0, self._show_tracks, tracks)
            except Exception as ex:
                logger.error("Fetch error: %s", ex)
                self.after(0, self._show_error, str(ex))
            finally:
                self.after(0, lambda: self._fetch_btn.config(state="normal"))
                self.after(0, lambda: self._dl_btn.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _show_tracks(self, tracks):
        self._clear_tracks()
        for t in tracks:
            row = TrackRow(self._track_container, t["index"], t["title"])
            row.pack(fill="x", padx=2, pady=2)
            self._track_rows.append(row)
        count = len(tracks)
        self._set_status(f"Found {count} tracks. Click 'Download All'.")
        self._global_bar.set(0)
        self._pct_label.config(text="")
        self._progress_label.config(text=f"0 / {count} tracks")
        logger.info("Showing %d tracks in UI", count)

    # ── Download ──────────────────────────────────────────────────────────────
    def _sync_download(self):
        """Download only tracks that are missing from the output folder."""
        self._start_download(skip_existing=True)

    def _start_download(self, skip_existing=True):
        url = self._get_url()
        if not url:
            return
        if self._is_running:
            logger.info("Download already running - ignoring")
            return

        self._save_settings()
        mode = "SYNC (skip existing)" if skip_existing else "FULL (re-download all)"
        logger.info("=== START DOWNLOAD [%s]: %s ===", mode, url)
        self._is_running = True
        self._dl_btn.config(state="disabled")
        self._sync_btn.config(state="disabled")
        self._fetch_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        self._clear_tracks()
        self._global_bar.set(0)
        self._pct_label.config(text="0%")
        self._progress_label.config(text="Preparing...")

        out_dir = self._dir_var.get()
        browser = self._get_browser()
        logger.info("Using browser for cookies: %s", browser or "none")
        self._downloader = PlaylistDownloader(
            output_dir=out_dir,
            browser=browser,
            skip_existing=skip_existing,
            on_progress=self._on_progress_cb,
            on_status=self._on_status_cb,
            on_done=self._on_done_cb,
            on_error=self._on_error_cb,
        )
        self._downloader.download_playlist(url)

    def _cancel(self):
        logger.info("Cancel clicked")
        if self._downloader:
            self._downloader.cancel()
        self._set_status("Cancelling...")
        self._reset_buttons()

    # ── Callbacks from downloader (worker thread -> main thread) ──────────────
    def _on_progress_cb(self, idx, total, title, pct):
        self.after(0, self._update_progress, idx, total, title, pct)

    def _on_status_cb(self, msg):
        self.after(0, self._set_status, msg)

    def _on_done_cb(self):
        self.after(0, self._handle_done)

    def _on_error_cb(self, msg):
        self.after(0, self._show_error, msg)
        self.after(0, self._reset_buttons)

    # ── UI updates (main thread only) ─────────────────────────────────────────
    def _update_progress(self, idx, total, title, pct):
        while len(self._track_rows) < idx:
            n = len(self._track_rows) + 1
            row = TrackRow(self._track_container, n, title)
            row.pack(fill="x", padx=2, pady=2)
            self._track_rows.append(row)

        row = self._track_rows[idx - 1]
        row._title_lbl.config(text=title)

        if pct >= 100:
            row.set_done()
        else:
            row.set_downloading(pct)

        global_pct = ((idx - 1) * 100 + pct) / total
        self._global_bar.set(global_pct)
        self._pct_label.config(text=f"{global_pct:.0f}%")
        self._progress_label.config(text=f"{idx} / {total} - {title[:50]}")

    def _handle_done(self):
        self._global_bar.set(100)
        self._pct_label.config(text="100%")
        self._set_status(f"Done! All tracks saved to: {self._dir_var.get()}")
        self._reset_buttons()
        messagebox.showinfo("Done!", f"All MP3 files downloaded!\n\nFolder: {self._dir_var.get()}")

    def _show_error(self, msg):
        self._set_status(f"Error: {msg}")
        messagebox.showerror("Error", msg)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _get_url(self):
        url = self._url_var.get().strip()
        if not url or url == self._PLACEHOLDER:
            logger.info("No URL entered")
            messagebox.showwarning("URL", "Enter a YouTube playlist URL.")
            return ""
        if "youtube.com" not in url and "youtu.be" not in url:
            logger.info("Invalid URL: %s", url)
            messagebox.showwarning("URL", "This doesn't look like a YouTube URL.")
            return ""
        logger.info("URL OK: %s", url)
        return url

    def _set_status(self, msg):
        self._status_var.set(msg)

    def _clear_tracks(self):
        for w in self._track_container.winfo_children():
            w.destroy()
        self._track_rows.clear()

    def _reset_buttons(self):
        self._is_running = False
        self._dl_btn.config(state="normal")
        self._sync_btn.config(state="normal")
        self._fetch_btn.config(state="normal")
        self._cancel_btn.config(state="disabled")
        logger.info("Buttons reset")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("YouTube Playlist -> MP3 Downloader")
    logger.info("=" * 50)
    app = App()
    app.mainloop()
