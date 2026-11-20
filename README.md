# 🚀 StreamClip AI — Twitch & YouTube to Shorts

> **Turn Twitch and YouTube streams into viral Shorts, Reels, and TikToks automatically.**
> Local AI highlight detection, animated captions, facecam/game layouts, and optional multi-platform publishing.

[![GitHub](https://img.shields.io/badge/install-from%20source-blue?logo=github)](https://github.com/sifat-jaman-13/stream-clip-ai)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker)](https://hub.docker.com/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-lightgrey)]()

[![Follow on YouTube](https://img.shields.io/badge/follow-YouTube-red?logo=youtube)](https://www.youtube.com/@scarzeroyt)
[![Follow on Twitch](https://img.shields.io/badge/follow-Twitch-9146FF?logo=twitch)](https://www.twitch.tv/scarzero13)
[![Follow on TikTok](https://img.shields.io/badge/follow-TikTok-000000?logo=tiktok)](https://www.tiktok.com/@scarzero13)
[![Follow on Instagram](https://img.shields.io/badge/follow-Instagram-E4405F?logo=instagram)](https://www.instagram.com/scarzero13/)
[![Follow on Facebook](https://img.shields.io/badge/follow-Facebook-1877F2?logo=facebook)](https://www.facebook.com/ScarZero13)

## Choose how to run AutoClip

- **Installer:** [Download AutoClip-Setup.exe](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest) for a normal Windows installation with shortcuts.
- **Portable:** Download **AutoClip-portable.zip** from the [latest release](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest), extract it, and run AutoClip.exe.
- **Manual terminal:** Follow the Windows commands below for full control over Python, FFmpeg, GPU packages, and the server.

**Keywords:** `twitch clipper` · `youtube clipper` · `stream to shorts` · `AI clip maker` · `viral shorts generator` · `TikTok clip generator` · `Instagram Reels maker` · `YouTube Shorts automation` · `Whisper captions`

### Optional Zernio posting

AutoClip includes a Zernio panel for identifying connected Instagram and
YouTube channels, publishing selected clips, publishing all clips, and
optionally auto-posting each newly finished MP4. It is disabled by default.

Open the app, enter your Zernio API key in the **Zernio posting** section, and
click **Save & identify channels**. The key is stored only in the local,
Git-ignored `zernio.json` file. Each clip's `.txt` file supplies its caption;
the first caption line becomes the YouTube title.

For headless/background use, set these environment variables locally before starting AutoClip:

```powershell
$env:ZERNIO_ENABLED="true"
$env:ZERNIO_API_KEY="your-zernio-api-key"
$env:ZERNIO_INSTAGRAM_ACCOUNT_ID="your-instagram-account-id"
$env:ZERNIO_YOUTUBE_ACCOUNT_ID="your-youtube-account-id"
$env:ZERNIO_SCHEDULE_MINUTES="0"       # 0 = publish now; e.g. 120 = schedule 2 hours later
$env:ZERNIO_YOUTUBE_VISIBILITY="public" # public, private, or unlisted
python autoclip.py
```

You may set only one platform account ID. Keep the API key in your local
environment; never put it in `settings.json`, source code, or Git. Instagram
must be a Business or Creator account. Zernio receives the video and caption
after each clip finishes rendering.

---

## ✨ Features

| Feature | Detail |
|---|---|
| 🔴 **Live stream clipping** | Monitors Twitch / YouTube live; auto-waits if offline |
| 🎞️ **VOD / file clipping** | Drop any `.mp4 .mkv .ts .flv .webm` and get clips instantly |
| 🧠 **AI moment detection** | Combines audio RMS peaks + word-per-second bursts + 150+ streamer hype words |
| 📝 **Animated captions** | ASS subtitles with per-word pop animation, Impact font, MrBeast colour palette |
| 📐 **9:16 output** | Blurred-background or fill-crop layout, 1080 × 1920, ready for Shorts/TikTok/Reels |
| 🖥️ **Local web UI** | Beautiful dark dashboard — no extra install required |
| ⚡ **GPU accelerated** | NVIDIA NVENC for encoding + CUDA for Whisper (CPU fallback included) |
| 🔒 **100% local & free by default** | Nothing leaves your machine unless optional Zernio posting is enabled |

---

## 📦 Installation

Choose the Windows experience you prefer:

| Windows option | Best for | Download / command |
|---|---|---|
| **Installer** | Start Menu, desktop shortcut, bundled runtime | [Download AutoClip-Setup.exe](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest) |
| **Portable** | Run from a folder or USB without installation | Download AutoClip-portable.zip from [Releases](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest), extract it, and run AutoClip.exe |
| **Manual terminal** | Developers and full control over Python/runtime | Follow the [Windows terminal guide](#-windows-native) below |

The installer and portable build open a terminal with the local server URL so you can see and
control the process. The manual method also prints the URL and supports the headless commands.

For the Rust launcher installer, use the separate [AutoClip Rust Edition repository](https://github.com/sifat-jaman-13/stream-clip-ai-rust).

Choose the guide that matches your operating system:

| Platform | Jump to |
|---|---|
| 🪟 Windows (native) | [Windows guide](#-windows-native) |
| 🍎 macOS | [macOS guide](#-macos) |
| 🐧 Linux | [Linux guide](#-linux) |
| 🐳 Docker | [Docker guide](#-docker) |

---

## 🪟 Windows (Native)

### Step 1 — Install FFmpeg

```powershell
winget install Gyan.FFmpeg
```

> Restart PowerShell after this so `ffmpeg` is on your `PATH`.  
> Verify: `ffmpeg -version`

### Step 2 — Install Python 3.10+

Download from [python.org](https://www.python.org/downloads/windows/) and tick **"Add Python to PATH"** during setup.

### Step 3 — Create a virtual environment (recommended)

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
```

> If you get a script execution error, run this once first:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### Step 4 — Install StreamClipAI

```powershell
# CPU only (from this checkout):
pip install -e .

# + Live stream support (Twitch / YouTube live):
pip install -e ".[live]"

# + NVIDIA GPU acceleration (fastest — requires CUDA-capable GPU):
pip install -e ".[gpu]"

# Everything at once (recommended):
pip install -e ".[all]"
```

### Step 5 — Run

```powershell
autoclip
```

A browser window opens automatically at `http://127.0.0.1:<port>/`.

  If the app opens but its buttons do not respond, disable your ad blocker for 127.0.0.1 / localhost. AutoClip is a local app and does not serve ads.

  New clips include a configurable “Subscribe for more clips” end card. On Windows, the optional soft female voice uses the built-in SAPI voice engine; the text remains available if no female voice is installed.

  **Headless (no UI):**
```powershell
autoclip live https://www.twitch.tv/your_channel
autoclip file C:\path\to\recording.mp4
```

---

## 🍎 macOS

### Step 1 — Install Homebrew (if not already)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### Step 2 — Install FFmpeg & Python

```bash
brew install ffmpeg python@3.11
```

Verify: `ffmpeg -version` and `python3 --version`

### Step 3 — Create a virtual environment (recommended)

```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 4 — Install StreamClipAI

```bash
# CPU only (works on Intel + Apple Silicon):
pip install -e .

# + Live stream support:
pip install -e ".[live]"

# Everything at once:
pip install -e ".[all]"
```

> **Apple Silicon (M1/M2/M3/M4):** this app currently uses the compatible CPU path (`faster-whisper`/CTranslate2 with INT8 fallback). The app does not currently select the experimental CTranslate2 MPS backend, so do not describe Apple Silicon as automatically using MPS. Use Python 3.11 or 3.12, native arm64 Python, FFmpeg, and `pip install -e ".[live]"`.

### Step 5 — Run

```bash
autoclip
```

Your default browser opens at `http://127.0.0.1:<port>/`.

**Headless:**
```bash
autoclip live https://www.twitch.tv/your_channel
autoclip file /path/to/recording.mp4
```

---

## 🐧 Linux

> Works on Ubuntu 22.04+, Debian 12+, Fedora 38+, Arch, and WSL2.

### Step 1 — Install FFmpeg & Python

**Ubuntu / Debian:**
```bash
sudo apt update
sudo apt install -y ffmpeg python3 python3-pip python3-venv
```

**Fedora / RHEL:**
```bash
sudo dnf install -y ffmpeg python3 python3-pip
```

**Arch Linux:**
```bash
sudo pacman -S ffmpeg python python-pip
```

Verify: `ffmpeg -version` and `python3 --version`

### Step 2 — Create a virtual environment (recommended)

```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 3 — Install StreamClipAI

```bash
# CPU only:
pip install -e .

# + Live stream support:
pip install -e ".[live]"

# + NVIDIA GPU (use a driver/runtime compatible with CUDA 12.x):
pip install -e ".[gpu]"

# Everything:
pip install -e ".[all]"
```

**NVIDIA GPU on Linux — compatible stack:**
```bash
# Recommended: Python 3.11/3.12, an NVIDIA driver supporting CUDA 12.x,
# and the project GPU extra. CTranslate2 provides the inference runtime.
nvidia-smi
pip install -e ".[all]"
```

The app uses CUDA `float16` first and falls back to CPU `int8` if CUDA cannot
load. See the [CTranslate2 installation guide](https://opennmt.net/CTranslate2/installation.html)
for current CUDA support details.

### Step 4 — Run

```bash
autoclip
```

> On a headless server without a browser, use headless mode and reach the UI over SSH port-forwarding:
> ```bash
> # On your local machine:
> ssh -L 8888:127.0.0.1:<port> user@your-server
> # Then open http://localhost:8888 in your local browser
> ```

**Headless:**
```bash
autoclip live https://www.twitch.tv/your_channel
autoclip file /path/to/recording.mp4
```

---

## 🐳 Docker

> No Python or FFmpeg installation needed — everything is bundled in the image.  
> CPU only (CUDA requires NVIDIA Container Toolkit — see note below).

### Quick start with Docker Compose (easiest)

```bash
# 1. Clone the repo (or just download docker-compose.yml):
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai

# 2. Build and start:
docker compose up --build

# 3. Open the web UI:
#    http://localhost:8080
```

Finished clips appear in `./out/` on your host machine.

### Docker run (manual)

```bash
# Build the image:
docker build -t stream-clip-ai .

# Run web UI:
docker run -it --rm \
  -p 8080:8080 \
  -v "$(pwd)/out:/data/out" \
  -v "$(pwd)/rec:/data/rec" \
  stream-clip-ai

# Headless — live stream:
docker run -it --rm \
  -v "$(pwd)/out:/data/out" \
  stream-clip-ai live https://www.twitch.tv/your_channel

# Headless — local file:
docker run -it --rm \
  -v "$(pwd)/out:/data/out" \
  -v "$(pwd)/my_vod.mp4:/data/rec/my_vod.mp4" \
  stream-clip-ai file /data/rec/my_vod.mp4
```

### NVIDIA GPU in Docker (Linux only)

```bash
# 1. Install NVIDIA Container Toolkit:
#    https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

# 2. Run with GPU passthrough:
docker run -it --rm --gpus all \
  -p 8080:8080 \
  -v "$(pwd)/out:/data/out" \
  stream-clip-ai
```

### Volume reference

| Host path | Container path | Purpose |
|---|---|---|
| `./out` | `/data/out` | Finished `.mp4` clips + `.txt` captions |
| `./rec` | `/data/rec` | Temporary live-stream recording segments |
| `./settings.json` | `/data/settings.json` | Persisted UI settings |
| `./custom_words.txt` | `/data/custom_words.txt` | Your streamer's custom hype words |

---

## 🖥️ Usage

### Web UI
```bash
autoclip           # native install
docker compose up  # docker
```
Opens a local dashboard. Paste a Twitch/YouTube URL or browse to a video file and hit **Start clipping**.

### Headless CLI
```bash
# Live stream:
autoclip live https://www.twitch.tv/channel_name
autoclip live https://www.youtube.com/watch?v=LIVE_ID

# Video file / VOD:
autoclip file /path/to/recording.mp4
```

---

## ⚙️ Configuration

All settings are persisted to `settings.json` automatically.

| Setting | Default | Description |
|---|---|---|
| `clips_per_chunk` | 2 | Clips extracted per recording segment |
| `chunk_min` | 3 | Live recording segment length (minutes) |
| `pre` / `post` | 20 / 15 s | Context before / after the peak moment |
| `min_score` | 1.5 | Hype-score threshold (higher = stricter) |
| `model` | `distil-large-v3` | Whisper model for speech recognition |
| `color` | Yellow | Caption highlight colour |
| `position` | Lower third | Caption vertical position |
| `layout` | Facecam + game (Twitch) | Video layout (facecam/game, blur bg, or fill-crop) |
| `font` | Impact | Caption font |

### Custom hype words
Edit `custom_words.txt` (auto-created on first run):
```
# word or phrase → default weight 2.0
# word or phrase | 3  → custom weight
no chance | 3
oh my days | 3
let him cook | 2.5
```
Changes apply to the next chunk — no restart needed.

---

## 📂 Output

```
out/
  streamname_143022_clip1.mp4   ← 9:16 clip (1080×1920)
  streamname_143022_clip1.txt   ← caption + hashtags ready to paste
```

---

## 🧩 How It Works

```
Stream / file
     │
     ▼ streamlink → ffmpeg (segments)
  .ts chunks (every N minutes for live)
     │
     ▼ faster-whisper (CUDA GPU / CPU)
  Word-level timestamps
     │
     ▼ AI Hype Scorer
  Audio RMS peaks + words/sec bursts + 150+ hype words + custom phrases
     │
     ▼ ffmpeg (NVENC / libx264) + ASS animated subtitles
  9:16 MP4 clips → out/
```

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| `ffmpeg not found` | Install FFmpeg and ensure it is on your `PATH` |
| `streamlink isn't installed` | `pip install streamlink` |
| `faster-whisper isn't installed` | `pip install --only-binary=:all: faster-whisper` |
| GPU / CUDA errors | Falls back to CPU automatically; NVIDIA users can run `pip install -e ".[all]"` |
| No clips generated | Lower the **Strictness** slider; check the Activity log |
| Docker: port already in use | Change `-p 8081:8080` and open `http://localhost:8081` |
| macOS: browser doesn't open | Copy the URL printed in the terminal and open it manually |
| WSL2: can't open browser | Use headless mode and access the printed port from Windows |

---

## 📋 Requirements

- Python **3.10+** (native installs) — not needed for Docker
- FFmpeg (on `PATH`) — bundled in Docker
- `numpy >= 1.24`
- `faster-whisper >= 1.0` / CTranslate2
- *(optional)* `streamlink` — for live Twitch / YouTube clipping
- *(optional)* `nvidia-cublas-cu12` — NVIDIA GPU acceleration

---

## 📜 License

**MIT** — free to use, modify and distribute. See [LICENSE](LICENSE).

---

## 📦 Editions

- [Main AutoClip repository and portable download](https://github.com/sifat-jaman-13/stream-clip-ai)
- [Rust Edition installer](https://github.com/sifat-jaman-13/stream-clip-ai-rust)

## 🙏 Credits

| Contributor | Role |
|---|---|
| **Sifat Jaman** | Creator & maintainer |
| **ChatGPT 5.6 Luna** (OpenAI) | AI product, coding, and documentation collaborator |
| **Claude** (Anthropic) | AI pair-programming assistant |
| **Antigravity** (Google DeepMind) | AI development environment and coding collaborator |

Follow Scarzero:

- [Facebook](https://www.facebook.com/ScarZero13)
- [YouTube](https://www.youtube.com/@scarzeroyt)
- [Twitch](https://www.twitch.tv/scarzero13)
- [TikTok](https://www.tiktok.com/@scarzero13)
- [Instagram](https://www.instagram.com/scarzero13/)

Built on top of amazing open-source projects:  
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) ·
[streamlink](https://github.com/streamlink/streamlink) ·
[FFmpeg](https://ffmpeg.org/)

---

*StreamClipAI is not affiliated with Twitch, YouTube, or any streaming platform.*
