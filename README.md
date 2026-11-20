# StreamSnip AI

StreamSnip AI turns Twitch and YouTube live streams or local video files into captioned short-form clips. Processing, transcription, rendering, settings, and generated clips stay local. Zernio is the supported publishing integration.

[![Windows installer](https://img.shields.io/badge/download-Windows%20setup-e94560?logo=windows)](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest/download/StreamSnipAI-Setup.exe)
[![Source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/sifat-jaman-13/stream-clip-ai)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Download for Windows

Download **StreamSnipAI-Setup.exe** from the [latest GitHub release](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest).

The installer packages only:

- a lightweight `StreamSnipAI.exe` launcher;
- the StreamSnip AI source modules;
- the icon and README;
- a setup script that opens a Windows terminal and installs runtime dependencies.

On first setup, the script:

1. detects Python;
2. installs Python 3.12 with `winget` when Python is missing;
3. upgrades `pip`;
4. installs the packages from `requirements.txt` plus Streamlink;
5. installs FFmpeg with `winget` when FFmpeg is missing;
6. launches `StreamSnipAI.exe`.

Internet access is required for the initial dependency and speech-model downloads. Keep the setup terminal open until installation finishes.

## Features

- Record supported Twitch and YouTube live streams.
- Wait for an offline stream and begin recording when it goes live.
- Process MP4, MKV, TS, FLV, and other FFmpeg-supported video files.
- Transcribe speech locally with faster-whisper.
- Choose built-in hook-word scoring or optional Ollama, Gemini, or Hugging Face analysis.
- Render 9:16, 16:9, 1:1, and 4:5 clips.
- Add karaoke or classic captions, streamer credit, end cards, and optional voice CTA.
- Preview, download, copy captions, reveal folders, select, publish, or delete clips.
- Publish manually or enable automatic posting through Zernio.

## Run from source

Install Python 3.10 or later and FFmpeg, then open PowerShell in the repository:

```powershell
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e ".[live]"
python autoclip.py
```

The web interface is available only on loopback at `http://127.0.0.1:8080` by default.

```bash
python autoclip.py live https://www.twitch.tv/your_channel
python autoclip.py live https://www.youtube.com/@channel
python autoclip.py file /path/to/recording.mp4
```

The package also provides `autoclip` and `streamclip` commands.

## Zernio publishing

Zernio is the only supported posting provider.

1. Create a Zernio API key.
2. Open **Settings -> Publishing**.
3. Select **Zernio hosted**.
4. Enter the API key and save.
5. Click **Save & identify channels**.
6. Select a connected Instagram or YouTube account.
7. Save the publishing settings.

Auto-post is off by default. When enabled, each newly rendered clip is submitted to the selected Zernio accounts.

Manual publishing is available for selected clips or all clips. Zernio's API access, account permissions, platform rules, quotas, and service limits apply.

Credentials are stored locally in `publishing.json` and `zernio.json`. These files are ignored by Git and must not be shared or committed.

## Docker

Docker Compose binds the app to the local computer only:

```bash
docker compose up --build
```

Open `http://127.0.0.1:8080`. Settings, recordings, and clips are stored in `./data`.

## Installer build

Windows packaging requires Python 3.14 for the build environment and Inno Setup 6:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

The build creates:

- `dist\StreamSnipAI\StreamSnipAI.exe`;
- `dist\installer\StreamSnipAI-Setup.exe`.

The installer intentionally does not require FFmpeg or Python packages to be embedded. It ships the app executable and source, then the setup terminal installs Python packages and FFmpeg on the target PC.

## Repository files

| File | Role |
|---|---|
| `autoclip.py` | Web UI, server, capture, clipping, transcription, settings, rendering, and publishing orchestration |
| `ai_highlights.py` | Ollama, Gemini, and Hugging Face highlight analysis |
| `zernio_poster.py` | Zernio publishing integration |
| `requirements.txt` | Runtime Python dependencies |
| `AutoClip.spec` | PyInstaller application build |
| `build_windows.ps1` | Windows app and installer build |
| `installer/AutoClip.iss` | Inno Setup installer definition |
| `installer/setup_windows.ps1` | Target-PC dependency setup launched by the installer |
| `docker-compose.yml`, `Dockerfile` | Docker deployment |
| `tests/test_regressions.py` | Regression tests |
| `assets/` | App icon and brand artwork |

## Privacy

Speech transcription and clip rendering run locally. Hosted Gemini or Hugging Face analysis sends transcript text to the selected service. Zernio publishing sends the selected video and caption data to Zernio.

API keys and settings are stored under the app data folder and are not exposed through the browser UI.

## License

StreamSnip AI is distributed under the MIT License. See [LICENSE](LICENSE).
