# YouTube Playlist → MP3 Downloader

A desktop GUI app that downloads your YouTube playlists as MP3 files with embedded metadata (artist, title, album art).

Built with Python + [yt-dlp](https://github.com/yt-dlp/yt-dlp).

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-red)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

---

## Features

- 🎵 Downloads entire YouTube playlists as **192 kbps MP3**
- 🖼️ Embeds the **YouTube thumbnail as album art** in every MP3
- 🏷️ Embeds **artist & title** ID3 tags automatically
- 📁 Saves as `Artist - Title.mp3`
- ⚡ **Sync New Only** — skips already-downloaded tracks, downloads only what's missing
- 🍪 Uses your **browser cookies** to bypass YouTube bot detection (Chrome/Edge/Firefox)
- 💾 Remembers your **last playlist URL and folder** between sessions
- 📂 Local FFmpeg support — just drop `ffmpeg.exe` in the project folder

---

## Requirements

- Python 3.10+
- Node.js 20+ (for YouTube JS challenge solving)
- FFmpeg

### Install Python dependencies

```bash
pip install -r requirements.txt
```

This installs `yt-dlp[default]` which includes `yt-dlp-ejs` for YouTube JS challenges.

---

## FFmpeg Setup

FFmpeg is required for MP3 conversion. Place it in **one of these locations** (checked in order):

```
givemyplalistyoutube/ffmpeg.exe          ← simplest
givemyplalistyoutube/bin/ffmpeg.exe
givemyplalistyoutube/ffmpeg/ffmpeg.exe
```

Or install it globally so it's on your system PATH.

**Download FFmpeg:**  
👉 https://github.com/BtbN/FFmpeg-Builds/releases  
→ `ffmpeg-master-latest-win64-gpl.zip` → extract → copy `ffmpeg.exe`

---

## Node.js Setup

Node.js is required to solve YouTube's JavaScript challenges (signature decryption).

**Download Node.js:**  
👉 https://nodejs.org/en/download/ (v20 or newer)

---

## Usage

```bash
py main.py
```

1. Paste your YouTube playlist URL
2. Select your browser for cookies (auto-detected on startup)
3. Choose your output folder
4. Click **Sync New Only** to download only missing tracks, or **Download All** to re-download everything

---

## How "Sync New Only" works

Before downloading, the app scans your output folder for existing `.mp3` files and compares them against the playlist. Any track whose title already exists in the folder is **skipped**. Only new additions to the playlist are downloaded.

---

## Browser Cookies

YouTube requires authentication to avoid bot detection. The app reads cookies directly from your installed browser — no manual export needed.

**Supported browsers:** Chrome, Edge, Firefox, Opera, Brave, Chromium

> Make sure you are **logged into YouTube** in that browser before running the app.

---

## Project Structure

```
givemyplalistyoutube/
├── main.py          # GUI (tkinter)
├── downloader.py    # Download logic (yt-dlp)
├── requirements.txt
├── README.md
└── .gitignore
```

---

## License

MIT
