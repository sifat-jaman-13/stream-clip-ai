# Contributing to StreamSnip AI

Thanks for helping improve StreamSnip AI. Bug reports, focused fixes, tests, documentation, and carefully scoped feature proposals are welcome.

## Before opening an issue

1. Search the existing [issues](https://github.com/sifat-jaman-13/stream-clip-ai/issues) and [releases](https://github.com/sifat-jaman-13/stream-clip-ai/releases).
2. Reproduce the problem with the latest release or current `master` branch.
3. Remove API keys, tokens, account IDs, local paths, and private video/transcript content from logs and screenshots.
4. For security-sensitive reports, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

A useful bug report includes the operating system, Python version (for source installs), app version, source type, selected AI provider, relevant Activity output, expected behavior, and exact reproduction steps.

## Development setup

Python 3.12 is recommended. FFmpeg must be available on `PATH` for rendering tests and normal operation.

```powershell
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Run the app:

```powershell
python autoclip.py
```

## Validation

Run both checks before proposing a change:

```powershell
python -m unittest discover -s tests -v
python -m py_compile autoclip.py ai_highlights.py zernio_poster.py
```

If a change affects Windows packaging, also run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1
```

## Project structure and conventions

- `autoclip.py` intentionally contains the local server and embedded HTML/CSS/JavaScript UI. Keep backend and UI changes synchronized.
- `ai_highlights.py` owns hosted/local AI provider behavior and must never log or return secrets.
- `zernio_poster.py` owns publishing requests and streamed media uploads.
- Add regression coverage for bug fixes and behavior changes.
- Prefer the Python standard library unless a dependency provides clear value to end users.
- Preserve local-first defaults. Hosted AI and publishing must remain explicit choices.
- Keep the HTTP server loopback-only by default and retain host/token protections.
- Do not silently fall back from a detected GPU failure to CPU; surface actionable diagnostics.
- Do not commit runtime JSON files, recordings, clips, model caches, build output, or credentials.

## Pull requests

Keep pull requests focused and explain:

- what changed;
- why it changed;
- how it was tested;
- any privacy, quota, installer, or compatibility impact;
- screenshots for visible UI changes, with private data removed.

Avoid unrelated formatting or generated-file changes. Do not update the application version unless the change is being prepared for a release.

## Maintainer release checklist

1. Synchronize the version in `autoclip.py`, `pyproject.toml`, and `installer/AutoClip.iss`.
2. Run the full regression and syntax checks.
3. Build and verify `dist\installer\StreamSnipAI-Setup.exe`.
4. Generate and verify the SHA-256 checksum.
5. Tag the tested commit and publish the installer/checksum from that tag.
6. Confirm the release-cleanup workflow keeps the installer only on the newest stable release.
7. Update `CHANGELOG.md` and verify the README still matches shipped behavior.
