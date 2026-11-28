<div align="center">
  <img src="assets/streamsnipai-banner.svg" width="100%" alt="StreamSnip AI, a native Windows studio for turning live streams into shareable clips">
  <p><strong>Capture the moment. Shape the clip. Review it. Publish when you are ready.</strong></p>
  <p>
    <a href="https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest"><img src="https://img.shields.io/github/v/release/sifat-jaman-13/stream-clip-ai?display_name=tag&style=flat-square&label=latest%20release" alt="Latest release"></a>
    <a href="https://github.com/sifat-jaman-13/stream-clip-ai/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/sifat-jaman-13/stream-clip-ai/tests.yml?branch=master&style=flat-square&label=tests" alt="Test workflow"></a>
    <a href="https://github.com/sifat-jaman-13/stream-clip-ai/actions/workflows/build-installer.yml"><img src="https://img.shields.io/github/actions/workflow/status/sifat-jaman-13/stream-clip-ai/build-installer.yml?branch=master&style=flat-square&label=Windows%20installer" alt="Windows installer workflow"></a>
    <img src="https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-2878d0?style=flat-square&logo=windows" alt="Windows 10 and 11">
    <img src="https://img.shields.io/badge/interface-React%20%2B%20pywebview-236b78?style=flat-square" alt="React and pywebview">
    <img src="https://img.shields.io/badge/licence-proprietary%20non--commercial-c47d46?style=flat-square" alt="Proprietary non-commercial licence">
  </p>
  <p>
    <a href="https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest"><strong>Download for Windows</strong></a>
    | <a href="https://sifat-jaman-13.github.io/stream-clip-ai/">Project website</a>
    | <a href="docs/USER_GUIDE.md">Complete user guide</a>
    | <a href="https://github.com/sifat-jaman-13/stream-clip-ai/issues">Report a problem</a>
  </p>
</div>

## What it is

StreamSnip AI is a **native Windows creator studio** for turning supported Twitch and YouTube live streams, recorded VODs, and local videos into short-form clips. It brings capture, creator monitoring, local transcription, AI-assisted highlight selection, facecam-aware framing, animated captions, clip review, metadata, and controlled publishing into one workflow.

The installed desktop app uses FastAPI + React/TypeScript + pywebview. FastAPI is the only local backend, React/Vite is the only application interface, and pywebview opens that same React build in a Windows desktop window using WebView2. Capture, transcription, rendering, and publishing orchestration remain in Python.

**Capture and publishing are always explicit actions.** Opening Live Studio does not start recording, and StreamSnip does not publish clips automatically.

## See the app

Screenshots below show the React Creator Studio interface.

<p align="center">
  <img src="docs/assets/product/dashboard.png" width="100%" alt="StreamSnip AI 4.0.10 Dashboard in Studio Dark with the session rundown, local engine status, recent clips and creator monitors">
</p>

<details>
  <summary><strong>View the other workspaces</strong></summary>
  <br>
  <table>
    <tr>
      <td width="50%">
        <p align="center"><strong>Live Studio</strong></p>
        <img src="docs/assets/product/live-studio.png" width="100%" alt="StreamSnip AI 4.0.10 Live Studio in Studio Dark with source selection and pre-capture configuration">
      </td>
      <td width="50%">
        <p align="center"><strong>Creator monitoring</strong></p>
        <img src="docs/assets/product/creator-monitoring.png" width="100%" alt="StreamSnip AI 4.0.10 Creators page in Studio Dark showing independent live and recorded VOD monitors">
      </td>
    </tr>
    <tr>
      <td width="50%">
        <p align="center"><strong>Clip Library</strong></p>
        <img src="docs/assets/product/clip-library.png" width="100%" alt="StreamSnip AI 4.0.10 Clip Library in Studio Dark with Ready to review and Scheduled tabs">
      </td>
      <td width="50%">
        <p align="center"><strong>Publisher</strong></p>
        <img src="docs/assets/product/publishing.png" width="100%" alt="StreamSnip AI 4.0.10 Publisher in Studio Dark with five Zernio connection slots">
      </td>
    </tr>
  </table>
</details>

## Install on Windows

1. Open [GitHub Releases](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest).
2. Download `StreamSnipAI-Setup.exe` and its matching `.sha256` file into the same folder.
3. Open PowerShell in that folder and verify the installer:

