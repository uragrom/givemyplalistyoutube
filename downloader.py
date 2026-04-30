"""
Core downloader module using yt-dlp to extract MP3s from YouTube playlists.
- Uses browser cookies to bypass bot detection
- Saves as "Artist - Title.mp3" with embedded metadata
- Supports local FFmpeg in the project folder
"""

import os
import sys
import re
import shutil
import time
import logging
import threading
import traceback
import yt_dlp

logger = logging.getLogger("downloader")

# Browsers to try for cookie extraction (in order)
BROWSERS_TO_TRY = ["chrome", "edge", "firefox", "opera", "brave", "chromium"]

# Directory of this script
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def find_ffmpeg() -> str:
    """Return path to ffmpeg binary.

    Search order:
      1. <project>/ffmpeg.exe          (drop it right here)
      2. <project>/bin/ffmpeg.exe      (bin subfolder)
      3. <project>/ffmpeg/ffmpeg.exe   (ffmpeg subfolder)
      4. System PATH
    Returns the directory containing ffmpeg (for yt-dlp ffmpeg_location),
    or empty string if not found.
    """
    candidates = [
        _PROJECT_DIR,
        os.path.join(_PROJECT_DIR, "bin"),
        os.path.join(_PROJECT_DIR, "ffmpeg"),
        os.path.join(_PROJECT_DIR, "ffmpeg", "bin"),
    ]
    for folder in candidates:
        exe = os.path.join(folder, "ffmpeg.exe")
        if os.path.isfile(exe):
            logger.info("FFmpeg found (local): %s", exe)
            return folder  # yt-dlp wants the directory, not the exe

    # Fall back to system PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        folder = os.path.dirname(system_ffmpeg)
        logger.info("FFmpeg found (system PATH): %s", system_ffmpeg)
        return folder

    logger.warning("FFmpeg NOT found. MP3 conversion will fail!")
    logger.warning("  -> Place ffmpeg.exe in: %s", _PROJECT_DIR)
    return ""


# Resolve FFmpeg once at import time
FFMPEG_DIR = find_ffmpeg()
FFMPEG_EXE = os.path.join(FFMPEG_DIR, "ffmpeg.exe") if FFMPEG_DIR else "ffmpeg"


def sanitize_filename(name: str) -> str:
    """Remove characters that are invalid in Windows filenames."""
    return re.sub(r'[\\/:*?"<>|]', '_', name)


def detect_browser():
    """Try to find a working browser for cookies."""
    for browser in BROWSERS_TO_TRY:
        try:
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "cookiesfrombrowser": (browser,),
                "js_runtimes": {"node": {}},
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(
                    "https://www.youtube.com/playlist?list=PLRqwX-V7Uu6ZiZxtDDRCi6uhfTH4FilpH",
                    download=False
                )
            if info and info.get("entries"):
                logger.info("Browser cookies OK: %s", browser)
                return browser
        except Exception as e:
            logger.info("Browser '%s' failed: %s", browser, str(e)[:80])
            continue
    logger.warning("No browser cookies available, will try without")
    return None


