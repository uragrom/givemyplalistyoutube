"""
sync_to_phone.py
Sync MP3 files from a local folder (Google Drive) to Android phone.

Two modes:
  - ADB mode: phone connected via USB with USB Debugging enabled
  - Folder mode: phone mounted as a drive letter (File Transfer / MSD mode)

Run:  py sync_to_phone.py
"""

import os
import sys
import json
import shutil
import logging
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("sync")

# ── Config ─────────────────────────────────────────────────────────────────────
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SRC_DIR)
_CFG = os.path.join(_PROJECT_DIR, "sync_config.json")

def load_cfg():
    try:
        if os.path.isfile(_CFG):
            return json.load(open(_CFG, encoding="utf-8"))
    except Exception:
        pass
    return {}

def save_cfg(d):
    try:
        json.dump(d, open(_CFG, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    except Exception:
        pass

# ── ADB helpers ────────────────────────────────────────────────────────────────
def find_adb():
    """Find adb.exe on PATH or in tools folder."""
    local = os.path.join(_PROJECT_DIR, "tools", "adb.exe")
    if os.path.isfile(local):
        return local
    found = shutil.which("adb")
    return found  # None if not found

def adb(adb_exe, *args, capture=True, timeout=30):
    cmd = [adb_exe] + list(args)
    if capture:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return (r.stdout or "").strip(), r.returncode
    else:
        return subprocess.run(cmd, timeout=timeout), 0

def list_adb_devices(adb_exe):
    """Return list of (serial, state) tuples for all connected devices."""
    out, _ = adb(adb_exe, "devices")
    devices = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if line and "\t" in line:
            serial, state = line.split("\t", 1)
            devices.append((serial.strip(), state.strip()))
    return devices, out  # also return raw output for diagnostics

def adb_ls(adb_exe, serial, remote_path):
    """List filenames in a remote directory."""
    out, code = adb(adb_exe, "-s", serial, "shell", f"ls '{remote_path}' 2>/dev/null")
    if code != 0 or "No such file" in out:
        return None  # directory doesn't exist
    names = [n.strip() for n in out.splitlines() if n.strip()]
    return names

def adb_mkdir(adb_exe, serial, remote_path):
    adb(adb_exe, "-s", serial, "shell", f"mkdir -p '{remote_path}'")

def adb_push(adb_exe, serial, local_file, remote_path):
    cmd = [adb_exe, "-s", serial, "push", local_file, remote_path]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    ok = r.returncode == 0
    return ok, (r.stderr or r.stdout or "").strip()


# ── Colours ────────────────────────────────────────────────────────────────────
BG      = "#0f0f13"
SURFACE = "#1a1a24"
CARD    = "#22222f"
ACCENT  = "#7c3aed"
GREEN   = "#22c55e"
RED     = "#ef4444"
YELLOW  = "#eab308"
TEAL    = "#0d9488"
TEXT    = "#f1f5f9"
SUB     = "#94a3b8"
BORDER  = "#2d2d3d"
FONT    = "Segoe UI"


def styled_btn(parent, text, cmd, bg=ACCENT, hover="#6d28d9", **kw):
    b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=TEXT,
                  activebackground=hover, activeforeground=TEXT,
                  font=(FONT, 10, "bold"), relief="flat", bd=0,
                  padx=14, pady=8, cursor="hand2", **kw)
    b.bind("<Enter>", lambda _: b.config(bg=hover))
    b.bind("<Leave>", lambda _: b.config(bg=bg))
    return b


# ── Main App ───────────────────────────────────────────────────────────────────
class SyncApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MP3 → Phone Sync")
        self.geometry("700x680")
        self.minsize(600, 560)
        self.configure(bg=BG)
        self.resizable(True, True)

        self._cfg = load_cfg()
        self._adb = find_adb()
        self._running = False
        self._cancel_flag = threading.Event()

        self._build()
        self._restore()
        self._check_adb_status()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Restart ADB server once on startup (fixes stale server)
        if self._adb:
            threading.Thread(target=self._startup_adb_restart, daemon=True).start()

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=SURFACE)
        hdr.pack(fill="x")
        tk.Label(hdr, text="MP3 → Phone Sync", bg=SURFACE, fg=TEXT,
                 font=(FONT, 15, "bold")).pack(side="left", padx=20, pady=14)
        self._adb_lbl = tk.Label(hdr, text="", bg=SURFACE, fg=YELLOW,
                                  font=(FONT, 9))
        self._adb_lbl.pack(side="right", padx=16)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=20, pady=14)

        # Source folder
        self._section(main, "Source folder (Google Drive music)")
        src_row = tk.Frame(main, bg=CARD)
        src_row.pack(fill="x")
        self._src_var = tk.StringVar()
        tk.Entry(src_row, textvariable=self._src_var, bg=SURFACE, fg=TEXT,
                 insertbackground=TEXT, relief="flat", font=(FONT, 10), bd=0
                 ).pack(side="left", fill="x", expand=True, ipady=8, padx=(10, 8), pady=8)
        styled_btn(src_row, "Browse", self._pick_src, bg=SURFACE, hover=CARD
                   ).pack(side="right", padx=(0, 8), pady=8)

        # Mode selector
        self._section(main, "Destination")
        mode_card = tk.Frame(main, bg=CARD, pady=10, padx=12)
        mode_card.pack(fill="x", pady=(0, 10))
        self._mode = tk.StringVar(value="adb")
        for val, lbl in [("adb", "USB via ADB  (requires USB Debugging on phone)"),
                          ("folder", "Folder / Drive letter  (phone mounted as USB storage)")]:
            tk.Radiobutton(mode_card, text=lbl, variable=self._mode, value=val,
                           command=self._on_mode_change,
                           bg=CARD, fg=TEXT, selectcolor=SURFACE,
                           activebackground=CARD, activeforeground=TEXT,
                           font=(FONT, 10)).pack(anchor="w", pady=2)

        # ADB panel
        self._adb_panel = tk.Frame(main, bg=CARD, pady=10, padx=12)
        self._adb_panel.pack(fill="x", pady=(0, 10))

        tk.Label(self._adb_panel, text="Connected device:", bg=CARD, fg=SUB,
                 font=(FONT, 9)).pack(anchor="w")
        dev_row = tk.Frame(self._adb_panel, bg=CARD)
        dev_row.pack(fill="x", pady=(4, 8))
        self._dev_var = tk.StringVar()
        self._dev_menu = tk.OptionMenu(dev_row, self._dev_var, "")
        self._dev_menu.config(bg=SURFACE, fg=TEXT, activebackground=ACCENT,
                               activeforeground=TEXT, font=(FONT, 10),
                               highlightthickness=0, relief="flat", bd=0)
        self._dev_menu.pack(side="left", padx=(0, 8))
        styled_btn(dev_row, "Refresh", self._refresh_devices, bg=SURFACE, hover=CARD
                   ).pack(side="left", padx=(0, 6))
        styled_btn(dev_row, "Diagnose", self._diagnose_adb, bg=SURFACE, hover=CARD
                   ).pack(side="left")

        # ADB status message
        self._adb_status_var = tk.StringVar(value="")
        self._adb_status_lbl = tk.Label(self._adb_panel, textvariable=self._adb_status_var,
                                         bg=CARD, fg=YELLOW, font=(FONT, 9), wraplength=550,
                                         justify="left")
        self._adb_status_lbl.pack(anchor="w", pady=(0, 6))

        tk.Label(self._adb_panel, text="Phone destination path:", bg=CARD, fg=SUB,
                 font=(FONT, 9)).pack(anchor="w")
        self._remote_var = tk.StringVar(value="/sdcard/Music")
        tk.Entry(self._adb_panel, textvariable=self._remote_var, bg=SURFACE, fg=TEXT,
                 insertbackground=TEXT, relief="flat", font=(FONT, 10), bd=0
                 ).pack(fill="x", ipady=7, pady=(4, 0), padx=2)

        # Folder panel
        self._folder_panel = tk.Frame(main, bg=CARD, pady=10, padx=12)
        # (packed on demand)
        fld_row = tk.Frame(self._folder_panel, bg=CARD)
        fld_row.pack(fill="x")
        self._dst_var = tk.StringVar()
        tk.Entry(fld_row, textvariable=self._dst_var, bg=SURFACE, fg=TEXT,
                 insertbackground=TEXT, relief="flat", font=(FONT, 10), bd=0
                 ).pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        styled_btn(fld_row, "Browse", self._pick_dst, bg=SURFACE, hover=CARD
                   ).pack(side="right")

        # Log area
        self._section(main, "Log")
        log_frame = tk.Frame(main, bg=SURFACE)
        log_frame.pack(fill="both", expand=True, pady=(0, 10))
        self._log_text = tk.Text(log_frame, bg=SURFACE, fg=TEXT, font=("Consolas", 9),
                                  relief="flat", bd=0, state="disabled",
                                  wrap="word", height=10)
        sb = tk.Scrollbar(log_frame, command=self._log_text.yview, bg=SURFACE)
        self._log_text.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True, padx=8, pady=6)

        # Progress
        self._prog_var = tk.DoubleVar()
        self._prog_bar = ttk.Progressbar(main, variable=self._prog_var,
                                          maximum=100, length=400)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor=SURFACE, background=ACCENT,
                         bordercolor=SURFACE, lightcolor=ACCENT, darkcolor=ACCENT)
        self._prog_bar.pack(fill="x", pady=(0, 6))
        self._status_var = tk.StringVar(value="Ready")
        tk.Label(main, textvariable=self._status_var, bg=BG, fg=SUB,
                 font=(FONT, 9)).pack(anchor="w")

        # Buttons
        btn_row = tk.Frame(main, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))
        self._sync_btn = styled_btn(btn_row, "Sync (skip existing)", self._start_sync,
                                     bg=TEAL, hover="#0f766e")
        self._sync_btn.pack(side="left", padx=(0, 8))
        self._copy_btn = styled_btn(btn_row, "Copy All (overwrite)", self._start_copy_all,
                                     bg="#16a34a", hover="#15803d")
        self._copy_btn.pack(side="left", padx=(0, 8))
        self._cancel_btn = styled_btn(btn_row, "Cancel", self._cancel,
                                       bg="#7f1d1d", hover="#991b1b")
        self._cancel_btn.pack(side="left")
        self._cancel_btn.config(state="disabled")

        self._on_mode_change()

    def _section(self, parent, title):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", pady=(8, 4))
        tk.Label(f, text=title.upper(), bg=BG, fg=SUB,
                 font=(FONT, 8, "bold")).pack(anchor="w")

    # ── Settings ───────────────────────────────────────────────────────────────
    def _restore(self):
        # Try to default source to last used MP3 folder from main app config
        main_cfg_path = os.path.join(_PROJECT_DIR, "config.json")
        if os.path.isfile(main_cfg_path):
            try:
                main_cfg = json.load(open(main_cfg_path, encoding="utf-8"))
                default_src = main_cfg.get("folder", "")
            except Exception:
                default_src = ""
        else:
            default_src = ""

        self._src_var.set(self._cfg.get("src", default_src))
        self._dst_var.set(self._cfg.get("dst", ""))
        self._remote_var.set(self._cfg.get("remote", "/sdcard/Music"))
        self._mode.set(self._cfg.get("mode", "adb"))
        self._on_mode_change()

    def _save(self):
        self._cfg.update({
            "src": self._src_var.get(),
            "dst": self._dst_var.get(),
            "remote": self._remote_var.get(),
            "mode": self._mode.get(),
        })
        save_cfg(self._cfg)

    def _on_close(self):
        self._save()
        self.destroy()

    # ── Mode toggle ────────────────────────────────────────────────────────────
    def _on_mode_change(self):
        if self._mode.get() == "adb":
            self._folder_panel.pack_forget()
            self._adb_panel.pack(fill="x", pady=(0, 10))
            self._refresh_devices()
        else:
            self._adb_panel.pack_forget()
            self._folder_panel.pack(fill="x", pady=(0, 10))

    # ── ADB ────────────────────────────────────────────────────────────────────
    def _startup_adb_restart(self):
        """Kill and restart ADB server on startup to ensure fresh device list."""
        try:
            adb(self._adb, "kill-server", timeout=5)
            adb(self._adb, "start-server", timeout=10)
        except Exception:
            pass
        # Refresh device list on main thread after server restart
        self.after(500, self._refresh_devices)

    def _check_adb_status(self):
        if self._adb:
            self._adb_lbl.config(text=f"ADB: {os.path.basename(self._adb)}", fg=GREEN)
        else:
            self._adb_lbl.config(text="ADB: not found  (place adb.exe here)", fg=RED)

    def _refresh_devices(self):
        if not self._adb:
            self._update_device_menu(["ADB not found"])
            self._adb_status_var.set("⚠ adb.exe not found. Download Platform Tools and place adb.exe here.")
            return
        try:
            devices, raw = list_adb_devices(self._adb)
            authorized = [(s, st) for s, st in devices if st == "device"]
            unauthorized = [(s, st) for s, st in devices if st == "unauthorized"]
            offline = [(s, st) for s, st in devices if st not in ("device", "unauthorized")]

            if authorized:
                serials = [s for s, _ in authorized]
                self._update_device_menu(serials)
                self._adb_status_lbl.config(fg=GREEN)
                self._adb_status_var.set(f"✓ {len(serials)} device(s) ready: {', '.join(serials)}")
                self._log(f"ADB ready: {', '.join(serials)}")
            elif unauthorized:
                serials = [s for s, _ in unauthorized]
                self._update_device_menu([f"{s} (unauthorized)" for s in serials])
                self._adb_status_lbl.config(fg=YELLOW)
                self._adb_status_var.set(
                    "⚠ Phone found but NOT authorized!\n"
                    "→ Unlock your phone and look for a popup:\n"
                    "  'Allow USB debugging from this computer?' → tap ALLOW\n"
                    "  Then click Refresh."
                )
                self._log(f"ADB unauthorized: {serials}. Check phone for auth dialog!")
            elif offline:
                self._update_device_menu(["Device offline"])
                self._adb_status_lbl.config(fg=RED)
                self._adb_status_var.set("⚠ Device offline. Try: unplug → replug USB cable.")
            else:
                self._update_device_menu(["No device found"])
                self._adb_status_lbl.config(fg=RED)
                self._adb_status_var.set(
                    "No device detected. Check:\n"
                    "1. USB cable is plugged in\n"
                    "2. Phone is in 'File Transfer' (MTP) or 'PTP' USB mode\n"
                    "3. USB Debugging is enabled (Settings → Developer options)\n"
                    "4. Phone screen is unlocked"
                )
                self._log("No ADB devices found. Raw output: " + raw.replace("\n", " | "))
        except Exception as e:
            self._update_device_menu([f"Error: {e}"])
            self._adb_status_var.set(f"Error running adb: {e}")

    def _diagnose_adb(self):
        """Show a popup with full adb diagnostics."""
        if not self._adb:
            messagebox.showinfo("ADB", "adb.exe not found in project folder or PATH.")
            return
        lines = [f"ADB path: {self._adb}\n"]
        # Kill and restart server
        lines.append("--- adb kill-server ---")
        out, _ = adb(self._adb, "kill-server")
        lines.append(out or "(ok)")
        lines.append("--- adb start-server ---")
        out, _ = adb(self._adb, "start-server")
        lines.append(out or "(ok)")
        lines.append("--- adb devices -l ---")
        out, _ = adb(self._adb, "devices", "-l")
        lines.append(out or "(empty)")
        text = "\n".join(lines)
        self._log("Diagnostics:\n" + text)

        # Show popup
        win = tk.Toplevel(self)
        win.title("ADB Diagnostics")
        win.configure(bg=BG)
        win.geometry("560x340")
        t = tk.Text(win, bg=SURFACE, fg=TEXT, font=("Consolas", 9),
                    relief="flat", bd=0, padx=10, pady=10)
        t.pack(fill="both", expand=True, padx=10, pady=10)
        t.insert("1.0", text)
        t.config(state="disabled")
        styled_btn(win, "Close & Refresh",
                   lambda: [win.destroy(), self._refresh_devices()]
                   ).pack(pady=(0, 10))
        # After kill/restart, refresh
        self.after(100, self._refresh_devices)

    def _update_device_menu(self, options):
        menu = self._dev_menu["menu"]
        menu.delete(0, "end")
        for opt in options:
            menu.add_command(label=opt,
                             command=lambda v=opt: self._dev_var.set(v))
        self._dev_var.set(options[0])

    # ── Folder pickers ─────────────────────────────────────────────────────────
    def _pick_src(self):
        d = filedialog.askdirectory(title="Select source folder (Google Drive music)")
        if d:
            self._src_var.set(d)

    def _pick_dst(self):
        d = filedialog.askdirectory(title="Select destination folder on phone/drive")
        if d:
            self._dst_var.set(d)

    # ── Log helpers ────────────────────────────────────────────────────────────
    def _log(self, msg):
        log.info(msg)
        self.after(0, self._append_log, msg)

    def _append_log(self, msg):
        self._log_text.config(state="normal")
        self._log_text.insert("end", msg + "\n")
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _set_status(self, msg):
        self.after(0, lambda: self._status_var.set(msg))

    def _set_progress(self, pct):
        self.after(0, lambda: self._prog_var.set(pct))

    # ── Sync entry points ──────────────────────────────────────────────────────
    def _start_sync(self):
        self._start(skip_existing=True)

    def _start_copy_all(self):
        self._start(skip_existing=False)

    def _start(self, skip_existing: bool):
        if self._running:
            return
        src = self._src_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showwarning("Source", "Choose a valid source folder first.")
            return

        mode = self._mode.get()

        # ── Snapshot ADB state NOW on the main thread before the worker starts ──
        # This prevents _refresh_devices() (triggered by the startup ADB restart)
        # from overwriting _dev_var while the worker is already running.
        adb_serial = None
        adb_remote = None
        if mode == "adb":
            raw_dev = self._dev_var.get()
            serial = raw_dev.split(" (")[0].strip()
            # NOTE: do NOT include "" in this tuple — empty string is a substring
            # of every string in Python, so `"" in serial` is always True.
            bad = ("No device", "Error", "not found", "offline", "unauthorized")
            if not serial or any(b.lower() in serial.lower() for b in bad):
                messagebox.showwarning("ADB", "No ready ADB device.\nCheck the status panel and try Refresh.")
                return
            if "unauthorized" in raw_dev:
                messagebox.showwarning("ADB", "Device unauthorized.\nUnlock phone and tap ALLOW on the USB debugging dialog.")
                return
            adb_serial = serial
            adb_remote = self._remote_var.get().strip().rstrip("/")

        self._save()
        self._running = True
        self._cancel_flag.clear()
        self._sync_btn.config(state="disabled")
        self._copy_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        self._prog_var.set(0)

        # Clear log
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

        t = threading.Thread(
            target=self._worker,
            args=(src, mode, skip_existing, adb_serial, adb_remote),
            daemon=True
        )
        t.start()

    def _cancel(self):
        self._cancel_flag.set()
        self._set_status("Cancelling...")

    def _reset_buttons(self):
        self._running = False
        self._sync_btn.config(state="normal")
        self._copy_btn.config(state="normal")
        self._cancel_btn.config(state="disabled")

    # ── Worker ─────────────────────────────────────────────────────────────────
    def _worker(self, src, mode, skip_existing, adb_serial=None, adb_remote=None):
        try:
            # Collect source MP3s
            mp3_files = sorted([
                f for f in os.listdir(src)
                if f.lower().endswith(".mp3")
            ])
            total = len(mp3_files)
            if total == 0:
                self._log("No MP3 files found in source folder!")
                self.after(0, self._reset_buttons)
                return

            self._log(f"Found {total} MP3 files in source")

            if mode == "adb":
                self._sync_adb(src, mp3_files, skip_existing, adb_serial, adb_remote)
            else:
                self._sync_folder(src, mp3_files, skip_existing)

        except Exception as e:
            self._log(f"FATAL ERROR: {e}")
            import traceback; traceback.print_exc()
        finally:
            self.after(0, self._reset_buttons)

    # ── ADB sync ───────────────────────────────────────────────────────────────
    def _sync_adb(self, src, mp3_files, skip_existing, serial, remote):
        if not self._adb:
            self._log("ADB not found! Place adb.exe in the project folder or install Android Platform Tools.")
            return

        # serial and remote were validated and captured on the main thread before the worker started.
        self._log(f"ADB device: {serial}")
        self._log(f"Remote path: {remote}")

        # Ensure remote directory exists
        adb_mkdir(self._adb, serial, remote)

        # List existing files on phone
        existing_on_phone = set()
        if skip_existing:
            names = adb_ls(self._adb, serial, remote)
            if names is None:
                self._log(f"Remote path does not exist or is empty, will create: {remote}")
            else:
                existing_on_phone = {n.lower() for n in names if n.lower().endswith(".mp3")}
                self._log(f"Files already on phone: {len(existing_on_phone)}")

        total = len(mp3_files)
        copied = skipped = failed = 0

        for i, fname in enumerate(mp3_files, 1):
            if self._cancel_flag.is_set():
                self._log(f"Cancelled. Copied {copied}, skipped {skipped}, failed {failed}.")
                return

            self._set_status(f"[{i}/{total}] {fname[:60]}")
            self._set_progress(i / total * 100)

            if skip_existing and fname.lower() in existing_on_phone:
                self._log(f"  SKIP: {fname}")
                skipped += 1
                continue

            local_path = os.path.join(src, fname)
            remote_path = f"{remote}/{fname}"
            self._log(f"  PUSH [{i}/{total}]: {fname}")
            ok, msg = adb_push(self._adb, serial, local_path, remote_path)
            if ok:
                copied += 1
            else:
                self._log(f"    FAILED: {msg}")
                failed += 1

        self._set_progress(100)
        summary = f"Done! Copied: {copied}, skipped: {skipped}, failed: {failed}"
        self._log("=" * 50)
        self._log(summary)
        self._set_status(summary)
        if failed == 0:
            self.after(0, lambda: messagebox.showinfo("Done!", summary))
        else:
            self.after(0, lambda: messagebox.showwarning("Done with errors", summary))

    # ── Folder sync ────────────────────────────────────────────────────────────
    def _sync_folder(self, src, mp3_files, skip_existing):
        dst = self._dst_var.get().strip()
        if not dst:
            self._log("No destination folder selected!")
            return

        os.makedirs(dst, exist_ok=True)
        self._log(f"Destination: {dst}")

        existing_in_dst = set()
        if skip_existing:
            existing_in_dst = {
                f.lower() for f in os.listdir(dst)
                if f.lower().endswith(".mp3")
            }
            self._log(f"Files already in destination: {len(existing_in_dst)}")

        total = len(mp3_files)
        copied = skipped = failed = 0

        for i, fname in enumerate(mp3_files, 1):
            if self._cancel_flag.is_set():
                self._log(f"Cancelled. Copied {copied}, skipped {skipped}, failed {failed}.")
                return

            self._set_status(f"[{i}/{total}] {fname[:60]}")
            self._set_progress(i / total * 100)

            if skip_existing and fname.lower() in existing_in_dst:
                self._log(f"  SKIP: {fname}")
                skipped += 1
                continue

            src_path = os.path.join(src, fname)
            dst_path = os.path.join(dst, fname)
            try:
                self._log(f"  COPY [{i}/{total}]: {fname}")
                shutil.copy2(src_path, dst_path)
                copied += 1
            except Exception as e:
                self._log(f"    FAILED: {e}")
                failed += 1

        self._set_progress(100)
        summary = f"Done! Copied: {copied}, skipped: {skipped}, failed: {failed}"
        self._log("=" * 50)
        self._log(summary)
        self._set_status(summary)
        if failed == 0:
            self.after(0, lambda: messagebox.showinfo("Done!", summary))
        else:
            self.after(0, lambda: messagebox.showwarning("Done with errors", summary))


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = SyncApp()
    app.mainloop()
