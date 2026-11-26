<div align="center">

<img src="assets/streamsnipai-banner.svg" width="100%" alt="StreamSnip AI — Find the moment. Make it a clip.">

# StreamSnip AI

### The native Windows studio for live capture, highlight clipping, and publishing.

<p>
  <a href="https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest"><img src="https://img.shields.io/github/v/release/sifat-jaman-13/stream-clip-ai?display_name=tag&style=flat-square&label=latest%20release" alt="Latest release"></a>
  <a href="https://github.com/sifat-jaman-13/stream-clip-ai/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/sifat-jaman-13/stream-clip-ai/tests.yml?branch=master&style=flat-square&label=tests" alt="Tests"></a>
  <a href="https://github.com/sifat-jaman-13/stream-clip-ai/actions/workflows/build-installer.yml"><img src="https://img.shields.io/github/actions/workflow/status/sifat-jaman-13/stream-clip-ai/build-installer.yml?branch=master&style=flat-square&label=Windows%20installer" alt="Windows installer"></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-2878d0?style=flat-square&logo=windows" alt="Windows 10 and 11">
  <img src="https://img.shields.io/badge/interface-WinUI%203-236b78?style=flat-square" alt="WinUI 3">
  <img src="https://img.shields.io/badge/license-proprietary%20non--commercial-c47d46?style=flat-square" alt="Proprietary non-commercial licence">
</p>

[**Download for Windows**](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest) · [Project website](https://sifat-jaman-13.github.io/stream-clip-ai/) · [Issues & support](https://github.com/sifat-jaman-13/stream-clip-ai/issues)

</div>

---

## The whole clipping session, in one desktop app

StreamSnip AI turns supported live streams, recorded VODs, and local videos into review-ready short-form clips. Capture a source, transcribe speech, rank promising moments, shape the frame, render captions, review the result, and publish through your connected Zernio destinations.

The installed application is a **native WinUI 3 Windows desktop app** backed by a supervised local Python media engine. Your recordings and rendered files stay on your PC. Hosted AI services are optional and receive transcript text only when you choose and configure them.


## From stream to short

~~~mermaid
flowchart LR
    A["Twitch / YouTube live"] --> C["Capture"]
    B["Recorded VOD / local video"] --> C
    C --> D["Transcribe"]
    D --> E["Score highlights"]
    E --> F["Frame and render"]
    F --> G["Review clip + metadata"]
    G --> H["Publish through Zernio"]
    H --> I["Facebook"]
    H --> J["Instagram"]
    H --> K["YouTube"]
~~~

## The workspace

### Live Studio

Prepare the source, capture settings, AI provider, transcription model, and captions before starting. Opening Live Studio does not start a recording; capture begins only after you explicitly start it. The screenshots below focus on stable, non-error workspace views.

### Creator monitoring

Save creators independently and keep their monitoring status, live recordings, and recorded-VOD work organised. Each creator has separate Live and Recorded VOD folders, rather than mixing every source into one queue.


### Clip library

Review the rendered video and its matching post metadata. Keep work that is still being reviewed separate from clips confirmed as published. Preview, download, copy metadata, delete individual items, or manage selections in bulk.


### Publishing

Connect one or more Zernio API keys, discover the social accounts available to each connection, and choose destinations for an individual clip or batch. StreamSnip checks results per destination; partial success and failures stay visible.


## Capabilities

| Area | What it does |
| --- | --- |
| Live capture | Capture supported Twitch and YouTube live sources with explicit start/stop controls. |
| Creator monitoring | Monitor saved creators independently and organise each creator's Live and Recorded VOD folders. |
| VOD and local video | Process recorded VODs and supported local video files through the same clipping workflow. |
| Transcription | Use local Faster-Whisper or configure a compatible command-line transcriber. |
| Highlight analysis | Score transcript windows with built-in Hook Words, local Ollama, Gemini, Hugging Face, or a custom OpenAI-compatible endpoint. |
| Facecam framing | Use local multi-frame facecam detection with OpenCV and YuNet; inspect and adjust the facecam and gameplay regions before rendering. |
| Output formats | Render portrait 9:16, landscape 16:9, square 1:1, and 4:5 clips. |
| Captions | Configure animated word-level captions, placement, creator credit, styles, and optional profanity handling. |
| Metadata | Generate transcript-grounded titles, descriptions, hashtags, and matching text sidecars. |
| Publishing | Publish through configured Zernio connections to Facebook, Instagram, and YouTube. |
| Clip lifecycle | Keep active clips and confirmed published records in separate areas with individual and bulk management. |

Highlight scores are estimates, not guarantees of views, reach, or engagement. Always review the video and its generated metadata before publishing.

## Installation

1. Open [GitHub Releases](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest).
2. Download **StreamSnipAI-Native-Setup.exe** and its matching SHA-256 file.
3. Verify the checksum (PowerShell example below).
4. Run the installer. Setup checks the required runtime and media dependencies, then reuses valid components and installs only what is missing or incompatible.
5. Launch StreamSnip AI from the Start menu or desktop shortcut.

~~~powershell
(Get-FileHash .\StreamSnipAI-Native-Setup.exe -Algorithm SHA256).Hash.ToLowerInvariant()
Get-Content .\StreamSnipAI-Native-Setup.exe.sha256
~~~

The two hashes must match.

### What the installer prepares

The installer deploys the self-contained WinUI 3 desktop application and the local Python engine source. On first install or repair, setup checks for:

- A compatible 64-bit Python runtime and an isolated app-managed environment.
- Python 3.15 uses a dedicated dependency profile: it omits the optional ONNX Runtime VAD dependency, then installs Faster-Whisper without that optional VAD extra. This does not affect StreamSnip's separate OpenCV/YuNet facecam detector.
- FFmpeg and FFprobe.
- The required Python packages and Windows-compatible wheels.
- The configured Faster-Whisper speech model files.
- The bundled face-detection model used by local facecam detection.

Existing compatible dependencies and model files are reused. Missing or incompatible components are installed or repaired. Setup does not replace system Python or change the global PATH.

An internet connection is required when setup needs to download packages or model files. A Hugging Face token is optional and may improve model-download reliability for gated or rate-limited downloads.

Setup diagnostics are written to:

~~~text
%LOCALAPPDATA%\StreamSnip AI\setup.log
~~~

## Configure your providers

### Transcription and highlight analysis

Local capture, local transcription, and rendering do not require a hosted AI API key. Choose the analysis method that fits your machine and workflow:

| Provider | Role | Where it runs |
| --- | --- | --- |
| Faster-Whisper | Speech-to-text | Locally |
| Custom transcriber | Bring your own executable or script that returns timestamped output | Locally |
| Built-in Hook Words | Transcript-based highlight scoring | Locally |
| Ollama | Local language-model analysis | Your configured Ollama service |
| Gemini / Hugging Face / custom endpoint | Optional hosted analysis and metadata | Provider service you configure |

A hosted provider receives transcript text when you select it for the requested task. Review the provider's privacy, data handling, and retention terms before connecting it.

### Zernio publishing

The current direct Zernio publishing integration supports:

- **Facebook**
- **Instagram**
- **YouTube**

TikTok is not a supported destination in the current integration.

Add your Zernio API key or keys in Publishing. StreamSnip discovers the accounts returned by each connection and lets you enable or disable accounts individually.

Zernio and the connected social platforms control account availability, request budgets, and posting quotas. Different API keys may still belong to one Zernio billing workspace and share its request allowance; another key does not guarantee another quota. Only destinations confirmed as successful are recorded as published. Retries reuse the same idempotency key for the same logical post to reduce duplicate-post risk.

## Local-first by design

| Operation | Execution |
| --- | --- |
| Capture and stream handling | Local Windows PC |
| Video files and recordings | Local Windows PC |
| Faster-Whisper transcription | Local Windows PC |
| Facecam detection and crop analysis | Local Windows PC |
| FFmpeg rendering and captions | Local Windows PC |
| Hook Words | Local Windows PC |
| Ollama | Local service you configure |
| Hosted AI analysis | Selected provider receives transcript text for that task |
| Zernio publishing | Selected media and post details are sent to Zernio and selected destinations |

The local FastAPI engine is bound to loopback and uses a per-process session token for state-changing requests. **Do not expose the engine API to an untrusted network or the public internet.**

Credentials are stored in local application settings and are not returned by the browser-facing status API. Never commit environment files, API keys, social tokens, cookies, or local browser profiles.

## Build from source

### Prerequisites

- Windows 10/11 x64.
- Python 3.10 or newer (the installer/build scripts validate compatibility).
- Node.js 22 and npm for the dashboard bundle.
- .NET 10 SDK for the WinUI 3 desktop application.
- Inno Setup 6 for the per-user Windows installer.
- FFmpeg for local media processing and tests that exercise media operations.

### Development setup

~~~powershell
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai

python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,live]"
~~~

