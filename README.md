# StreamSnip AI

### Local AI clipping for live streams, VODs, Shorts, Reels, and YouTube

> Turn Twitch and YouTube streams—or local video files—into captioned, social-ready clips on your own machine.

<p align="center">
  <strong>Capture → transcribe → score → render → publish</strong><br>
  Local speech transcription and rendering, with optional local or hosted AI highlight analysis.
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
| **Portable Windows app** | Run the compiled app directly without the installer | [Download portable app](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest/download/StreamSnipAI-Portable.zip) |
| **Manual terminal** | Full control over Python, FFmpeg, CUDA, and dependencies | Follow the source setup below |

The Windows installer opens a visible terminal through the real `StreamSnipAI.exe` launcher and prints the local server URL. Keep that terminal open
while recording, rendering, or publishing. Closing that terminal or choosing Quit stops the local server.

The app's browser interface and default hook-word analysis run locally. If you choose Gemini or hosted
Hugging Face analysis, the timestamped transcript is sent to that provider. API credentials are stored
in local app data and are not included in the page sent to the browser.

## What the app does

- Captures live streams with a preference of 1080p60, 1080p, 720p60, 720p, then best.
- Processes Twitch/YouTube live URLs or local MP4, MKV, TS, FLV, and WebM files.
- Transcribes speech locally with faster-whisper, then finds moments using audio energy, speech rate, and built-in/custom hook words.
- Produces 1080-based output in 9:16, 16:9, 1:1, or 4:5 formats.
- Supports Facecam + game, blurred background, fill crop, and manually selected source crop.
- Provides a four-corner draggable facecam selector with reset-to-center behavior.
- Transcribes with distil-large-v3, large-v3-turbo, medium, large-v3, small, or base.
- Finds viral moments with built-in/custom hook words, local Ollama models, Gemini, or Hugging Face hosted models; Gemini quota exhaustion automatically tries Ollama.
- Renders Karaoke/Classic subtitles with Classic, Hormozi, Neon, MrBeast, Minimal, and Fire presets.
- Adds streamer credit from the source URL, optional on-video credit, and a configurable CTA.
- Shows render/transcription and publishing progress, clip selection, bulk delete, and activity history.
- Publishes selected or all clips through Zernio, Postiz, or Mixpost.

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

