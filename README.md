# StreamSnip AI

**A local-first creator studio for capturing streams, finding moments, rendering clips, and preparing posts.**

[![Latest release](https://img.shields.io/github/v/release/sifat-jaman-13/stream-clip-ai)](https://github.com/sifat-jaman-13/stream-clip-ai/releases)
[![Windows](https://img.shields.io/badge/platform-Windows-2563eb)](https://github.com/sifat-jaman-13/stream-clip-ai)
[![Tests](https://github.com/sifat-jaman-13/stream-clip-ai/actions/workflows/tests.yml/badge.svg)](https://github.com/sifat-jaman-13/stream-clip-ai/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/license-proprietary%20non--commercial-orange)](LICENSE)

StreamSnip AI is a desktop-hosted creator workspace. It combines Twitch and YouTube capture, creator monitoring, local transcription, AI-assisted highlight selection, captioned video rendering, clip review, and publishing handoff in one local application.

The React Creator Studio is the default interface. The Python engine continues to handle capture and media processing; a loopback-only FastAPI server exposes the local application API.

> **Source status:** The repository can contain newer Creator Studio work than the installer currently published under GitHub Releases. A source-code update does not mean a new installer or tagged release has shipped.

## The creator workflow

1. **Dashboard** - Check engine health, current capture status, recent clips, and creator activity.
2. **Live Studio** - Select a Twitch or YouTube live source, or a local video/VOD. Review the session configuration before starting.
3. **Session setup** - Configure the four tabs in Live Studio:
   - **Capture:** source mode, capture behavior, and processing options.
   - **AI provider:** highlight-analysis provider, model, and credentials.
   - **Transcription:** local speech model, language, and optional custom transcriber.
   - **Captions:** aspect ratio, framing, subtitle appearance, creator credit, and profanity filtering.
4. **Creators** - Save channels for independent live monitoring and recorded-VOD folder watching.
5. **Clip library** - Preview generated clips, inspect or edit their title and description, and prepare a post.
6. **Publishing / Published** - Publish through a configured Zernio connection or hand off to a platform's upload page in the system browser. Successfully posted clips are tracked separately.

Opening Live Studio does not start a recording. Capture starts only after the user presses **Start capture**. The application saves the visible session settings before sending the start request.

## Features

- Capture supported Twitch and YouTube live streams with Streamlink.
- Process local video files and recorded VODs.
- Monitor multiple saved creators independently.
- Keep each creator's live recordings, live clips, VOD inbox, processed originals, and failed VODs in separate folders.
- Transcribe speech locally with faster-whisper, or connect a custom command-line transcriber.
- Analyze transcript windows for high-potential moments using local scoring or a configured AI provider.
- Choose Hook Words, Ollama, Gemini, Hugging Face, or a custom OpenAI-compatible chat-completions provider, subject to provider configuration.
- Render portrait, landscape, square, and 4:5 clips with configurable framing and captions.
- Generate transcript-grounded titles, descriptions, and hashtags.
- Review clips before sharing and keep posted clips in a separate Published view.
- Publish through Zernio when an API key and eligible connected social account are available.
- Use manual browser handoff as a fallback; the user selects the local video and completes the final Publish action.
- Choose an application theme and font. Odysseus is the default theme; JetBrains Mono is the default interface font. Google Sans, Inter, Roboto, and other font options are available.

Highlight scores are estimates, not guarantees of reach or engagement.

## AI providers, API keys, and privacy

The capture and media-processing workflow does not require a StreamSnip cloud account or a StreamSnip API key.

| Capability | Credential / network requirement |
| --- | --- |
| Local capture and FFmpeg rendering | No StreamSnip API key; stream capture needs internet access |
| Built-in faster-whisper transcription | Runs locally; speech models must be available on the PC |
| Custom local transcriber | No StreamSnip API key; the transcriber may have its own requirements |
| Hook Words scoring | Local; no hosted AI key |
| Ollama | Local service; no hosted AI key when using a local Ollama instance |
| Gemini, Hugging Face, or another hosted AI provider | The selected provider may require its own key or token |
| Direct social publishing | Zernio API key and connected social accounts |

When no AI provider has been saved, Gemini is the initial provider selection. Gemini-backed capture requires a saved Gemini API key. Select another provider in Live Studio when you do not want to use Gemini.

Hosted AI providers receive the transcript text needed for highlight analysis and generated post copy. Choose local Hook Words scoring or a local Ollama instance when you do not want transcript text sent to a hosted AI provider.

Provider credentials are stored in local application settings and are not returned to the browser interface. The local API binds to loopback by default. Keep it on localhost; do not expose it to a LAN or the public internet. Never commit settings files, API keys, OAuth tokens, recordings, or generated clips to Git.

## Bring-your-own transcriber

Choose the custom CLI/script option in the **Transcription** tab. The command supports these placeholders:

- {input} - absolute path to the source video or audio file.
- {output} - temporary JSON output path.
- {language} - selected language value; defaults to auto.

Example command for whisper.cpp:

~~~text
whisper-cli -f "{input}" -oj -of "{output}"
~~~

The transcriber can write JSON to the output file or print JSON to stdout. Word-level timestamps are preferred:

~~~json
{
  "words": [
    { "start": 0.10, "end": 0.48, "word": "hello" },
    { "start": 0.50, "end": 0.82, "word": "there" }
  ]
}
~~~

Segment-based output is also accepted:

~~~json
{
  "segments": [
    { "start": 0.0, "end": 2.4, "text": "Hello there, welcome back." }
  ]
}
~~~

Word timestamps provide more accurate subtitle and censor timing. Segment-only output is accepted, but word timing is approximated by distributing words across the segment duration. Commands are launched without a shell, so use an executable and arguments rather than shell operators or pipes. Do not put API keys in the command field; use environment variables or the transcriber's own secure local configuration.

## Creator folder layout

Live capture and recorded VODs are kept separate for each creator:

~~~text
Creators/
  Creator_Name_ID/
    Live/
      Recordings/
      Clips/
    Recorded_VODs/
      Watch_Inbox/
      Clips/
      Processed_Originals/
      Failed/
~~~

Enable a creator's VOD folder watcher and place a completed recording in its Watch_Inbox. StreamSnip waits for the copy to finish before processing it. Removing a creator profile does not automatically delete that creator's existing files.

## Publishing

For direct publishing, configure the Zernio API key and connect the social accounts you intend to use. Select destinations and edit the post copy before publishing. Availability depends on account permissions and each platform's media requirements.

Manual publishing opens the selected platform in the operating system's default browser and prepares the post text. You must select the local video and complete the final Publish action yourself. StreamSnip does not silently attach a local file or take control of another site's authenticated form.

Do not run a real publishing test unless you intend to create a public or scheduled post. Account and credential checks that do not submit a post are safe read-only checks.

## Install on Windows

Download the latest published installer from [GitHub Releases](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest).

Review the release notes and SHA-256 checksum before running an installer. The published installer is unsigned. Keep the support terminal open while StreamSnip AI is running. Use **Quit** inside the app and wait for shutdown before closing the terminal; closing it directly may interrupt recording, processing, or uploads.

## Run from source

Requirements:

- Windows 10 or 11.
- Python 3.10 or later; Python 3.12 is used in the commands below.
- Node.js and npm compatible with the Vite version in the dashboard.
- FFmpeg available on PATH.
- Internet access for live stream capture and hosted integrations.

Clone the repository and install the Python dependencies:

~~~powershell
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
~~~

Install and build the React dashboard:

~~~powershell
Set-Location .\dashboard
npm ci
npm run build
Set-Location ..
~~~

Start the application from the repository root:

~~~powershell
python autoclip.py
~~~

The app prints its local address and opens the Creator Studio when the production dashboard build is present. Open the printed local address followed by /dashboard/ if you need to open it manually. The root URL redirects to the Creator Studio.

## Frontend development

Use two PowerShell terminals.

**Terminal 1 - local Python engine:**

~~~powershell
$env:STREAMSNIP_PORT = "8204"
.\.venv\Scripts\python.exe .\autoclip.py
~~~

**Terminal 2 - Vite development server:**

~~~powershell
Set-Location .\dashboard
npm ci
npm run dev
~~~

Open http://127.0.0.1:5173/dashboard/. Vite proxies /api and /clips requests to the Python engine on port 8204. The backend chooses an available port when STREAMSNIP_PORT is not set, so use the fixed port above for this development proxy configuration.

The local API documentation is available at http://127.0.0.1:8204/api/docs while the development server is running. Keep the backend bound to localhost.

## Development checks

From the repository root, run the Python tests and syntax checks:

~~~powershell
python -m pytest -q
python -m py_compile autoclip.py api_server.py
~~~

From the dashboard folder, run the frontend checks:

~~~powershell
npm run lint
npm run build
~~~

The production dashboard bundle is written to dashboard/dist. GitHub Actions runs the repository's automated test workflow.

## Project resources

- [Issues](https://github.com/sifat-jaman-13/stream-clip-ai/issues)
- [Discussions](https://github.com/sifat-jaman-13/stream-clip-ai/discussions)
- [Project site](https://sifat-jaman-13.github.io/stream-clip-ai/)
- [Browser-assisted publishing guide](docs/BROWSER_AUTOMATION.md)

## Licence

This repository uses a **Proprietary Non-Commercial Use Licence**. It is source-available, not an OSI-approved open-source licence. Personal, private, and individual educational use is permitted under the licence. Commercial use requires prior written permission. Read [LICENSE](LICENSE) before using or redistributing the software.

---

Built by [Sifat Jaman / ScarZero](https://github.com/sifat-jaman-13).
