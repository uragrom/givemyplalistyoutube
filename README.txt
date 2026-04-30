===================================================
  YouTube Playlist -> MP3 Downloader
  Powered by yt-dlp
===================================================

HOW TO USE
----------
1. Run:  py main.py
2. Paste your YouTube playlist URL
3. Select your browser (for cookies)
4. Click "Download All"

FILES WILL BE SAVED AS:
  Artist - Title.mp3
  with embedded ID3 tags (artist, title)


HOW TO ADD LOCAL FFMPEG
-----------------------
FFmpeg is required for MP3 conversion.
You can place ffmpeg.exe in any of these locations:

  Option 1 (simplest):
    givemyplalistyoutube\ffmpeg.exe

  Option 2 (bin subfolder):
    givemyplalistyoutube\bin\ffmpeg.exe

  Option 3 (ffmpeg subfolder):
    givemyplalistyoutube\ffmpeg\ffmpeg.exe
    givemyplalistyoutube\ffmpeg\bin\ffmpeg.exe

The app will automatically detect it on startup
and show "FFmpeg: OK (local)" in the interface.

DOWNLOAD FFMPEG:
  https://github.com/BtbN/FFmpeg-Builds/releases
  -> Download: ffmpeg-master-latest-win64-gpl.zip
  -> Extract and copy ffmpeg.exe into this folder


COOKIES (to bypass YouTube bot detection)
------------------------------------------
The app auto-detects Chrome, Edge, Firefox, etc.
Make sure your browser is installed and you are
logged into YouTube in that browser.


TROUBLESHOOTING
---------------
- "Requested format not available"  -> Already fixed,
  no format restriction is used.

- "Sign in to confirm you're not a bot" -> Select your
  browser in the dropdown so cookies are used.

- FFmpeg NOT FOUND -> Add ffmpeg.exe as shown above.

All logs are saved to:  app.log
===================================================
