# StreamSnip AI

**StreamSnip AI** turns Twitch and YouTube live streams, or video files on your computer, into short, captioned clips. It records and processes video locally, transcribes speech with faster-whisper, finds candidate moments, renders clips with FFmpeg, and can optionally publish through Zernio, Postiz, or Mixpost.

[![Windows installer](https://img.shields.io/badge/download-Windows%20setup-e94560?logo=windows)](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest/download/StreamSnipAI-Setup.exe)
[![Source](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/sifat-jaman-13/stream-clip-ai)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Download for Windows

The [GitHub Releases page](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest) provides one packaged Windows download: **StreamSnipAI-Setup.exe**. Run the installer and follow its prompts. It installs and launches the actual StreamSnip AI app executable directly; no separate launcher or system Python setup is needed. An internet connection is required the first time the selected speech model is downloaded.

The shortcut starts the app in a terminal and opens its local web interface in an app-style browser window. Keep the terminal open while StreamSnip AI is running. Use **Quit** in the app to stop it cleanly; this also stops an active recording. Closing only the browser window does not stop the server.

The installer can use an existing supported Python 3.10–3.14 installation. If none is found, it installs Python 3.12 with `winget`. Setup installs the Python packages and downloads the default `distil-large-v3` speech model. Allow about **4–6 GB of free space** for the initial setup; other speech models and recordings need additional space. FFmpeg is bundled in installer builds when it is available on the build computer. If the installed app reports that FFmpeg is missing, install it separately and add it to `PATH`.

## What it does

- Records Twitch and YouTube live streams. If a stream is offline, it can wait and start when the stream goes live.
- Makes clips from local video files, including MP4, MKV, TS, FLV, and WebM files supported by FFmpeg.
- Transcribes speech locally with faster-whisper. Speech model choices include `distil-large-v3`, `large-v3-turbo`, `medium`, `large-v3`, `small`, and `base`.
- Finds moments using built-in or custom hook words and audio/speech scoring, or optional Ollama, Gemini, and hosted Hugging Face analysis.
- Analyzes long transcripts in windows. When Gemini is rate-limited, over quota, or temporarily unavailable, it tries other available Gemini models, then can switch remaining windows to Ollama. If AI analysis cannot be used, the app falls back to local hook-word and audio scoring.
- Renders portrait 9:16, landscape 16:9, square 1:1, or portrait 4:5 MP4 clips with Karaoke or Classic captions and six caption styles.
- Provides facecam-plus-game, blurred-background, center-fill, and selected-crop layouts.
- Adds a caption text file, optional streamer credit, and a configurable end-card message. Windows can also add a spoken CTA when its voice support is available.
- Includes a clip library with preview, download, caption copy, folder reveal, selection, publishing, and delete controls.
- Supports manual publishing and optional auto-posting through Zernio, Postiz, or Mixpost.

## First run

1. Install the app using **StreamSnipAI-Setup.exe** from the [latest release](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest).
2. Launch **StreamSnip AI** from the Start Menu or desktop shortcut. Keep its terminal open.
3. To clip a live stream, select **Live stream** and paste a Twitch or YouTube live URL. To clip a recording, select **Video file / VOD** and browse to a video file on your computer.
4. Choose a highlight engine, output format, caption and clip settings as desired. Defaults work without an AI key or publishing account.
5. Select **Start recording & clipping** for a stream or **Make clips from this file** for a video. Progress and errors appear in **Activity**; finished clips appear in the library.

Use **Settings → Storage folders** to choose where recordings and clips are saved. The default folders are `rec` and `out` under the app's data folder. For a source checkout, that is the project folder; for the Windows installer, it is the installed app folder. The app recreates the default folders if they are missing. Changing storage folders takes effect after clipping is stopped.

Each finished clip is saved as an `.mp4` and a matching `.txt` file containing suggested caption text and hashtags. Live recordings are saved in the recording folder. You can enable deletion of a raw recording after processing in **Output**.

## Settings and defaults

| Setting | Default | Details |
|---|---:|---|
| Minimum viral score | 70 | Raise it to keep fewer, stronger moments; lower it to include more candidates. |
| Clips per chunk | 2 | Set to 0 for no per-chunk limit. |
| Live chunk length | 3 minutes | Each captured segment is processed separately. |
| Before / after the peak | 20 / 15 seconds | The app keeps context around each selected moment and caps a clip at 60 seconds. |
| Speech model | `distil-large-v3` | Other available models trade speed, resource use, and transcription accuracy. |
| Processing hardware | Automatic | Uses CUDA for speech and NVENC for video whenever supported NVIDIA hardware and FFmpeg support are available. Uses INT8/software CPU processing only if no supported GPU is detected; GPU startup failures are reported instead of silently moving speech work to CPU. |
| Live capture bitrate target | 6,000 kbps | This is the lowest allowed setting. Capture prefers 1080p60, then 1080p, 720p60, 720p, and the best available stream. A lower-resolution source cannot gain real detail from upscaling. |
| Output format | 9:16 portrait | Other options are 16:9, 1:1, and 4:5. |
| Auto-post | Off | Must be enabled separately in the selected publishing provider's settings. |

Settings can also be checked and edited in the app. Update controls check the app's GitHub release and runtime components; the app update button opens the release page and does not replace the installed application automatically.

## Choose how highlights are selected

The **Choose your highlight engine** panel is near the top of the app. It controls moment selection, not speech transcription. Whisper creates the transcript separately. **Hook words and Ollama are local and do not use hosted AI quota. Gemini and Hugging Face send transcript windows to hosted services and can consume API quota or provider credits.** Gemini can try multiple models before Ollama fallback; those hosted attempts still count against the provider's limits. Activity reports which provider and model handled each transcript window, where it ran, model retries, and fallback behavior.

### Built-in and custom hook words

This is the default and works offline without an AI service. The app combines its default hook words with audio energy and speech-rate scoring. Open **Hype words** to review, add, or remove phrases for your language and community. Changes are saved locally and apply to subsequent chunks.

### Ollama on your computer

Ollama runs a model locally. Install Ollama from [ollama.com/download](https://ollama.com/download), open a terminal, and download a model. For example:

~~~powershell
ollama pull qwen3:4b
~~~

Browse the [Ollama model library](https://ollama.com/library) to compare available models and their memory needs. In StreamSnip AI, choose **Ollama local AI**, keep the standard address `http://127.0.0.1:11434`, and click **Detect models**. Select an installed model and save. Ollama must be installed, running, and have at least one model downloaded. You can check installed models with `ollama list`.

For Docker, use `http://host.docker.internal:11434` as the Ollama address; inside a container, `127.0.0.1` points to the container itself. The Compose configuration supplies this address by default.

### Gemini API

1. Create an API key in [Google AI Studio](https://aistudio.google.com/) and review Google's [Gemini API setup guide](https://ai.google.dev/gemini-api/docs/get-started).
2. In StreamSnip AI, choose **Gemini API**, enter the key, and save the AI settings. The key is stored in the local app data folder and is not sent to the browser UI.
3. Process a short recording and check **Activity** for the Gemini model and request status.

The **Preferred Gemini model** field lets you choose the first model to try. The default is `gemini-3.8-flash`; available models depend on the API key, and StreamSnip checks the key's available models for fallback.

Google offers a free tier for eligible models, but model availability and quotas vary by account and can change. See Google's [current pricing and free-tier information](https://ai.google.dev/gemini-api/docs/pricing). StreamSnip AI can show quota or rate-limit errors returned by Google; it cannot read your remaining quota before a request. When requests hit quota/rate limits or temporary model/API failures, StreamSnip AI tries other Gemini models available to the key before switching the remaining transcript windows to Ollama. Keep Ollama running and a model selected to use that fallback. Without a working Ollama fallback, the app uses local hook-word and audio scoring.

### Hugging Face hosted models

Choose **Hugging Face**, enter a model ID and a token with access to [Inference Providers](https://huggingface.co/docs/inference-providers/index), then save AI settings. This sends timestamped transcript windows to hosted inference and may use provider credits or limits. StreamSnip also passes the saved token to Hugging Face Hub when faster-whisper downloads its speech model; downloading the public speech model is separate from hosted AI inference. You do not need to paste the token into a terminal or send it to support. The token is stored in local app settings and is never written to Activity. To avoid hosted usage entirely, choose **Hook words** or **Ollama**.

## Publishing clips

Publishing is optional. Connect social accounts in your selected provider first; StreamSnip lists Instagram, YouTube, Facebook Pages, and TikTok accounts reported by Postiz. In **Settings → Publishing**, select Postiz, enter your self-hosted instance URL and API key, click **Save & identify channels**, select accounts, and save again. **Auto-post is off by default.** The no-subscription route is self-hosted Postiz: the software is free, but your own computer/server and internet connection must stay available. Your social accounts still have to meet each platform's developer/API requirements.

### Zernio

1. Create a key from the [Zernio API keys page](https://zernio.com/dashboard/api-keys); see its [quickstart](https://docs.zernio.com/quickstart).
2. Choose **Zernio** and enter the key. The app uses Zernio's hosted API; no base URL or workspace is needed.
3. Click **Save & identify channels**, select connected Instagram and/or YouTube accounts, and save those selections.

### Self-hosted Postiz (no scheduler subscription)

1. Install Postiz's free open-source edition on your own computer/server using its [self-hosting guide](https://docs.postiz.com/). This avoids a Postiz Cloud subscription, but you maintain the server, updates, backups, and social-network developer apps.
2. Connect Instagram, YouTube, Facebook Page, and/or TikTok in Postiz. Create a key under **Settings → Developers → Public API**; see the [Postiz Public API guide](https://docs.postiz.com/public-api/introduction).
3. Choose **Postiz** in StreamSnip. Enter your instance URL and API key. A self-hosted URL is required; StreamSnip will not default to paid Postiz Cloud. Do not append `/public/v1`; the app adds the API paths.
4. Select the channels and save. For TikTok, also tick the direct-publishing confirmation. TikTok requires Postiz and its uploaded video media to be reachable over public HTTPS; TikTok may restrict unaudited apps to private posts and daily limits. Check the [Postiz TikTok self-hosting requirements](https://docs.postiz.com/self-host/providers/tiktok) before enabling it.

### Mixpost Cloud or self-hosted

1. Mixpost Lite is free and self-hostable, but currently supports Facebook Pages, X, and Mastodon. Its official plan comparison lists Instagram, YouTube, and TikTok under paid Pro/Enterprise features. See [Mixpost's feature/pricing page](https://mixpost.app/pricing) before choosing it. Mixpost Cloud is hosted; its pricing can change.
2. The API required by this StreamSnip connector and Mixpost's Instagram, YouTube, and TikTok integrations are plan-limited. Check [Mixpost's current feature and pricing list](https://mixpost.app/pricing) before using it. Mixpost is not the free four-platform route; use self-hosted Postiz for that.

### Posting behavior and limits

- **Auto-post** is off by default. When enabled, newly rendered clips are submitted to the saved accounts for the selected provider.
- StreamSnip does not charge for publishing. Postiz Cloud, Zernio, and Mixpost paid editions may charge separately. For the free route, select **Postiz** and enter your own self-hosted instance URL; a blank URL is rejected to prevent accidentally using Postiz Cloud.
- Manual publishing is available for one or more selected clips, or all clips. Upload progress and failures appear in **Activity**.
- The schedule delay is configured in minutes. YouTube visibility is sent by the Zernio and Postiz integrations; provider and platform rules still apply.
- Credentials are saved locally in `publishing.json` (Zernio settings may also be kept in `zernio.json`). Do not share these files or commit API keys.
- API permissions, platform limits, provider plans, and quotas apply. Some Mixpost installations require chunked uploads for larger videos; this integration uses a normal multipart upload and may not work with those installations.

## Install from source

### Windows PowerShell

Install [Python 3.10 or later](https://www.python.org/downloads/) and [FFmpeg](https://www.gyan.dev/ffmpeg/builds/) first, then run:

~~~powershell
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[live]"
~~~

For NVIDIA CUDA speech acceleration, install the optional CUDA libraries:

~~~powershell
pip install nvidia-cublas-cu12
~~~

If PowerShell blocks environment activation, either run `venv\Scripts\python.exe` directly or allow local activation scripts for your user:

~~~powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
~~~

### macOS and Linux

Install Python 3.10 or later and FFmpeg with your system package manager, then:

~~~bash
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[live]"
~~~

On Apple Silicon, use native arm64 Python and the CPU/INT8 processing option. The project does not provide an automatic CTranslate2 MPS backend.

## Run from source

Start the browser app, which binds to loopback and opens a local browser window:

~~~bash
python autoclip.py
~~~

The package also installs the `autoclip` command. For headless processing without the web UI, use:

~~~bash
autoclip live https://www.twitch.tv/your_channel
autoclip live https://www.youtube.com/@channel
autoclip file /path/to/recording.mp4
~~~

The equivalent Python commands are `python autoclip.py live URL` and `python autoclip.py file PATH`. Live capture requires Streamlink. All modes require FFmpeg. Keep the terminal open while a headless job runs; press Ctrl+C to stop it.

## Docker

Docker Compose runs the web app at [http://localhost:8080](http://localhost:8080) and binds the port to this computer only. It stores app settings, hook words, recordings, and clips under `./data` on the host. Docker Compose does not pass through a GPU, so expect speech processing to use the CPU.

~~~bash
docker compose up --build
~~~

To process a local file from a terminal, mount it into the existing `/data` volume and run file mode:

~~~bash
docker compose run --rm -v "$PWD/my_vod.mp4:/data/rec/my_vod.mp4:ro" streamclipai file /data/rec/my_vod.mp4
~~~

The file appears read-only inside the container; results are saved under `./data/out`. For Ollama installed on the host, use `http://host.docker.internal:11434` in AI settings. The Compose file passes that address into the app. Do not expose the container port publicly without adding your own access control.

## Troubleshooting

| Problem | What to check |
|---|---|
| The installer says an application file is missing | Uninstall StreamSnip AI, then download and reinstall the latest `StreamSnipAI-Setup.exe` from [Releases](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest). |
| The app reports that it is already running | Check for the existing StreamSnip AI terminal/app window and choose **Quit**, or stop that process before launching another copy. |
| The browser UI does not open | Copy the local URL printed in the terminal into a browser. The app-style window uses Edge or Chrome when available. |
| UI buttons do not respond | Disable extensions such as ad blockers for `127.0.0.1` and `localhost`. |
| No stream is found | Check the Twitch/YouTube URL and network connection. Offline streams are polled while the app waits. |
| No clips are produced | Inspect **Activity** for transcription errors, check the speech model and FFmpeg, and lower the minimum viral score if needed. |
| Whisper reports that `model.bin` is missing | The local model cache was interrupted or damaged. The app clears only that model's broken Hugging Face cache and retries its download; allow the download to finish before closing the app. |
| A clip says it is in use | Check **Activity** for the process name, path, and PID Windows identified. Use its **Stop process** button only after saving work in that app; if Windows cannot identify the holder, close the video player or Explorer preview pane and retry. |
| Transcription is slow or CUDA fails | Check that the NVIDIA GPU and driver are available and that the installed runtime includes CUDA support. Activity shows GPU initialization errors; when a supported CUDA GPU is detected, speech processing does not silently switch to CPU. |
| FFmpeg or FFprobe is missing | Install FFmpeg and add its `bin` folder to `PATH`, then restart StreamSnip AI. |
| Ollama models are not detected | Start Ollama, download a model with `ollama pull MODEL_NAME`, confirm it appears in `ollama list`, then click **Detect models** again. |
| Gemini reports quota/rate limits | Check the project's current Google AI Studio quota. Keep Ollama running with a model selected for automatic fallback. |
| A publisher cannot find a channel | Connect the account in the provider dashboard, verify the API key and permissions, then click **Save & identify channels** again. |
| Publishing fails | Read the provider error in **Activity**. Check provider status, credentials, channel access, schedule, file size, and plan limits. |

## Local files and privacy

The app UI runs on this computer and, by default, listens only on `127.0.0.1`. Speech transcription, clip rendering, and built-in hook-word scoring run locally. Gemini and Hugging Face hosted highlight analysis send timestamped transcript text to their selected service. Ollama analysis runs on the configured Ollama machine. Publishing sends selected video files and captions to the configured publisher. API keys and settings are stored in local files under the app data folder, not inside the web page; protect the Windows account and local files that contain those credentials.

Settings, AI provider credentials, publishing credentials, and hook words are stored in files such as `settings.json`, `ai_settings.json`, `publishing.json`, `zernio.json`, and `custom_words.txt`. These local runtime files are ignored by Git. Source installs keep them beside the project; the Windows installer keeps them under its installation folder. Clips and recordings use the paths selected under **Settings → Storage folders**.

## Build the Windows installer

The repository's Windows build script creates the self-contained PyInstaller app and `dist\installer\StreamSnipAI-Setup.exe`. It requires Python 3.14 for the build environment and Inno Setup 6. FFmpeg and FFprobe are included when found on the build computer; otherwise, users must install them separately.

~~~powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
~~~

The installer contains the actual application executable and its bundled runtime files. Start Menu and optional desktop shortcuts open `StreamSnipAI.exe` directly. The only packaged Windows download published on GitHub Releases is `StreamSnipAI-Setup.exe`.

## Project files

| File | Role |
|---|---|
| `autoclip.py` | Local web UI and server, capture and clipping engine, transcription, settings, rendering, and orchestration. |
| `ai_highlights.py` | Transcript analysis through Ollama, Gemini, or Hugging Face hosted inference. |
| `zernio_poster.py` | Zernio publishing integration. |
| `selfhost_publishers.py` | Postiz and Mixpost publishing integrations. |
| `AutoClip.spec`, `build_windows.ps1`, `installer/AutoClip.iss` | Self-contained Windows app build and Setup installer definition. |
| `build_windows.ps1`, `AutoClip.spec` | Windows application build configuration. |
| `docker-compose.yml`, `Dockerfile` | Local Docker deployment. |
| `tests/test_regressions.py` | Automated regression coverage for the application. |
| `assets/` | App icon and brand artwork. |

## Credits

Created by **Sifat Jaman / ScarZero**.

- [Scar Clip Farm on YouTube](https://youtube.com/@scarclipfarm)
- [Scarzero on YouTube](https://www.youtube.com/@scarzeroyt)
- [Scarzero13 on Twitch](https://www.twitch.tv/scarzero13)
- [Scarzero13 on TikTok](https://www.tiktok.com/@scarzero13)
- [Scarzero13 on Instagram](https://www.instagram.com/scarzero13/)
- [ScarZero13 on Facebook](https://www.facebook.com/ScarZero13)

## License

StreamSnip AI is distributed under the MIT License. See [LICENSE](LICENSE).
