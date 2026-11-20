# StreamSnip AI

### Local AI clipping for live streams, VODs, Shorts, Reels, and YouTube

> Turn Twitch and YouTube streams—or local video files—into captioned, social-ready clips on your own machine.

<p align="center">
  <strong>Capture → transcribe → score → render → publish</strong><br>
  Runs locally with optional NVIDIA GPU acceleration and automatic runtime setup.
</p>

[![Source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/sifat-jaman-13/stream-clip-ai)
[![Windows installer](https://img.shields.io/badge/download-Windows%20installer-e94560?logo=windows)](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest/download/StreamSnipAI-Setup.exe)
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
| **Windows installer** | Start Menu/desktop shortcuts; downloads its runtime on first setup | [Download installer](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest/download/StreamSnipAI-Setup.exe) |
| **Manual terminal** | Full control over Python, FFmpeg, CUDA, and dependencies | Follow the source setup below |

The Windows installer opens a visible terminal through the real `StreamSnipAI.exe` launcher and prints the local server URL. Keep that terminal open
while recording, rendering, or publishing. Closing that terminal or choosing Quit stops the local server.

## What the app does

- Captures live streams with a preference of 1080p60, 1080p, 720p60, 720p, then best.
- Processes Twitch/YouTube live URLs or local MP4, MKV, TS, FLV, and WebM files.
- Detects moments from audio energy, speech rate, and built-in/custom hype words.
- Produces 1080-based output in 9:16, 16:9, 1:1, or 4:5 formats.
- Supports Facecam + game, blurred background, fill crop, and manually selected source crop.
- Provides a four-corner draggable facecam selector with reset-to-center behavior.
- Transcribes with distil-large-v3, large-v3-turbo, medium, large-v3, small, or base.
- Finds viral moments with built-in/custom hook words, local Ollama models, Gemini, or Hugging Face hosted models; Gemini quota exhaustion automatically tries Ollama.
- Renders Karaoke/Classic subtitles with Classic, Hormozi, Neon, MrBeast, Minimal, and Fire presets.
- Adds streamer credit from the source URL, optional on-video credit, and a configurable CTA.
- Shows render/transcription and Zernio publishing progress bars, selection, bulk delete, and activity history.
- Publishes selected or all clips through optional local Zernio configuration.

## Requirements

Installation requirements:

- Python 3.10 or newer
- FFmpeg on PATH, or bundled by an installer built on a machine with FFmpeg available
- Streamlink for live Twitch/YouTube sources
- NVIDIA CUDA hardware is optional; CPU fallback is supported
- In Settings, choose GPU for CUDA speech + NVENC rendering or CPU for INT8 speech + software rendering, then click Save settings. An RTX 3060 Ti is supported.

## Installation storage and downloads

The installer is small, but it downloads a compatible Python runtime, speech/GPU packages, and the default
`distil-large-v3` speech model during setup. Plan for approximately **4–6 GB of free space** for a
complete first-time installation. Larger models such as `medium` and `large-v3` can require additional
model storage when selected. Recordings and finished clips are stored separately in the configured
recording/output folders and can require **many additional GB**, depending on stream length and clip count.

### What the Windows installer downloads

The installer automatically downloads or installs the following when needed:

| Component | Purpose |
|---|---|
| Python 3.10–3.14 | Runtime for the app; Python 3.12 is installed through `winget` only when no compatible Python is found |
| NumPy | Audio analysis and processing |
| faster-whisper | Speech transcription |
| CTranslate2, ONNX Runtime, Tokenizers, PyAV | Speech-model dependencies |
| Streamlink | Twitch and YouTube live capture |
| NVIDIA cuBLAS CUDA package | GPU speech acceleration for supported NVIDIA cards |
| `distil-large-v3` model | Default speech model, downloaded before first launch |
| FFmpeg and FFprobe | Bundled when available during installer build; otherwise install FFmpeg separately and add it to PATH |

Plan for approximately **4–6 GB** for the complete first-time installation. `medium` and `large-v3`
can use additional model storage. FFmpeg is not downloaded by the installer; install FFmpeg separately
and place it on PATH. CPU mode remains available when CUDA is unavailable.

Docker Compose exposes the UI only on this computer at [http://localhost:8080](http://localhost:8080). Persistent settings,
custom words, clips, and recordings are stored under `./data` on the host; place a source video at
`./data/rec` to process it from the container. For Ollama on the host, enable host access in Ollama and
use the prefilled `host.docker.internal` address in AI settings.

## Manual installation

### Windows PowerShell

~~~powershell
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai
winget install Gyan.FFmpeg
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[live]"
~~~

For NVIDIA CUDA speech support in a manual Windows install:

~~~powershell
pip install nvidia-cublas-cu12
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
pip install -e ".[live]"
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
| Speech model | **distil-large-v3** | Changeable in Output; medium and large-v3 are available for higher accuracy |
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

## Publishing providers

Publishing is optional. Automatic posting is off by default and starts only when enabled in Settings.
StreamSnip AI supports Zernio plus self-hosted Postiz and Mixpost. Choose the provider in Settings → Publishing provider:

1. Enter the provider API key and, for self-hosted services, the base URL (and Mixpost workspace UUID).
2. Identify connected Instagram and YouTube channels through the provider's official API.
3. Choose channel IDs, visibility, schedule delay, and auto-post behavior.
4. Select individual clips, double-click a clip, select all, or publish the whole batch.

Credentials are saved locally in `publishing.json` and must never be committed or shared. Zernio remains
available through `zernio_poster.py`; Postiz and Mixpost use their documented REST APIs. Self-hosted
instances still enforce the legitimate platform and provider rate limits.

Postiz uses its public API base URL and integration IDs. Mixpost uses its instance URL, personal key,
workspace UUID, account IDs, and the instance's `/api` endpoints. Connect Instagram and YouTube inside
Postiz or Mixpost first; StreamSnip only submits clips to accounts that the provider reports as connected.

## Capture quality

Live recording targets 1080p when the source provides it, falls back to 720p when necessary, and records
with an 8,000 kbps minimum video bitrate by default. Clips render at the selected Full HD output dimensions
(1080×1920, 1920×1080, 1080×1080, or 1080×1350). A source stream below 1080p cannot contain real 1080p detail,
so the app preserves the best available source rather than inventing detail.

## Runtime and app updates

Settings includes:

- App version check with a link to the latest release
- FFmpeg, faster-whisper, Streamlink, CTranslate2, NumPy, and speech-model checks
- Component update and selected speech-model download controls

## AI highlight providers

The default hook-word detector runs locally and supports the built-in list plus custom phrases. Ollama analysis also runs locally: install Ollama, download a model with Ollama, then use **Detect models** in AI settings. Gemini and Hugging Face hosted analysis send the timestamped transcript to that provider; enter the matching API key or access token. Provider quota/rate-limit errors appear in the activity log. When Gemini reports quota exhaustion, StreamSnip AI automatically checks Ollama and uses an installed local model when available. Whisper speech models are free open models downloaded from Hugging Face and run locally. Hugging Face model weights are open, though hosted inference providers may charge for usage.

The app update control opens the release page; it does not replace files during a running recording.

## Build Windows packages

~~~powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
~~~

The script creates a PyInstaller compatibility build in `dist\AutoClip`, a real
`dist\StreamSnipAI.exe` terminal launcher, and compiles
`dist\installer\StreamSnipAI-Setup.exe` when Inno Setup 6 is installed. The installer ships the
Python source and bootstrap files; it downloads the runtime and dependencies on first setup. No
portable package is published by the current release workflow.

## Troubleshooting

| Symptom | Check |
|---|---|
| Buttons do nothing | Disable the ad blocker for 127.0.0.1 / localhost |
| Stream stops immediately | Ensure only one copy is running and inspect Activity |
| No stream found | Confirm Streamlink is installed and keep the best fallback |
| FFmpeg missing | Install FFmpeg and add it to PATH, or use an installer build that bundled FFmpeg |
| No clips | Lower minimum viral score and inspect transcription/activity |
| CUDA error | Update NVIDIA drivers; CPU fallback remains available |
| Zernio unavailable | Check zernio_poster.py, API key, and channel settings |
| Browser does not open | Copy the printed local URL into a browser |

## Project map

| Path | Purpose |
|---|---|
| autoclip.py | Local server, web UI, clipping engine, captions, progress, and orchestration |
| launcher.py | Source for the real Windows StreamSnipAI.exe launcher |
| run_streamsnip.cmd | Internal terminal/runtime bootstrap command |
| installer/bootstrap.ps1 | Python runtime, dependency, and speech-model setup |
| zernio_poster.py | Optional Zernio API integration |
| build_windows.ps1 | PyInstaller and Inno Setup installer build |
| installer/AutoClip.iss | Windows installer metadata and shortcuts |
| Dockerfile / docker-compose.yml | Container packaging |
| assets/ | App icon and brand artwork |

## Credits and links

Created by **Sifat Jaman / ScarZero**. Product direction, source ownership, and final decisions
belong to Sifat Jaman. Development assistance is credited to **ChatGPT 5.6 Luna**, **Claude**, and
**Antigravity**. The runtime uses faster-whisper, Streamlink, FFmpeg, NumPy, and CTranslate2.

- [Scar Clip Farm on YouTube](https://youtube.com/@scarclipfarm)
- [Scarzero on YouTube](https://www.youtube.com/@scarzeroyt)
- [Scarzero13 on Twitch](https://www.twitch.tv/scarzero13)
- [Scarzero13 on TikTok](https://www.tiktok.com/@scarzero13)
- [Scarzero13 on Instagram](https://www.instagram.com/scarzero13/)
- [ScarZero13 on Facebook](https://www.facebook.com/ScarZero13)

## License

MIT. See [LICENSE](LICENSE).
