# 🎬 StreamClipAI

> **Free, local, AI-powered stream clipper.**  
> Twitch / YouTube live stream (or any video file) → ready-to-post **9:16 vertical clips** with animated MrBeast-style captions — no cloud, no subscription, no cost.

[![PyPI - Package Name](https://img.shields.io/badge/pypi-stream--clip--ai-blue?logo=pypi)](https://pypi.org/project/stream-clip-ai/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker)](https://hub.docker.com/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-lightgrey)]()

**Keywords:** `twitch auto clipper` · `youtube stream clipper` · `ai clip maker` · `stream to shorts` · `auto highlight detection` · `tiktok clip generator` · `reels maker` · `whisper captions`

### Optional Zernio posting

AutoClip can optionally upload each finished MP4 to Zernio and publish it to
connected Instagram and/or YouTube accounts. It is disabled by default.

Set these environment variables locally before starting AutoClip:

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
| 🔒 **100% local & free** | Nothing leaves your machine — no API keys needed |

---

## 📦 Installation

Choose the guide that matches your setup:

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
# CPU only (works on any PC):
pip install stream-clip-ai

# + Live stream support (Twitch / YouTube live):
pip install "stream-clip-ai[live]"

# + NVIDIA GPU acceleration (fastest — requires CUDA-capable GPU):
pip install "stream-clip-ai[gpu]"

# Everything at once (recommended):
pip install "stream-clip-ai[all]"
```

### Step 5 — Run

```powershell
autoclip
```

A browser window opens automatically at `http://127.0.0.1:<port>/`.

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
pip install stream-clip-ai

# + Live stream support:
pip install "stream-clip-ai[live]"

# Everything at once:
pip install "stream-clip-ai[all]"
```

> **Apple Silicon (M1/M2/M3):** GPU acceleration for Whisper uses the MPS backend automatically via `faster-whisper`. The `[gpu]` extra (CUDA) is not needed — CPU + MPS gives excellent speed.

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
pip install stream-clip-ai

# + Live stream support:
pip install "stream-clip-ai[live]"

# + NVIDIA GPU (requires CUDA 11.8+ drivers installed):
pip install "stream-clip-ai[gpu]"

# Everything:
pip install "stream-clip-ai[all]"
```

**NVIDIA GPU on Linux — extra step (if CUDA isn't set up):**
```bash
# Check your driver:
nvidia-smi

# Install CUDA toolkit (Ubuntu example):
sudo apt install -y nvidia-cuda-toolkit
```

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
| `chunk_min` | 5 | Live recording segment length (minutes) |
| `pre` / `post` | 20 / 15 s | Context before / after the peak moment |
| `min_score` | 2.0 | Hype-score threshold (higher = stricter) |
| `model` | `distil-large-v3` | Whisper model for speech recognition |
| `color` | Yellow | Caption highlight colour |
| `position` | Lower third | Caption vertical position |
| `layout` | Blur background | Video layout (blur bg or fill-crop) |
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
     ▼ faster-whisper (GPU / Apple MPS / CPU)
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
| GPU / CUDA errors | Falls back to CPU automatically; or: `pip install --only-binary=:all: nvidia-cublas-cu12` |
| No clips generated | Lower the **Strictness** slider; check the Activity log |
| Docker: port already in use | Change `-p 8081:8080` and open `http://localhost:8081` |
| macOS: browser doesn't open | Copy the URL printed in the terminal and open it manually |
| WSL2: can't open browser | Use headless mode and access the printed port from Windows |

---

## 📋 Requirements

- Python **3.10+** (native installs) — not needed for Docker
- FFmpeg (on `PATH`) — bundled in Docker
- `numpy >= 1.24`
- `faster-whisper >= 1.0`
- *(optional)* `streamlink` — for live Twitch / YouTube clipping
- *(optional)* `nvidia-cublas-cu12` — NVIDIA GPU acceleration

---

## 📜 License

**MIT** — free to use, modify and distribute. See [LICENSE](LICENSE).

---

## 🙏 Credits

| Contributor | Role |
|---|---|
| **Sifat Jaman** | Creator & maintainer |
| **Claude** (Anthropic) | AI pair-programming assistant |
| **Antigravity** (Google DeepMind) | AI development environment |

Built on top of amazing open-source projects:  
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) ·
[streamlink](https://github.com/streamlink/streamlink) ·
[FFmpeg](https://ffmpeg.org/)

---

*StreamClipAI is not affiliated with Twitch, YouTube, or any streaming platform.*
