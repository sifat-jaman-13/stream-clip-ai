# StreamSnip AI — Auto Stream Clipper

> Turn Twitch and YouTube streams—or local video files—into captioned, social-ready clips on your own machine.

[![Source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/sifat-jaman-13/stream-clip-ai)
[![Windows installer](https://img.shields.io/badge/download-Windows%20installer-e94560?logo=windows)](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest/download/AutoClip-Setup.exe)
[![Portable ZIP](https://img.shields.io/badge/download-portable%20ZIP-7c3aed?logo=windows)](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest/download/AutoClip-portable.zip)
[![Native edition](https://img.shields.io/badge/download-StreamSnip%20Native-DEA584?logo=rust)](https://github.com/sifat-jaman-13/stream-clip-ai-rust/releases/latest)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-files-2496ED?logo=docker)](Dockerfile)

[![YouTube: Scarzero](https://img.shields.io/badge/YouTube-Scarzero-red?logo=youtube)](https://www.youtube.com/@scarzeroyt)
[![Twitch: Scarzero13](https://img.shields.io/badge/Twitch-Scarzero13-9146FF?logo=twitch)](https://www.twitch.tv/scarzero13)
[![TikTok: Scarzero13](https://img.shields.io/badge/TikTok-Scarzero13-000000?logo=tiktok)](https://www.tiktok.com/@scarzero13)
[![Instagram: Scarzero13](https://img.shields.io/badge/Instagram-Scarzero13-E4405F?logo=instagram)](https://www.instagram.com/scarzero13/)
[![Facebook: ScarZero13](https://img.shields.io/badge/Facebook-ScarZero13-1877F2?logo=facebook)](https://www.facebook.com/ScarZero13)

## Choose your install method

| Option | Use it when | Link |
|---|---|---|
| **Windows installer** | Start Menu/desktop shortcuts and bundled runtime | [Download installer](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest/download/AutoClip-Setup.exe) |
| **Portable Windows** | Extract and run from a folder or USB drive | [Download portable ZIP](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest/download/AutoClip-portable.zip) |
| **Manual terminal** | Full control over Python, FFmpeg, CUDA, and dependencies | Follow the source setup below |
| **StreamSnip Native** | Rust launcher installer for Windows | [Open Native Edition](https://github.com/sifat-jaman-13/stream-clip-ai-rust) |

The Windows packages open a visible terminal and print the local server URL. Keep that terminal open
while recording, rendering, or publishing. Closing the app stops its local server.

## What the app does

- Captures live streams with a preference of 1080p60, 1080p, 720p60, 720p, then best.
- Processes Twitch/YouTube live URLs or local MP4, MKV, TS, FLV, and WebM files.
- Detects moments from audio energy, speech rate, and built-in/custom hype words.
- Produces 1080-based output in 9:16, 16:9, 1:1, or 4:5 formats.
- Supports Facecam + game, blurred background, fill crop, and manually selected source crop.
- Provides a four-corner draggable facecam selector with reset-to-center behavior.
- Transcribes with distil-large-v3, large-v3-turbo, small, or base.
- Renders Karaoke/Classic subtitles with Classic, Hormozi, Neon, MrBeast, Minimal, and Fire presets.
- Adds streamer credit from the source URL, optional on-video credit, and a configurable CTA.
- Shows render/transcription and Zernio publishing progress bars, selection, bulk delete, and activity history.
- Publishes selected or all clips through optional local Zernio configuration.

## Requirements

Native install:

- Python 3.10 or newer
- FFmpeg on PATH
- Streamlink for live Twitch/YouTube sources
- NVIDIA CUDA hardware is optional; CPU fallback is supported

Docker files are included. The current app binds its UI to a local ephemeral port and prints that port
at startup; use Docker as a packaging/headless starting point, or adapt the bind/port setup when you
need browser access from outside the container.

## Manual installation

### Windows PowerShell

~~~powershell
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai
winget install Gyan.FFmpeg
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[all]"
~~~

If PowerShell blocks activation:

~~~powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
~~~

### macOS or Linux

Install Python 3.10+ and FFmpeg with your system package manager, then:

~~~bash
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[all]"
~~~

On Apple Silicon, use native arm64 Python and the CPU/INT8 path. The project does not claim an
automatic CTranslate2 MPS backend.

## Run it

### Web app

~~~powershell
autoclip
# Or: python autoclip.py
~~~

The app opens a local browser window and prints its URL. If controls do not respond, disable your
ad blocker for 127.0.0.1 and localhost.

### Headless terminal mode

~~~bash
autoclip live https://www.twitch.tv/your_channel
autoclip live https://www.youtube.com/watch?v=LIVE_ID
autoclip file /path/to/recording.mp4
~~~

The direct equivalents are python autoclip.py live URL and python autoclip.py file PATH.

## Defaults and controls

| Setting | Default | Meaning |
|---|---:|---|
| Minimum viral score | **70** | Higher keeps only stronger moments |
| Clips per chunk | **2** | 0 means no limit |
| Live chunk length | **3 minutes** | Each segment is analyzed separately |
| Before / after peak | **20 / 15 seconds** | Context around the detected moment |
| Output format | **9:16** | 1080 × 1920 portrait |
| Speech model | **distil-large-v3** | Changeable in Output |
| CTA | **Subscribe for more clips** | Text plus optional Windows SAPI voice |
| Streamer tag | Auto-detected | Blank uses the source URL handle |

Settings are persisted in settings.json. Recording and output folders are configurable from Settings;
missing rec and out directories are recreated automatically.

## Subtitles, framing, and output

Enable Subtitles (customize) to choose mode, preset, font size, text/stroke colors, position,
alignment, and vertical nudge. The source-frame selector uses the original frame—normally 16:9—so
you can select the exact segment instead of accepting a forced crop. The facecam selector has handles
on all four corners and a reset control.

Each finished clip has an MP4 and matching TXT caption file:

~~~text
out/
├── clip_name.mp4
└── clip_name.txt
~~~

Raw live segments are stored in the recording folder and can be deleted after clipping.

## Zernio publishing

Zernio is optional and disabled until configured. In Settings → Zernio posting:

1. Enter the API key and save it locally.
2. Identify connected Instagram and YouTube channels.
3. Choose channel IDs, visibility, schedule delay, and auto-post behavior.
4. Select individual clips, double-click a clip, select all, or publish the whole batch.

The key is saved in local zernio.json and must never be committed or shared. Posting depends on the
separate zernio_poster.py integration and a working Zernio account.

## Runtime and app updates

Settings includes:

- App version check with a link to the latest release
- FFmpeg, faster-whisper, Streamlink, CTranslate2, NumPy, and speech-model checks
- Component update and selected speech-model download controls

The app update control opens the release page; it does not replace files during a running recording.

## Build Windows packages

~~~powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
~~~

The script creates a console-enabled PyInstaller one-folder build, bundles FFmpeg when found, creates
dist\AutoClip-portable.zip, and compiles dist\installer\AutoClip-Setup.exe when Inno Setup 6 is
installed. Installer metadata is StreamSnip AI 1.0.1 by ScarZero.

## Troubleshooting

| Symptom | Check |
|---|---|
| Buttons do nothing | Disable the ad blocker for 127.0.0.1 / localhost |
| Stream stops immediately | Ensure only one copy is running and inspect Activity |
| No stream found | Confirm Streamlink is installed and keep the best fallback |
| FFmpeg missing | Install FFmpeg or use the bundled Windows package |
| No clips | Lower minimum viral score and inspect transcription/activity |
| CUDA error | Update NVIDIA drivers; CPU fallback remains available |
| Zernio unavailable | Check zernio_poster.py, API key, and channel settings |
| Browser does not open | Copy the printed local URL into a browser |

## Project map

| Path | Purpose |
|---|---|
| autoclip.py | Local server, web UI, clipping engine, captions, progress, and orchestration |
| zernio_poster.py | Optional Zernio API integration |
| build_windows.ps1 | PyInstaller, portable ZIP, and Inno Setup build |
| installer/AutoClip.iss | Windows installer metadata and shortcuts |
| Dockerfile / docker-compose.yml | Container packaging |
| assets/ | App icon and brand artwork |

## Credits and links

Created by **Sifat Jaman / ScarZero**. Built with credit to ChatGPT 5.6 Luna, Claude, and
Antigravity, and on top of faster-whisper, Streamlink, FFmpeg, NumPy, and CTranslate2.

- [Scar Clip Farm on YouTube](https://youtube.com/@scarclipfarm)
- [Scarzero on YouTube](https://www.youtube.com/@scarzeroyt)
- [Scarzero13 on Twitch](https://www.twitch.tv/scarzero13)
- [Scarzero13 on TikTok](https://www.tiktok.com/@scarzero13)
- [Scarzero13 on Instagram](https://www.instagram.com/scarzero13/)
- [ScarZero13 on Facebook](https://www.facebook.com/ScarZero13)

## License

MIT. See [LICENSE](LICENSE).