class PlaylistDownloader:
    """Handles fetching playlist info and downloading tracks as MP3."""

    def __init__(self, output_dir: str, browser: str = None,
                 skip_existing: bool = True,
                 on_progress=None, on_status=None,
                 on_done=None, on_error=None):
        self.output_dir = output_dir
        self.browser = browser
        self.skip_existing = skip_existing
        self.on_progress = on_progress
        self.on_status = on_status
        self.on_done = on_done
        self.on_error = on_error
        self._cancel = threading.Event()
        self._thread = None

    def _get_existing_files(self) -> set:
        """Get normalized names of all MP3 files in the output folder."""
        existing = set()
        if not os.path.isdir(self.output_dir):
            return existing
        for f in os.listdir(self.output_dir):
            if f.lower().endswith(".mp3"):
                name = os.path.splitext(f)[0].lower().strip()
                existing.add(name)
        return existing

    def _is_already_downloaded(self, display_name, title, artist, vid_id, existing) -> bool:
        """Check if a track is already in the output folder.
        Checks multiple name patterns since files could have been renamed."""
        candidates = [
            sanitize_filename(display_name),
            sanitize_filename(title),
            sanitize_filename(f"{artist} - {title}"),
            vid_id,
        ]
        for c in candidates:
            if c and c.lower().strip() in existing:
                return True
        # Also check if any existing file contains the title
        title_lower = title.lower().strip()
        for name in existing:
            if title_lower in name:
                return True
        return False

    def cancel(self):
        logger.info("CANCEL requested by user")
        self._cancel.set()

    def _base_opts(self):
        """Return base ydl options with cookies and JS runtime."""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            # Node.js runtime for solving YouTube JS challenges (yt-dlp-ejs)
            "js_runtimes": {"node": {}},
        }
        if self.browser:
            opts["cookiesfrombrowser"] = (self.browser,)
        return opts

    def fetch_playlist_info(self, url: str) -> list:
        """Return list of {index, title, url, id, artist} dicts."""
        logger.info("Fetching playlist info: %s", url)
        opts = self._base_opts()
        opts["extract_flat"] = True

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            logger.error("ERROR fetching playlist: %s", exc)
            raise ValueError(f"Failed to get playlist: {exc}")

        if not info:
            raise ValueError("Could not get playlist info. Check the URL.")

        playlist_title = info.get("title", "Unknown playlist")
        entries = list(info.get("entries") or [])
        logger.info("Playlist: '%s', entries: %d", playlist_title, len(entries))

        tracks = []
        for i, entry in enumerate(entries, 1):
            if entry is None:
                continue
            title = entry.get("title") or f"Track {i}"
            vid_id = entry.get("id", "")
            artist = (entry.get("uploader") or entry.get("channel") or "").strip()
            # Remove " - Topic" suffix from YouTube Music auto-channels
            if artist.endswith(" - Topic"):
                artist = artist[:-8].strip()
            tracks.append({
                "index": i,
                "title": title,
                "url": entry.get("url") or entry.get("webpage_url", ""),
                "id": vid_id,
                "artist": artist,
            })
            display = f"{artist} - {title}" if artist else title
            logger.info("  [%d] %s (id=%s)", i, display, vid_id)

        logger.info("Total valid tracks: %d", len(tracks))
        return tracks

    def download_playlist(self, url: str):
        """Start downloading in a background thread."""
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run, args=(url,), daemon=True)
        self._thread.start()
        logger.info("Download thread started")

    def _emit_status(self, msg):
        logger.info("STATUS: %s", msg)
        if self.on_status:
            self.on_status(msg)

    def _emit_progress(self, idx, total, title, pct):
        if self.on_progress:
            self.on_progress(idx, total, title, pct)

    def _emit_done(self):
        logger.info("ALL DONE")
        if self.on_done:
            self.on_done()

    def _emit_error(self, msg):
        logger.error("ERROR: %s", msg)
        if self.on_error:
            self.on_error(msg)

    def _run(self, url: str):
        try:
            self._emit_status("Getting playlist info...")

            tracks = self.fetch_playlist_info(url)
            total = len(tracks)

            if total == 0:
                self._emit_error("Playlist is empty or unavailable.")
                return

            self._emit_status(f"Found {total} tracks. Checking existing files...")
            os.makedirs(self.output_dir, exist_ok=True)
            logger.info("Output directory: %s", self.output_dir)

            # Build a set of existing filenames (normalized, no extension)
            existing = self._get_existing_files()
            logger.info("Existing MP3 files in folder: %d", len(existing))

            successful = 0
            skipped = 0
            failed = 0

            for idx, track in enumerate(tracks, 1):
                if self._cancel.is_set():
                    self._emit_status(f"Cancelled. Downloaded {successful}, skipped {skipped}/{total}.")
                    return

                title = track["title"]
                artist = track.get("artist", "")
                vid_id = track["id"]
                video_url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else track["url"]

                # Build display name
                display_name = f"{artist} - {title}" if artist else title

                # Check if already exists
                if self.skip_existing and self._is_already_downloaded(display_name, title, artist, vid_id, existing):
                    logger.info("[%d/%d] SKIP (exists): %s", idx, total, display_name)
                    self._emit_progress(idx, total, f"[SKIP] {display_name}", 100.0)
                    skipped += 1
                    continue

                logger.info("=" * 50)
                logger.info("[%d/%d] %s", idx, total, display_name)
                logger.info("  URL: %s", video_url)

                self._emit_progress(idx, total, display_name, 0.0)
                self._emit_status(f"[{idx}/{total}] {display_name}")

                # Temporary filename - we'll rename after getting full metadata
                temp_template = os.path.join(self.output_dir, "%(id)s_temp.%(ext)s")

                def make_hook(ci, ct, ctitle):
                    def hook(d):
                        status = d.get("status", "")
                        if status == "downloading":
                            pct_str = d.get("_percent_str", "0%").strip().replace("%", "")
                            try:
                                pct = float(pct_str)
                            except ValueError:
                                pct = 0.0
                            self._emit_progress(ci, ct, ctitle, pct)
                        elif status == "finished":
                            logger.info("  Download finished: %s", d.get("filename", "?"))
                    return hook

                # Download + extract audio in one pass
                # NO format restriction - let yt-dlp pick whatever is available
                # FFmpegExtractAudio will convert to mp3 regardless
                ydl_opts = self._base_opts()
                ydl_opts.update({
                    "outtmpl": temp_template,
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        },
                    ],
                    "noprogress": False,
                    "progress_hooks": [make_hook(idx, total, display_name)],
                    "retries": 3,
                    "fragment_retries": 3,
                })
                if FFMPEG_DIR:
                    ydl_opts["ffmpeg_location"] = FFMPEG_DIR

                try:
                    # Download and get info in one call
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(video_url, download=True)

                    if info is None:
                        logger.warning("  extract_info returned None for: %s", display_name)
                        failed += 1
                        self._emit_progress(idx, total, display_name, 100.0)
                        continue

                    # Get better artist info from full metadata
                    real_artist = (
                        info.get("artist") or
                        info.get("creator") or
                        info.get("uploader") or
                        info.get("channel") or
                        artist or "Unknown"
                    ).strip()
                    if real_artist.endswith(" - Topic"):
                        real_artist = real_artist[:-8].strip()

                    real_title = info.get("track") or info.get("title") or title

                    # Build final filename
                    final_name = sanitize_filename(f"{real_artist} - {real_title}")
                    display_name = f"{real_artist} - {real_title}"

                    # Find the temp mp3 file and rename it
                    temp_mp3 = os.path.join(self.output_dir, f"{vid_id}_temp.mp3")
                    final_mp3 = os.path.join(self.output_dir, f"{final_name}.mp3")

                    if os.path.exists(temp_mp3):
                        # Embed metadata using ffmpeg
                        import subprocess
                        tagged_mp3 = os.path.join(self.output_dir, f"{vid_id}_tagged.mp3")
                        ffmpeg_cmd = [
                            FFMPEG_EXE, "-y", "-i", temp_mp3,
                            "-metadata", f"artist={real_artist}",
                            "-metadata", f"title={real_title}",
                            "-codec", "copy",
                            tagged_mp3,
                        ]
                        try:
                            subprocess.run(
                                ffmpeg_cmd, check=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                            )
                            os.remove(temp_mp3)
                            # Remove existing file if present (re-download case)
                            if os.path.exists(final_mp3):
                                os.remove(final_mp3)
                            os.rename(tagged_mp3, final_mp3)
                        except Exception as tag_err:
                            logger.warning("  Metadata tagging failed: %s, using untagged file", tag_err)
                            if os.path.exists(tagged_mp3):
                                os.remove(tagged_mp3)
                            if os.path.exists(final_mp3):
                                os.remove(final_mp3)
                            os.rename(temp_mp3, final_mp3)

                        logger.info("  OK: %s", final_mp3)
                        successful += 1
                    else:
                        # Try to find any file with the video ID prefix
                        found = False
                        for f in os.listdir(self.output_dir):
                            if f.startswith(f"{vid_id}_temp"):
                                old_path = os.path.join(self.output_dir, f)
                                ext = os.path.splitext(f)[1]
                                new_path = os.path.join(self.output_dir, f"{final_name}{ext}")
                                if os.path.exists(new_path):
                                    os.remove(new_path)
                                os.rename(old_path, new_path)
                                logger.info("  OK (alt ext): %s", new_path)
                                found = True
                                successful += 1
                                break
                        if not found:
                            logger.warning("  Temp file not found for: %s", vid_id)
                            failed += 1

                except Exception as exc:
                    logger.error("  Exception: '%s': %s", display_name, exc)
                    failed += 1

                self._emit_progress(idx, total, display_name, 100.0)

            logger.info("=" * 50)
            logger.info("SUMMARY: %d downloaded, %d skipped, %d failed out of %d",
                        successful, skipped, failed, total)
            self._emit_status(
                f"Done! Downloaded: {successful}, skipped: {skipped}, failed: {failed}")
            self._emit_done()

        except Exception as exc:
            logger.error("FATAL ERROR: %s", exc)
            traceback.print_exc()
            self._emit_error(str(exc))