```powershell
$installer = '.\StreamSnipAI-Setup.exe'
$checksum = "$installer.sha256"
$expected = ((Get-Content -LiteralPath $checksum -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()

if ($actual -ne $expected) {
    throw 'SHA-256 mismatch. Do not run this installer.'
}

Write-Host "SHA-256 verified: $actual"
```

4. Run the installer and launch StreamSnip AI from the Start menu or desktop shortcut.

The app supports Windows 10/11 x64. You do not need to install Python or FFmpeg globally; setup prepares an isolated runtime, reuses compatible components, and installs or repairs missing packages. It can reuse a compatible 64-bit Python installation, including **Python 3.15**. On Python 3.15, setup installs Faster-Whisper 1.2.1 through a dedicated compatibility path and omits its optional ONNX Runtime-backed VAD dependency. If no installed Python passes the dependency checks, setup installs a private Python 3.14.10 runtime for the app. Internet access is required when setup needs to download packages or model files.

The installer is currently unsigned, so Windows SmartScreen may show a publisher warning. Only continue if the installer came from the official release and its checksum matches.

## Quick start: first clip

1. **Check Dashboard.** Wait for the local engine to show that it is connected and ready.
2. **Choose a source.** In Live Studio, select Live stream for Twitch/YouTube or Video file / VOD for a local video. Paste the URL or use Browse video.
3. **Preview.** Press Preview source frame to verify the selected source. This is only a still-frame check.
4. **Configure.** Set Capture, AI provider, Transcription, and Captions in Live Studio before recording.
5. **Start.** Press Start capture. Follow the actual status and progress in Live Studio or Dashboard.
6. **Stop.** Press Stop capture when you are finished. Allow active work to stop gracefully.
7. **Review.** Open Clip Library, preview the MP4, and correct its title, description, and tags.
8. **Publish if wanted.** Open Publisher, connect up to five Zernio API keys, and enable the destinations you want. Use **Post** on a clip for immediate publishing or **Auto schedule** to queue every ready clip.

See the [complete user guide](docs/USER_GUIDE.md) for detailed setup, each setting, creator monitoring, publishing, storage, and troubleshooting.

## What to configure in Live Studio

Live Studio keeps the full pre-capture setup in one place.

| Tab | Main options |
| --- | --- |
| Capture | Chunk length, seconds before/after a highlight, minimum score, bitrate, and max clips per chunk |
| AI provider | Gemini, Ollama, OpenAI/ChatGPT API, Anthropic/Claude API, or custom OpenAI-compatible endpoint |
| Transcription | Shared Faster-Whisper model, language, provider, and CPU/GPU settings |
| Framing | Per-creator video layout and output ratio, GPU-first automatic facecam detection, and manual pink facecam/cyan gameplay regions |
| Captions | Per-creator subtitle mode/style, font, colors, position, creator credit, and tag |
| Shared defaults | AI provider, caption/transcription provider, clipping thresholds, and profanity filter apply to every creator |

### AI providers

- **Gemini, OpenAI, and Claude** are hosted APIs. Use your own API key, model access, and quota.
- **Ollama** runs on the local service you configure and does not require a hosted AI API key.
- **Custom OpenAI-compatible API** can point to a compatible hosted or local endpoint.

The selected model analyzes transcript windows, selects candidate moments, and generates title, description, and topical tags. Use Test provider, then Save AI settings. Hosted providers receive transcript text for the task you choose; check their privacy and billing terms.

### Transcription and output

Faster-Whisper, FFmpeg rendering, OpenCV/YuNet, and local Hook Words processing run on your PC. Facecam framing uses local multi-frame facecam detection with a supported GPU provider first and CPU only when no compatible GPU is available; review automatic results and adjust the manual framing regions when needed.

Each creator keeps independent facecam/game regions, video layout, output ratio, and caption appearance. Supported ratios are 9:16 portrait, 16:9 landscape, 1:1 square, and 4:5. AI provider, caption/transcription provider, clipping thresholds, and profanity filtering remain shared defaults.

## Appearance and typography

JetBrains Mono remains the default UI font. The font picker also offers Manrope, DM Sans, Inter, Open Sans, IBM Plex Sans, Nunito Sans, Roboto, Source Sans 3, Poppins, Lato, Fira Code, and Windows/system and serif alternatives. Theme text colors are contrast-corrected so labels remain readable across the available palettes.

## Workspaces

