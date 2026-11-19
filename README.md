# 🎬 StreamClipAI

> **Free, local, AI-powered stream clipper.**  
> Twitch / YouTube live stream (or any video file) → ready-to-post **9:16 vertical clips** with animated MrBeast-style captions — no cloud, no subscription, no cost.

[![PyPI - Package Name](https://img.shields.io/badge/pypi-stream--clip--ai-blue?logo=pypi)](https://pypi.org/project/stream-clip-ai/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)]()

**Keywords:** `twitch auto clipper` · `youtube stream clipper` · `ai clip maker` · `stream to shorts` · `auto highlight detection` · `tiktok clip generator` · `reels maker` · `whisper captions`

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

## 🚀 Quick Start

### 1 — Prerequisites

| Tool | Install |
|---|---|
| **Python 3.10+** | [python.org](https://www.python.org/downloads/) |
| **FFmpeg** | `winget install Gyan.FFmpeg` (Windows) · `brew install ffmpeg` (macOS) · `sudo apt install ffmpeg` (Linux) |

### 2 — Install StreamClipAI

**From PyPI (recommended):**
```bash
pip install stream-clip-ai
```

**With GPU support (NVIDIA CUDA — fastest transcription):**
```bash
pip install "stream-clip-ai[gpu]"
```

**With live-stream support (Twitch / YouTube live):**
```bash
pip install "stream-clip-ai[live]"
```

**Everything at once (recommended for streamers):**
```bash
pip install "stream-clip-ai[all]"
```

**From source:**
```bash
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai
pip install -e ".[all]"
```

> **Windows venv tip** (avoids permission issues):
> ```powershell
> py -3.11 -m venv venv
> .\venv\Scripts\Activate.ps1
> pip install "stream-clip-ai[all]"
> ```

---

## 🖥️ Usage

### Web UI (recommended)
```bash
autoclip
# or
python -m autoclip
```
Opens a local web dashboard at `http://127.0.0.1:<port>/` automatically.  
Paste a stream URL or browse to a video file and hit **Start clipping**.

### Headless — Live stream (Twitch / YouTube)
```bash
autoclip live https://www.twitch.tv/your_channel
autoclip live https://www.youtube.com/watch?v=LIVE_VIDEO_ID
```

### Headless — Video file / VOD
```bash
autoclip file path/to/recording.mp4
autoclip file path/to/vod.mkv
```

---

## ⚙️ Configuration

All settings are adjusted live in the UI and persisted to `settings.json` in your working directory.

| Setting | Default | Description |
|---|---|---|
| `clips_per_chunk` | 2 | Number of clips extracted per recording segment |
| `chunk_min` | 5 | Live recording segment length (minutes) |
| `pre` / `post` | 20 / 15 s | Seconds of context before / after the peak moment |
| `min_score` | 2.0 | Hype-score threshold (higher = stricter, fewer clips) |
| `model` | `distil-large-v3` | Whisper model for speech recognition |
| `color` | Yellow | Caption highlight colour |
| `position` | Lower third | Caption vertical position |
| `layout` | Blur background | Video layout (blurred bg or fill-crop) |
| `font` | Impact | Caption font (any font installed on your system) |

### Custom hype words
Edit `custom_words.txt` (auto-created on first run) to add your streamer's catchphrases:
```
# word or phrase → weight 2.0 by default
# word or phrase | 3  → custom weight
no chance | 3
oh my days | 3
let him cook | 2.5
```
Changes are picked up **without restarting** — mid-stream edits work.

---

## 📂 Output

```
out/
  streamname_143022_clip1.mp4   ← 9:16 vertical clip (1080×1920)
  streamname_143022_clip1.txt   ← caption + hashtags to paste
```

Clips folder opens automatically from the **Clips folder** button in the UI.

---

## 🧩 How It Works

```
Stream / file
     │
     ▼ (streamlink → ffmpeg segments)
  .ts chunks (every N minutes for live)
     │
     ▼ faster-whisper (GPU/CPU)
  Word-level timestamps
     │
     ▼ AI Hype Scorer
  Audio RMS peaks + words/sec bursts + 150+ hype-word hits + custom phrases
     │
     ▼ ffmpeg (NVENC/x264) + ASS animated subtitles
  9:16 MP4 clips → out/
```

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| `ffmpeg not found` | Install FFmpeg and ensure it is on your `PATH` |
| `streamlink isn't installed` | `pip install streamlink` |
| `faster-whisper isn't installed` | `pip install --only-binary=:all: faster-whisper` |
| GPU/CUDA errors | StreamClipAI automatically falls back to CPU; or reinstall: `pip install --only-binary=:all: nvidia-cublas-cu12` |
| No clips generated | Lower the **Strictness** slider in the UI; check the Activity log |

---

## 📋 Requirements

- Python **3.10 or newer**
- FFmpeg (must be on `PATH`)
- `numpy >= 1.24`
- `faster-whisper >= 1.0`
- *(optional)* `streamlink` — for live Twitch / YouTube clipping
- *(optional)* `nvidia-cublas-cu12` — for GPU-accelerated transcription on NVIDIA GPUs

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
