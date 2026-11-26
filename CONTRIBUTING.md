# Contributing to StreamSnip AI

Thanks for helping improve StreamSnip AI. Focused bug fixes, regression tests, documentation, and carefully scoped feature proposals are welcome.

## Before opening an issue

1. Search the existing [issues](https://github.com/sifat-jaman-13/stream-clip-ai/issues) and [releases](https://github.com/sifat-jaman-13/stream-clip-ai/releases).
2. Reproduce the problem with the latest release or current development branch.
3. Remove API keys, tokens, account IDs, private local paths, and private video/transcript content from logs and screenshots.
4. For security-sensitive reports, follow [SECURITY.md](SECURITY.md) and use private vulnerability reporting.

A useful report includes the operating system, app version, Python version (for source installs), capture source type, selected AI provider, relevant Activity output, expected behavior, and exact reproduction steps.

## Development setup

The primary supported workflow is Windows 10/11 x64. Python 3.12, Node.js 22, and .NET 10 are recommended for source development. FFmpeg must be available on PATH.

~~~powershell
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install "pytest>=8"

Set-Location .\dashboard
npm ci
npm run lint
npm run build
Set-Location ..
~~~

Run the native WinUI 3 application from the repository root:

~~~powershell
$env:STREAMSNIP_SOURCE_DIR = (Get-Location).Path
$env:STREAMSNIP_PYTHON = (Join-Path (Get-Location).Path ".venv\Scripts\python.exe")
dotnet run --project .\desktop\StreamSnip.Desktop\StreamSnip.Desktop.csproj
~~~

The React/Vite dashboard can be run separately for browser-oriented frontend development. Start the Python engine with STREAMSNIP_PORT=8204 in one terminal, then run npm run dev from dashboard in another. See the root README for the full workflow.

## Validation

Run Python checks from the repository root:

~~~powershell
python -m py_compile autoclip.py api_server.py ai_highlights.py post_metadata.py zernio_poster.py zernio_connections.py facecam_detect.py
python -m pytest -q
~~~

Run frontend checks from dashboard:

~~~powershell
npm run lint
npm run build
~~~

For changes to the WinUI 3 shell, build it on Windows:

~~~powershell
dotnet restore .\desktop\StreamSnip.Desktop\StreamSnip.Desktop.csproj
dotnet build .\desktop\StreamSnip.Desktop\StreamSnip.Desktop.csproj --no-restore
~~~

For installer changes, run:

~~~powershell
.\build_native_installer.ps1
~~~

This creates dist\installer\StreamSnipAI-Native-Setup.exe and its SHA-256 file. The build requires Node.js 22, .NET 10 SDK, and Inno Setup 6. The CI release workflow uses the same native builder.

## Project structure and conventions

- autoclip.py owns application services, capture workers, creator monitoring, and media workflow orchestration.
- api_server.py exposes local engine services through the loopback-only FastAPI transport.
- dashboard/ contains the separate React, TypeScript, and Vite browser dashboard.
- desktop/StreamSnip.Desktop/ contains the native WinUI 3 Windows shell.
- ai_highlights.py owns local and hosted highlight-analysis providers; never log or return secrets.
- post_metadata.py builds transcript-grounded titles, descriptions, and hashtags.
- zernio_poster.py owns Zernio API requests, media uploads, idempotency, and destination-result parsing.
- zernio_connections.py owns API-key configuration, account discovery, per-account selection, and rate-limit classification.
- installer/ and build_native_installer.ps1 own Windows packaging and setup.
- Add regression coverage for every behavior change and bug fix.
- Keep capture and state-changing user actions explicit.
- Preserve local-first defaults. Hosted AI and social publishing remain user-configured integrations.
- Keep the local HTTP service on loopback and preserve host/token protections.
- Do not commit runtime JSON, SQLite databases, recordings, clips, model caches, build outputs, recovery copies, or credentials.
- Never run a live social publish as an automated test unless the test explicitly intends to create an external post and has approval.

## Pull requests

Keep changes focused and explain what changed, why it changed, how it was tested, and any privacy, rate-limit, installer, licensing, or compatibility impact. Include screenshots for visible UI changes with private data removed.

Avoid unrelated formatting and generated-file changes. Do not update the application version unless preparing a release.

## Maintainer release checklist

1. Synchronize the version in autoclip.py, pyproject.toml, and native installer metadata.
2. Run the Python regression suite, Python compilation, dashboard lint, dashboard production build, and the Windows WinUI build.
3. Run build_native_installer.ps1 and verify the generated native installer.
4. Verify the matching SHA-256 checksum.
5. Tag the tested commit and let the release workflow attach the native installer and checksum.
6. Confirm the release-cleanup workflow retains only the intended stable native installer asset.
7. Update CHANGELOG.md and verify the README and project website match the release.
