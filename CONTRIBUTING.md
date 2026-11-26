# Contributing to StreamSnip AI

Thanks for helping improve StreamSnip AI. Focused bug fixes, regression tests, documentation, and carefully scoped feature proposals are welcome.

## Before opening an issue

1. Search the existing [issues](https://github.com/sifat-jaman-13/stream-clip-ai/issues) and [releases](https://github.com/sifat-jaman-13/stream-clip-ai/releases).
2. Reproduce the problem with the latest release or current default branch.
3. Remove API keys, tokens, account IDs, private local paths, and private video/transcript content from logs and screenshots.
4. For security-sensitive reports, follow [SECURITY.md](SECURITY.md) and use private vulnerability reporting.

A useful report includes the operating system, app version, Python version (for source installs), capture source type, selected AI provider, relevant Activity output, expected behavior, and exact reproduction steps.

## Development setup

The primary supported workflow is Windows 10/11. Python 3.12 and Node.js 22 are recommended for source development. FFmpeg must be available on PATH.

    git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
    cd stream-clip-ai

    py -3.12 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    python -m pip install "pytest>=8"

    Set-Location .\dashboard
    npm ci
    npm run build
    Set-Location ..

Run the application from the repository root:

    python autoclip.py

For frontend development, run the backend with STREAMSNIP_PORT=8204 in one terminal and npm run dev from dashboard in another. See the root README for the complete two-terminal workflow.

## Validation

Run the Python checks from the repository root:

    python -m py_compile autoclip.py api_server.py ai_highlights.py post_metadata.py zernio_poster.py zernio_connections.py facecam_detect.py
    python -m pytest -q

Run frontend checks from dashboard:

    npm run lint
    npm run build

For changes to the optional WinUI 3 Windows shell, also build the project on Windows:

    dotnet restore .\desktop\StreamSnip.Desktop\StreamSnip.Desktop.csproj
    dotnet build .\desktop\StreamSnip.Desktop\StreamSnip.Desktop.csproj --no-restore

If a change affects the Windows installer, run the packaging script:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1

## Project structure and conventions

- autoclip.py owns application services, capture workers, creator monitoring, and the media workflow.
- api_server.py exposes those services through the loopback-only FastAPI transport.
- dashboard/ contains the React, TypeScript, and Vite Creator Studio.
- ai_highlights.py owns local and hosted highlight-analysis providers; never log or return secrets.
- post_metadata.py builds transcript-grounded titles, descriptions, and hashtags.
- zernio_poster.py owns Zernio API requests, media uploads, idempotency, and publish-result parsing.
- zernio_connections.py owns multi-key configuration, account discovery, per-account selection, and rate-limit classification.
- desktop/StreamSnip.Desktop/ contains the optional WinUI 3 native Windows shell.
- installer/ and build_windows.ps1 own Windows packaging and setup.
- Add regression coverage for every behavior change and bug fix.
- Keep capture and state-changing user actions explicit.
- Preserve local-first defaults. Hosted AI and social publishing remain user-configured integrations.
- Keep the local HTTP service on loopback and preserve host/token protections.
- Do not commit runtime JSON, SQLite databases, recordings, clips, model caches, build output, recovery copies, or credentials.

## Pull requests

Keep changes focused and explain what changed, why it changed, how it was tested, and any privacy, rate-limit, installer, licensing, or compatibility impact. Include screenshots for visible UI changes with private data removed.

Avoid unrelated formatting and generated-file changes. Do not update the application version unless preparing a release.

## Maintainer release checklist

1. Synchronize the version in autoclip.py, pyproject.toml, and installer/AutoClip.iss.
2. Run the Python regression suite, Python compilation, dashboard lint, and dashboard production build.
3. Build and verify dist\installer\StreamSnipAI-Setup.exe.
4. Generate and verify the SHA-256 checksum.
5. Tag the tested commit and publish the installer/checksum from that tag.
6. Confirm the release-cleanup workflow retains only the intended stable installer assets.
7. Update CHANGELOG.md and verify the README matches the actual release.