Build the dashboard:

~~~powershell
cd dashboard
npm ci
npm run lint
npm run build
cd ..
~~~

Publish and package the native Windows app:

~~~powershell
.\build_native_installer.ps1
~~~

The script builds the dashboard, publishes the self-contained WinUI 3 application for win-x64, compiles the Inno Setup 6 installer, and generates a matching SHA-256 sidecar under dist\installer\.

### Tests

~~~powershell
python -m pytest -q
~~~

For a focused test file:

~~~powershell
python -m pytest tests\test_native_installer_setup.py -q
~~~

## Repository map

~~~text
.
├── desktop/                  Native WinUI 3 desktop application
├── dashboard/                React + TypeScript engine dashboard bundle
├── installer/                Inno Setup script and Windows setup/repair scripts
├── docs/                     GitHub Pages site and product screenshots
├── licenses/                 Third-party notices
├── models/                   Bundled face-detection model asset
├── tests/                    Python regression and integration tests
├── autoclip.py               Capture, processing, rendering, and local API host
├── api_server.py             Local FastAPI engine integration
├── ai_highlights.py          AI/highlight analysis providers
├── post_metadata.py          Transcript-grounded post metadata
├── zernio_connections.py    Zernio key and account discovery
└── zernio_poster.py          Zernio publishing integration
~~~

## Licence and third-party notices

The project source is under the custom **Proprietary Non-Commercial Use Licence** in [LICENSE](LICENSE). It is not an OSI-approved open-source licence. Commercial use and public redistribution of project code are not granted by that licence; obtain written permission from the applicable rights holders before doing either.

Third-party libraries, model weights, and bundled fonts retain their own licences. Their notices are collected under [licenses/third-party/](licenses/third-party/). The YuNet notice applies to the bundled model file only; it does not describe or claim ownership of StreamSnip's own multi-frame detection and framing logic. The bundled JetBrains Mono font is covered by its OFL notice.

## Support

- **Bug reports:** [GitHub Issues](https://github.com/sifat-jaman-13/stream-clip-ai/issues)
- **Releases:** [GitHub Releases](https://github.com/sifat-jaman-13/stream-clip-ai/releases)
- **Project site:** [sifat-jaman-13.github.io/stream-clip-ai](https://sifat-jaman-13.github.io/stream-clip-ai/)

<div align="center">
  <sub>StreamSnip AI · Built for creators who want control of the whole clipping workflow.</sub>
</div>