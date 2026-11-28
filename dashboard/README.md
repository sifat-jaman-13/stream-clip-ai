# StreamSnip AI Creator Studio

The dashboard is the React, TypeScript, and Vite frontend for StreamSnip AI. It is the default local interface and connects to the Python application through its loopback-only FastAPI API.

The Python application remains responsible for capture, creator monitoring, transcription, AI analysis, rendering, files, and publishing integrations. The API transport adapts the established application services; it is not a separate capture engine.

## Workspace areas

- **Dashboard** - engine status, current session, recent clips, and creator activity.
- **Live Studio** - choose a Twitch/YouTube live source or a local video/VOD. Configure Capture, AI provider, Transcription, and Captions before starting.
- **Creators** - manage independent live monitors and recorded-VOD folder watchers.
- **Clip library** - browse a responsive portrait-first card grid, hover for a muted preview, open the large player with caption and metadata, edit post copy, and use per-clip or bulk review actions.
- **Scheduled** - review provider-confirmed scheduled posts and completed publishing history.
- **Hype words** - edit the phrase list used by local highlight scoring.
- **Publishing** - configure Zernio accounts or prepare a manual upload in the system browser.
- **Settings** - manage application-wide storage and appearance. Session-specific processing settings belong in Live Studio.
- **Activity, Help, and About** - inspect engine events and access workflow and project information.

Opening the dashboard does not start capture or a creator monitor. Starting and stopping work are explicit user actions.

## Requirements

- Windows 10 or 11.
- Python 3.10 or later (Python 3.12 is used in the commands below).
- Node.js and npm compatible with the installed Vite version.
- FFmpeg available on PATH for media processing.

## Production build

Run these commands from the repository root:

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Set-Location .\dashboard
npm ci
npm run build
Set-Location ..
python autoclip.py
~~~

The Python application serves the compiled dashboard from /dashboard/ and opens it by default when the build is present. The root URL redirects to /dashboard/. The production bundle is written to dashboard/dist.

## Development mode

Use two PowerShell terminals.

**Terminal 1 - start the Python application from the repository root:**

~~~powershell
$env:STREAMSNIP_PORT = "8204"
.\.venv\Scripts\python.exe .\autoclip.py
~~~

The fixed port is required by the Vite proxy configuration. The app uses an available port automatically when STREAMSNIP_PORT is omitted.

**Terminal 2 - start Vite from the dashboard folder:**

~~~powershell
Set-Location .\dashboard
npm ci
npm run dev
~~~

Open http://127.0.0.1:5173/dashboard/. Vite proxies /api and /clips to the Python application at http://127.0.0.1:8204.

In development, the frontend obtains the running process's session token from /api/session. In production, the Python application injects its process token into the built dashboard HTML. The local API validates loopback host and client addresses. Keep the service on localhost; do not expose it to a LAN or the public internet.

## Development checks

Run from the dashboard folder:

~~~powershell
npm run lint
npm run build
~~~

Run the Python regression suite from the repository root:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
python -m py_compile autoclip.py api_server.py
~~~

## Architecture notes

- React owns the presentation and local workspace interactions.
- The Python application owns capture and media-processing behavior.
- FastAPI and Uvicorn provide the local HTTP transport around the existing application handler.
- Session-specific capture, AI, transcription, and caption configuration is grouped in Live Studio so users can review it before starting.
- Global Settings is reserved for application-wide storage and appearance.
- The default appearance is Odysseus with JetBrains Mono. Users can select another theme or font from the appearance controls.
- Provider credentials remain in local application settings and are not returned to the frontend.
- Hosted AI providers receive transcript text when selected. The AI provider tab identifies the transcript-sharing behavior.

Publishing creates an external side effect. Do not run a real publish test unless you intend to create a public or scheduled post.

## Troubleshooting

- **Engine unavailable:** confirm the Python application is still running and that it was started with STREAMSNIP_PORT=8204.
- **POST requests return 403:** reload the dashboard to fetch the current session token. Restart the Python application after updating backend source.
- **Port 8204 is in use:** stop the other process only when you know it is safe, or update dashboard/vite.config.ts and STREAMSNIP_PORT to the same unused port.
- **Missing video previews:** verify the Python application is running and that the clip still exists in its local output folder.
- **Missing packages:** run npm ci in dashboard, or python -m pip install -r requirements.txt from the repository root.
