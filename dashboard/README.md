# StreamSnip AI — React Dashboard

The React dashboard is a separate frontend for the existing StreamSnip AI Python engine. It uses the engine's local HTTP API; it does not replace the capture, transcription, rendering, AI, or publishing backend.

## Current dashboard areas

- **Overview** — session status, creator monitors, and recent clips.
- **Live Studio** — add creator profiles, start/stop live monitors, and manage recorded-VOD folder watchers.
- **Clip library** — search, preview, reveal, and delete generated clips.
- **Published** — view clips already recorded in the backend's Posted registry.
- **Activity** — review events returned by the local engine.
- **Settings and Help** — migration guidance; advanced provider and application settings remain in the classic interface for now.

## Requirements

- Windows 10 or 11.
- Python 3.10–3.12 for the documented backend setup.
- Node.js with npm.
- FFmpeg available on PATH for video processing.

## 1. Install the Python backend dependencies

Run these commands from the repository root, not from the dashboard folder:

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
~~~

If the repository's .venv already exists and its dependencies are installed, skip this step. If PowerShell blocks virtual-environment activation, you can call the environment's interpreter directly with ..\.venv\Scripts\python.exe from this folder.

## 2. Start the existing Python engine

Open a first PowerShell terminal in the repository root:

~~~powershell
$env:STREAMSNIP_PORT = "8204"
.\.venv\Scripts\python.exe .\autoclip.py
~~~

The port setting matters: the Vite development proxy targets http://127.0.0.1:8204. Without this environment variable, the Python app chooses an available random port by default.

Keep this terminal open while using StreamSnip AI. The Python app also opens its classic interface; the React dashboard is opened separately in the next step.

## 3. Install and start the React dashboard

Open a second PowerShell terminal:

~~~powershell
Set-Location .\dashboard
npm ci
npm run dev
~~~

Open **http://127.0.0.1:5173/dashboard/**. Vite proxies /api and /clips requests to the Python engine on port 8204.

In Vite development, the React frontend obtains the running engine's local session token from /api/session. In production, the Python handler injects that process token into the built dashboard HTML. The session endpoint accepts requests only when the Host is loopback and any supplied Origin is also loopback. Keep the backend bound to localhost; do not expose it to your LAN or the public internet.

## Development checks

Run from the dashboard folder:

~~~powershell
npm run lint
npm run build
~~~

The production build is written to dashboard/dist.

Run the Python regression suite from the repository root:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
~~~

## Important migration note

The Python backend continues to serve the classic interface at its root URL. After npm run build, the same Python HTTP server serves the React bundle at /dashboard/. During development, Vite serves the same route at port 5173. The Settings and Help pages intentionally point users to the classic interface for features that have not been migrated.

No capture or publishing job is started simply by opening the dashboard. Monitoring and clip deletion are separate actions initiated from their controls. Publishing controls remain in the classic interface until that part of the migration is complete.

## Troubleshooting

- **Engine offline:** confirm the Python terminal is still running and that it was started with STREAMSNIP_PORT=8204.
- **POST requests return 403:** restart the backend after updating the Python source, then reload the Vite page so it fetches a fresh session token.
- **Port 8204 is already in use:** stop the other process only if you know it is safe to stop, or choose another backend port and update dashboard/vite.config.ts to match.
- **Missing video previews:** verify that the Python engine is running and that the clip is still present in the local clip folders.
- **Missing packages:** run npm ci in dashboard, or python -m pip install -r requirements.txt from the repository root.
