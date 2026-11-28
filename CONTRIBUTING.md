# Contributing to StreamSnip AI

Thanks for helping improve StreamSnip AI. Focused bug fixes, regression tests, documentation, and carefully scoped feature proposals are welcome.

## Before opening an issue

1. Search the existing issues and releases.
2. Reproduce the problem with the latest release or current development branch.
3. Remove API keys, tokens, account IDs, private local paths, and private video/transcript content from logs and screenshots.
4. For security-sensitive reports, follow SECURITY.md and use private vulnerability reporting.

A useful report includes the operating system, app version, Python version, capture source type, selected AI provider, relevant Activity output, expected behavior, and exact reproduction steps.

## Development setup

The primary supported workflow is Windows 10/11 x64. Use Python 3.10+ (Python 3.12 is the current CI baseline), Node.js 22, and FFmpeg.

~~~powershell
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt
python -m pip install "pytest>=8"

Set-Location .\dashboard
npm ci
npm run lint
npm run build
Set-Location ..
~~~

Run the single local FastAPI backend from the repository root:

~~~powershell
$env:STREAMSNIP_PORT = "8204"
python .\autoclip.py
~~~

In another terminal, run the React development server:

~~~powershell
Set-Location .\dashboard
npm run dev
~~~

Vite proxies local API calls to the Python server. For a packaged desktop build, pywebview opens the same production dashboard bundle; there is no separate desktop UI.

## Validation

Run Python checks from the repository root:

~~~powershell
python -m py_compile autoclip.py api_server.py desktop_shell.py ai_highlights.py post_metadata.py zernio_poster.py zernio_connections.py facecam_detect.py
python -m pytest -q
~~~

Run frontend checks:

~~~powershell
Set-Location .\dashboard
npm run lint
npm run build
Set-Location ..
~~~

For the Windows installer, run:

~~~powershell
.\build_installer.ps1
~~~

The build creates the React production bundle, packages desktop_shell.py with PyInstaller, compiles the Inno Setup installer, and writes dist\installer\StreamSnipAI-Setup.exe plus a SHA-256 sidecar. No .NET SDK or C# desktop build is required.

## Project structure and conventions

- autoclip.py owns capture workers, creator monitoring, media workflow orchestration, and application services.
- api_server.py exposes the only local HTTP API through FastAPI, bound to loopback.
- desktop_shell.py supervises the local Python process and hosts the React interface with pywebview/WebView2.
- dashboard/ contains the only application interface: React, TypeScript, and Vite.
- ai_highlights.py owns local and hosted highlight-analysis providers; never log or return secrets.
- post_metadata.py builds transcript-grounded titles, descriptions, and hashtags.
- zernio_poster.py owns Zernio API requests, media uploads, idempotency, and destination-result parsing.
- zernio_connections.py owns API-key configuration, account discovery, per-account selection, and rate-limit classification.
- installer/ and build_installer.ps1 own Windows packaging and setup.
- Add regression coverage for every behavior change and bug fix.
- Keep capture and state-changing user actions explicit.
- Preserve local-first defaults. Hosted AI and social publishing remain user-configured integrations.
- Keep the local API on loopback and preserve host/token protections.
- Do not commit runtime JSON, SQLite databases, recordings, clips, model caches, build outputs, recovery copies, or credentials.
- Never run a live social publish as an automated test unless the test explicitly intends to create an external post and has approval.

## Pull requests

Keep changes focused and explain what changed, why it changed, how it was tested, and any privacy, rate-limit, installer, licensing, or compatibility impact. Include screenshots for visible UI changes with private data removed.

Avoid unrelated formatting and generated-file changes. Do not update the application version unless preparing a release.

## Maintainer release checklist

1. Synchronize the version in autoclip.py and pyproject.toml.
2. Run the Python regression suite, Python compilation, dashboard lint, dashboard production build, and Windows installer build.
3. Verify the installer and SHA-256 sidecar.
4. Tag the release and verify the Windows installer CI artifact.
5. Attach release notes and user-facing installation guidance.