| Workspace | Purpose |
| --- | --- |
| Dashboard | Session status, processing rundown, recent clips, creator activity, and engine events |
| Live Studio | Source selection and all pre-capture settings |
| Creators | Independent Twitch/YouTube monitors and recorded-VOD folder watching |
| Clip Library | Find, preview, and review generated clips and metadata |
| Scheduled | Zernio-confirmed scheduled posts and completed publishing history |
| Hype words | Local phrases used by the Hook Words scoring option |
| Publisher | Five Zernio API-key slots, account discovery, and destination controls |
| Settings | Application-wide appearance and storage |
| Activity | Engine and workflow event history |
| Help & how-to | In-app quick start and troubleshooting |
| About | App version, architecture, source, and release links |

## Publishing and supported destinations

Publishing is optional and uses your configured Zernio integration. Publisher provides five independent API-key slots. Each slot discovers its Facebook, Instagram, and YouTube destinations, and you can enable the accounts you want to use. Use the per-clip **Post** action for immediate publishing or **Auto schedule** to queue all ready clips using your saved spacing interval (5 minutes when the interval is zero).

The current integration supports **Facebook, Instagram, and YouTube**. **TikTok is not a supported destination in this integration.** Account availability, upload limits, quotas, and posting errors are controlled by Zernio and the connected platforms. A clip moves to **Scheduled** only after Zernio confirms a future-dated destination. The Scheduled view also retains completed posts with a **Posted** status; pending or failed requests do not move a clip out of Clip Library.

Review every video and its metadata before posting. Highlight scores are suggestions, not guarantees of views or engagement.

## Local files and privacy

The installed app stores its local engine data under:

```
%LOCALAPPDATA%\StreamSnip AI\
```

Common folders include `out\` for generated clips, `rec\` for recordings and capture chunks, and `models\` for downloaded model files. Settings, provider configuration, creator profiles, publishing configuration, and logs are stored in the same local application-data area.

- Capture, transcription, facecam detection, rendering, and Hook Words are local.
- Ollama analysis stays on the local service you configure.
- Hosted AI receives transcript text for the task you request.
- Zernio receives selected media and post details when you publish.

The local API binds to loopback and uses a per-process session token for state-changing requests. **Do not expose it to an untrusted network or the public internet.** Never commit API keys, social tokens, cookies, or local browser profiles.

## Troubleshooting

- **Engine offline:** wait for startup; use runtime repair or rerun the latest installer and choose Repair. Check `%LOCALAPPDATA%\StreamSnip AI\setup.log` and `streamsnip.log`.
- **No source preview:** confirm the URL is supported and online, or verify the local file exists and opens in a media player.
- **No clips:** confirm the AI provider test succeeds, check the model/quota, lower an overly restrictive minimum score, and allow transcription/rendering to finish.
- **Slow transcription:** try a smaller Faster-Whisper model, ensure it is downloaded, and check available RAM/VRAM and disk space.
- **Publishing failure:** refresh connected accounts, check account enablement and provider quota, and inspect Activity for the destination result.

The [complete user guide](docs/USER_GUIDE.md) has step-by-step recovery instructions and more troubleshooting cases.

## Build from source

**Prerequisites:** Windows 10/11 x64, Python 3.10+, Node.js 22 with npm, .NET 10 SDK, Inno Setup 6, and FFmpeg.

```powershell
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai

python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,live]"

cd dashboard
npm ci
npm run lint
npm run build
cd ..

.\build_installer.ps1
python -m pytest -q
```

The build script runs React lint and Vite production build, packages the pywebview shell with PyInstaller, compiles the Inno Setup installer, and writes StreamSnipAI-Setup.exe plus its SHA-256 sidecar under dist\installer\. It does not build a second UI or compile a C# desktop shell.

## Project information

- [Complete user guide](docs/USER_GUIDE.md)
- [Product overview](PRODUCT.md)
- [Design system](DESIGN.md)
- [Release history](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Third-party notices](licenses/third-party/)

### Licence

The project source is under the custom [Proprietary Non-Commercial Use Licence](LICENSE). It is **not** an OSI-approved open-source licence. Commercial use and public redistribution are not granted by this licence; obtain written permission from the applicable rights holders before either.

### Support

- [Open an issue](https://github.com/sifat-jaman-13/stream-clip-ai/issues)
- [Download releases](https://github.com/sifat-jaman-13/stream-clip-ai/releases)
- [Visit the project website](https://sifat-jaman-13.github.io/stream-clip-ai/)