Docker Compose exposes the UI only on this computer at [http://localhost:8080](http://localhost:8080); it is not configured for remote/LAN access.
Persistent settings, custom words, clips, and recordings are stored under `./data` on the host. Place a source video at
`./data/rec` to process it from the container. For Ollama on the host, allow connections from Docker in Ollama and
use the prefilled `host.docker.internal` address in AI settings. Docker runs CPU processing.

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

Publishing is optional. Automatic posting is off by default. Before configuring StreamSnip, connect the social accounts you want to use inside the provider dashboard. StreamSnip can only list channels the provider already reports as connected.

### Zernio

1. Sign in at [Zernio](https://zernio.com), open [API keys](https://zernio.com/dashboard/api-keys), choose **Create API key**, and copy the key. Zernio shows it once; see its [official quickstart](https://docs.zernio.com/quickstart).
2. In StreamSnip, open **Settings → Publishing**, select **Zernio**, and paste the key into **API key**. No base URL or workspace is needed.
3. Click **Save & identify channels**, select your connected Instagram and/or YouTube channel, and save.

### Postiz (Cloud or self-hosted)

1. In Postiz, connect your social channel. Open **Settings → Developers → Public API** and create/copy the API key. The [Postiz public API guide](https://docs.postiz.com/public-api/introduction) explains its API-key authentication.
2. In StreamSnip, select **Postiz** and paste the key. For Postiz Cloud, leave **Base URL** blank (the app uses `https://api.postiz.com`). For self-hosted Postiz, enter the instance root (for example, `https://postiz.example.com`). Do not add `/public/v1`; StreamSnip adds that API path. Leave **Workspace UUID** blank.
3. Click **Save & identify channels** once to save the key and load accounts. Choose the connected channel(s), then click the button again to save those selections.

### Mixpost (Cloud or self-hosted)

1. In Mixpost, connect your social channel. Open the user menu → **API** → **Create a personal key**, then copy it when Mixpost displays it. Find the workspace UUID in the dashboard URL or use Mixpost's [List your workspaces](https://docs.mixpost.app/api/reference/list-my-workspaces) API guide. See the [Mixpost API reference](https://docs.mixpost.app/api/) for personal keys and base URLs.
2. In StreamSnip, select **Mixpost**, paste the personal key, enter the Mixpost address in **Base URL**, and enter the workspace UUID in **Workspace UUID**. For Mixpost Cloud, use `https://cloud.mixpost.app/p`; for self-hosting, enter your instance address. Include any installed path in the base URL. Do not add `/api` or the workspace UUID; StreamSnip builds the API path.
3. Click **Save & identify channels** once to save the credentials and load accounts. Choose the connected channel(s), then click the button again to save those selections.

### Posting safely

- API credentials and publishing settings are saved locally in `publishing.json`. Keep API keys private; do not commit or share them.
- Select one clip using its checkbox, then click **Publish selected (1)** for a manual test. Keep **Auto-post** off until the provider and channel work as expected.
- **Auto-post** submits newly generated clips automatically when enabled. Configure **Schedule delay** and **YouTube visibility** in Publishing settings (visibility is currently sent by the Zernio and Postiz adapters). Repeat **Save & identify channels** if you reconnect or change accounts.
- Successful and failed publishing activity appears in **Activity**. If a channel does not appear, confirm it is connected in the provider dashboard and that your key has access.

Zernio is hosted. Postiz and Mixpost can use hosted or self-hosted instances and their REST APIs. Provider and social-platform plans, permissions, quotas, and media limits still apply. Some Mixpost instances require chunked uploads for videos over 10 MB, which this integration may not support.

## Capture quality

Live recording targets 1080p when the source provides it, falls back to 720p when necessary, and uses a
6,000 kbps capture video bitrate target by default (the lowest setting allowed). Clips render at the selected Full HD output dimensions
(1080×1920, 1920×1080, 1080×1080, or 1080×1350). A source stream below 1080p cannot contain real 1080p detail,
so the app preserves the best available source rather than inventing detail.

## Runtime and app updates

Settings includes:

- App version check with a link to the latest release
- FFmpeg, faster-whisper, Streamlink, CTranslate2, NumPy, and speech-model checks
- Component update and selected speech-model download controls

## AI highlight providers

Choose a provider in the prominent **Choose your highlight engine** card at the very top of the main screen. Its four choices stay visible so you can switch at any time. This setting controls transcript highlight analysis, separately from the faster-whisper speech-to-text model setting.

### Free built-in hook words (no AI service)

The default **Built-in and custom hook words** option analyzes speech and audio locally and works offline. Open the **Hype words** tab to review and edit hook phrases. Add phrases that fit your language, game, community, and content (such as reactions, surprising outcomes, or recurring catchphrases); remove defaults that do not fit. Save your changes. Hook words work together with audio-energy and speech-rate scoring.

### Gemini API key (Google AI Studio)

1. Sign in to [Google AI Studio](https://aistudio.google.com/), open **API keys**, and choose **Create API key**. Google says AI Studio creates a project and key for new users; see the [Gemini API getting-started guide](https://ai.google.dev/gemini-api/docs/get-started).
2. Copy the key and keep it private. In StreamSnip, choose **Gemini API** in the **Choose your highlight engine** card, paste the key into **Gemini API key**, and save AI settings. The key is stored locally by the app.
3. Process a short recording and check **Activity** for successful analysis or an authentication/quota error.

Google offers a free tier for eligible Gemini API models, but availability, model limits, and rate quotas can vary by model, project, and account. Check Google's current [Gemini API pricing and free-tier table](https://ai.google.dev/gemini-api/docs/pricing); a key does not mean unlimited free usage. StreamSnip reports quota/rate-limit errors returned by Google but cannot show remaining quota in advance. On quota/rate-limit, timeout, or temporary service errors, StreamSnip tries other available Gemini models that support text generation before trying Ollama for the remaining transcript windows. If Gemini models are unavailable or fail and a local Ollama model is configured and reachable, Ollama is used; otherwise the app falls back to built-in audio and hook-word scoring.

### Ollama local AI (runs on your computer)

Ollama runs the selected open model locally. Model inference is separate from Whisper transcription; both use computer resources, and larger Ollama models need more memory and may run more slowly.

1. Install Ollama from its [official download page](https://ollama.com/download). On Windows, use the installer. Ollama normally runs in the background and exposes its local API at `http://127.0.0.1:11434`.
2. Download a model. A modest starting point is Qwen 3 4B. Open PowerShell or Terminal and run:

   ~~~powershell
   ollama pull qwen3:4b
   ~~~

   The [Ollama model library](https://ollama.com/library) lists models and download sizes. Start with a smaller model; try a larger one if your computer has enough memory and you want to compare its results. Speed depends on your hardware and model choice.
3. In StreamSnip, choose **Ollama local AI** in the **Choose your highlight engine** card, leave **Ollama address** as `http://127.0.0.1:11434` for a standard local install, and click **Detect models**. Select the model that appears and save AI settings.
4. To check Ollama later, click **Detect models** again. If no models appear, confirm Ollama is running and a model is installed. `ollama list` shows installed model names.

To use a different model, choose one from the [Ollama library](https://ollama.com/library), copy its exact name/tag, and run `ollama pull MODEL_NAME` (replace `MODEL_NAME` with that name). After the download, click **Detect models** in StreamSnip and select it. For Gemini quota fallback, leave Ollama running and keep an installed model selected. In Docker, `127.0.0.1` points inside the container; use the host Ollama address from the Docker instructions instead.

### Hugging Face hosted model

Choose **Hugging Face open model (hosted)** to send transcript windows to the Hugging Face Inference Providers router. Enter a model ID and a Hugging Face token with Inference Providers access, then save. This is a hosted service; availability, credits, and rate limits depend on Hugging Face and the selected provider.

AI analysis processes timestamped transcript windows across the recording. The **Activity** log identifies the provider and model, says whether analysis is running locally or through a hosted API, reports the transcript window being analyzed, records Gemini model retries and Ollama fallback, and reports how many moments the model returned. If an AI provider returns no moments or fails, the app logs the issue and falls back to built-in audio and hook-word scoring. Stop requests cancel waiting AI analysis. AI results are limited by **Clips per chunk** and **Minimum viral score**. Whisper models from Hugging Face are separate downloads that run locally; they are not the hosted Hugging Face chat-analysis provider.

The app update control opens the release page; it does not replace files during a running recording.

## Build Windows packages

~~~powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
~~~

The script creates a PyInstaller compatibility build in `dist\AutoClip`, a real
`dist\StreamSnipAI.exe` terminal launcher, a portable app archive at
`dist\StreamSnipAI-Portable.zip`, and compiles `dist\installer\StreamSnipAI-Setup.exe` when Inno
Setup 6 is installed. The portable archive contains the compiled app as `StreamSnipAI.exe` plus
its required runtime files; extract the whole archive and run that EXE. The installer ships the
Python source and bootstrap files; it downloads the runtime and dependencies on first setup.

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
| autoclip.py | Local server, web UI, clipping engine, captions, settings, progress, and orchestration |
| ai_highlights.py | Ollama, Gemini, and Hugging Face transcript highlight analysis |
| launcher.py | Source for the real Windows StreamSnipAI.exe launcher |
| run_streamsnip.cmd | Internal terminal/runtime bootstrap command |
| installer/bootstrap.ps1 | Python runtime, dependency, and speech-model setup |
| zernio_poster.py | Optional Zernio API integration |
| selfhost_publishers.py | Optional Postiz and Mixpost API integrations |
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
