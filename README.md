# 🎬 AutoClip

> **Free, local, fully-automated stream clipper.**  
> Twitch / YouTube live stream (or any video file) → ready-to-post **9:16 vertical clips** with animated MrBeast-style captions — no cloud, no subscription, no cost.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)]()

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
| 🔒 **100% local** | Nothing leaves your machine |

---

## 🚀 Quick Start

### 1 — Prerequisites

| Tool | Install |
|---|---|
| **Python 3.10+** | [python.org](https://www.python.org/downloads/) |
| **FFmpeg** | `winget install Gyan.FFmpeg` (Windows) · `brew install ffmpeg` (macOS) · `sudo apt install ffmpeg` (Linux) |

### 2 — Install AutoClip

**From PyPI (recommended):**
```bash
pip install autoclip
```

**With GPU support (NVIDIA CUDA — recommended for speed):**
```bash
pip install "autoclip[gpu]"
```

**With live-stream support (Twitch / YouTube live):**
```bash
pip install "autoclip[live]"
```

**Everything at once:**
```bash
pip install "autoclip[all]"
```

**From source:**
```bash
git clone https://github.com/sifat-jaman-13/autoclip.git
cd autoclip
pip install -e ".[all]"
```

> **Windows venv tip** (avoids permission issues):
> ```powershell
> py -3.14 -m venv venv
> .\venv\Scripts\Activate.ps1
> pip install "autoclip[all]"
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

### Headless — Live stream
```bash
autoclip live https://www.twitch.tv/your_channel
autoclip live https://www.youtube.com/watch?v=LIVE_VIDEO_ID
```

### Headless — Video file / VOD
```bash
autoclip file path/to/recording.mp4
```

---

## ⚙️ Configuration

All settings are adjusted live in the UI and persisted to `settings.json` next to the script (or in your working directory when installed).

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
  streamname_143022_clip1.mp4   ← 9:16 vertical clip
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
     ▼ Hype scorer
  RMS audio peaks + words/sec + hype-word hits + custom phrases
     │
     ▼ ffmpeg (NVENC/x264) + ASS subtitles
  9:16 MP4 clips → out/
```

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| `ffmpeg not found` | Install FFmpeg and ensure it is on your `PATH` |
| `streamlink isn't installed` | `pip install streamlink` |
| `faster-whisper isn't installed` | `pip install --only-binary=:all: faster-whisper` |
| GPU/CUDA errors | AutoClip automatically falls back to CPU — or reinstall: `pip install --only-binary=:all: nvidia-cublas-cu12` |
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

*AutoClip is not affiliated with Twitch, YouTube, or any streaming platform.*
