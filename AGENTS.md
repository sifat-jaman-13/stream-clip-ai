# StreamSnip AI — engineering rules

## Current application architecture

StreamSnip AI 4.1.0 is a Windows desktop application built from one React/TypeScript interface, one FastAPI/Python processing backend, and a pywebview shell hosted by WebView2. The installer is built with PyInstaller and Inno Setup.

- React/Vite in `dashboard/` is the only application UI.
- FastAPI in `api_server.py` adapts the existing Python application services; it is not a second processing engine.
- Python modules own capture, creator monitoring, transcription, AI analysis, framing, rendering, storage, and publishing.
- `desktop_shell.py` hosts the React build in the native desktop window.
- `build_installer.ps1` and `installer/StreamSnipAI.iss` produce the Windows installer.
- There is no WinUI/C# application or .NET build in the current product.

Do not reintroduce a second UI, backend, installer path, or platform-specific duplicate of existing application behavior without an explicit product requirement.

## UI design and review

Before changing UI, read `DESIGN.md`, inspect the current source, and inspect the rendered application. Use the user's design reference: https://github.com/sifat-jaman-13/chatgpt-design-skills

StreamSnip is an operational media workstation. Prioritize readable controls, reliable states, clear hierarchy, preview quality, and efficient clip review over decorative panels or marketing effects.

- Preserve the current product identity and working behavior.
- Use semantic theme tokens; keep status colors independent of the user-selected accent.
- Choose text colors using WCAG relative luminance. Target at least 7:1 for primary text and 4.5:1 for body, muted, and button text on their actual surfaces.
- Keep labels and essential instructions readable at normal desktop scale.
- Use purposeful motion; animate transform and opacity where practical, avoid layout shifts and `transition: all`, and respect `prefers-reduced-motion`.
- Provide keyboard-visible focus, accessible labels, and useful loading, disabled, success, and error states.
- Do not change capture, transcription, AI, rendering, creator monitoring, storage, or publishing behavior during visual-only work.
- After palette changes, run `python dashboard/tools/audit-theme-contrast.py`.

## Build and verification

Run the checks relevant to the change:

- React: `npm ci`, `npm run lint`, and `npm run build` from `dashboard/`.
- Python: `python -m pytest -q` from the repository root.
- Installer: `./build_installer.ps1` on Windows with Python 3.10+, Node.js 22, and Inno Setup 6 available.

The Windows installer workflow should build on pushes and pull requests to `master`, not only when a release tag is created.

## Safe collaboration

- Inspect `git status` before editing and preserve all unrelated working-tree changes.
- Make focused edits and re-read changed files before testing.
- Never reset, clean, overwrite, or stop another contributor's process to make a change.
- Never delete user data, local recordings, clips, creator folders, settings, credentials, or local databases as repository cleanup.
- Never commit API keys, social tokens, cookies, private browser profiles, or machine-specific runtime data.
- Do not run real publishing tests unless a real public or scheduled post is explicitly intended.
