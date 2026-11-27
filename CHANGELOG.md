# Changelog

## [4.0.9] - 2026-11-27

### Changed
- Promoted Studio Dark to the default appearance in the native app, browser Creator Studio, and public website.
- Kept all 12 curated themes available; saved theme selections remain selectable and are preserved.
- Updated the product screenshots across the README, user guide, and public website to match the Studio Dark 4.0.9 interface.
- Added bundled Inter, Open Sans, IBM Plex Sans, Roboto, and Source Sans 3 font options alongside JetBrains Mono, Segoe UI, and Consolas in the native app and browser Creator Studio.
- Corrected appearance-setting navigation to rebuild the Settings page instead of appending duplicate views; persisted Small, Medium, and Large text sizes now apply consistently.

### Verification
- Studio Dark contrast: primary 15.72:1, body 12.22:1, muted 7.64:1, quiet 5.14:1, accent text 4.77:1.
- Theme parity: all 12 palettes match across React, CSS, and WinUI.
- Full Python tests, frontend lint/build, Windows Release build, screenshot review, and installer workflow verified before release.

## [4.0.8] - 2026-11-27

### Added
- Reworked Zernio publishing into five fixed, equivalent API-key connection slots in the native Publisher and browser Creator Studio.
- Added immediate per-clip Zernio publishing and an explicit Auto schedule action for all ready clips.
- Added a persistent Scheduled registry that separates provider-confirmed future posts from completed posts while keeping both visible in Scheduled history.

### Fixed
- Clips leave the ready-to-review list only after Zernio confirms a scheduled or published destination.
- A zero-minute Auto schedule interval now defaults to five minutes between clips; the per-clip Post action always publishes immediately.
- Enforced the five-connection limit in the local backend and clarified that multiple keys can still share Zernio team quotas.
- Preserved Scheduled and Posted registry state when deleting clips and updated the Publisher/Scheduled documentation.

### Verification
- Full Python regression suite, frontend lint and production build, and Windows Release build verified before release.
- Zernio scheduling and failure-state regression tests cover confirmed and rejected provider outcomes.

## [4.0.7] - 2026-11-27

### Fixed
- Keep the generated WinUI XAML PRI resource index in Release builds and stop installer compilation when it is missing.
- Repair the Live Studio page-render failure caused by missing native XAML resources in the previous installer.
- Keep Dashboard session details and progress controls current as captures start, advance, and stop.
- Preserve the engine-retry notice while navigating between pages.
- Make configuration-preserving uninstall recoverable across retries and retain dependency ownership state until cleanup succeeds.
- Replace the stale 4.0.5 error screenshot with screenshots captured from the corrected native application.

### Verification
- Windows Release build includes `StreamSnip.Desktop.pri` and the native application launches.
- Live Studio, Dashboard, Creators, Clip Library, and Publishing pages render without the prior page-render diagnostic.
- Native installer/uninstaller regression tests, config-restore functional tests, and release metadata checks pass.

## [4.0.6] - 2026-11-26

### Added
- Rebuilt the public GitHub Pages website around real native WinUI 3 product screenshots and a clearer download path.
- Replaced the repository README with a structured product and technical guide, including current publishing destinations, install verification, local-first boundaries, and developer instructions.
- Consolidated bundled third-party notices under licenses/third-party/ and documented the exact scope of each notice.

### Fixed
- Removed an unrelated NeonClipping licence notice; StreamSnip's caption treatment is independently implemented.
- Kept the YuNet MIT notice for the bundled face-detection model and the JetBrains Mono OFL notice for the bundled font, without attributing StreamSnip's own detection/framing logic to either.
- Synchronized the application version across Python metadata, the native desktop UI, the package manifest, and installer defaults.

### Verification
- 257 Python tests passed, including 8 subtests.
- Frontend lint and Vite production build passed; the native WinUI 3 application publish succeeded.
- The tagged Windows release workflow compiles the Inno Setup 6 installer and attaches its matching SHA-256 checksum.

## [4.0.4] - 2026-11-25

### Fixed
- Live Studio associates captures started from a saved creator with that creator's ID and routes new recordings and clips into the creator's dedicated folders.
- Creator status distinguishes foreground Live Studio capture from the separate background-monitor worker, including legacy live sessions matched by their saved channel URL.
- Creator activity counts include active Live Studio captures, and each creator row links back to its active session without confusing it with a background monitor.
- Prevented the same saved creator from being recorded simultaneously by a Live Studio capture and a separate background-monitor worker.

### Verification
- 188 Python tests passed, including 8 subtests; all four focused creator regressions passed.
- Frontend lint reported 0 warnings and 0 errors; TypeScript and Vite production build passed.
- Windows installer compiled successfully; installed 4.0.4 API health and creator records verified.

## [4.0.3] - 2026-11-25

### Fixed
- Python discovery now considers all registered and commonly installed stable 64-bit Python interpreters from 3.10 onward, orders them newest-first, and validates real StreamSnip dependency resolution in a disposable virtual environment before selection.
- Skips a Python version when the current Windows dependency stack cannot resolve its required wheels (currently Python 3.15 is skipped because ONNX Runtime has no matching Windows distribution); selects the newest compatible installed Python instead.
- When no compatible system interpreter exists, installs verified Python 3.14.10 privately under the StreamSnip install directory without changing global Python installations or PATH.
- Rebuilds the app virtual environment when the selected Python major/minor changes, preserving the previous runtime until the new dependencies and speech-model checks succeed. Failed migrations restore the previous runtime.
- The app-local Python fallback is removed by the StreamSnip uninstaller; user-installed system Python versions are never claimed or removed.

### Verification
- 184 Python unit tests passed, including both Gemini retry/rotation tests and installer/launcher regression coverage.
- Python compilation passed; frontend lint reported 0 warnings/errors; TypeScript and Vite production build passed.
- PowerShell setup script parsed successfully, real Windows discovery selected Python 3.14.10 after rejecting 3.15.2 for its unavailable Windows ONNX Runtime distribution, and the 4.0.3 Windows installer compiled successfully with Inno Setup 6.7.3.

## [4.0.2] - 2026-11-25

### Fixed
- Moved dependency installation and speech-model verification to the install/repair workflow only. Normal desktop shortcut launches now start the prepared app runtime directly and do not rerun setup or model checks.
- The installer runs one-time preparation without launching the app from the setup script, then offers a separate post-install launch action.
- The console launcher now directly supervises the installed Python app process and exits with it, preserving reliable shutdown without running the setup script on every launch.

### Verification
- Added regression checks that the normal launcher starts the preconfigured runtime directly, waits for the app process, and never invokes the setup script. Installer entries explicitly run one-time preparation and then launch the app.

## [4.0.1] - 2026-11-25

### Fixed
- Closing the Creator Studio window now releases its specific server-side window lease immediately rather than depending only on a streaming connection teardown. Late stream starts cannot resurrect a window after its close request, and closing one of multiple windows does not stop the remaining session.
- Shortcut launches keep the backend attached to the supervised StreamSnip support-console session. The support console exits when the app exits instead of allowing the application process to become a detached background service.
- Added `api_server.py` to the Windows installer payload and setup preflight; the installed source now includes the FastAPI module imported by the engine.

### Verification
- 183 Python unit tests passed, including named lease registration/release, close-before-stream-start races, multi-window behavior, React Creator Studio lifecycle wiring, Gemini retry/rotation, and Windows installer checks.
- Frontend lint reported 0 warnings/errors; TypeScript and Vite production build passed.
- PowerShell setup script parsed successfully; the Windows launcher compiled and Inno Setup 6.7.3 produced the 4.0.1 installer with `api_server.py` included.

## [4.0.0] - 2026-11-25

### Added
- Added direct per-clip Zernio publishing from the clip dialog, including editable title/description, per-post destination selection, multi-platform account mapping, and manual native-upload fallback.
- Expanded Zernio account discovery and publishing targets to connected social accounts across Instagram, TikTok, Facebook, YouTube, X, LinkedIn, Pinterest, Reddit, Bluesky, Threads, and Google Business.
- Kept the simple single-source live Start/Stop control at the top of the workspace and added independent Start Live / Stop Live controls to every saved creator.
- Added a per-creator custom transcriber option. Users can run a local executable or script with input/output/language placeholders and return timestamped word or segment JSON; local custom transcribers require no StreamSnip API key.
- Added custom transcriber JSON parsing for word-level output, segment-level output, and Whisper.cpp-style millisecond offsets.
- Added the multi-creator dashboard with independent live controls and separate Live and Recorded VOD folder trees, including per-creator watched VOD inboxes, output clips, processed originals, and failed archives.
- Added stable-file detection before a watched VOD is processed, preventing files that are still copying from being opened.
- Added a shared resource-controlled processing queue while allowing up to two stream captures concurrently.
- Unified the clip gallery across local, per-creator Live, and per-creator Recorded VOD outputs, with source labels and shared preview, download, delete, and direct-publish actions.
- Added automatic cleanup of temporary live recording chunks after successful clip rendering or a completed no-clip analysis. If all clip renders fail, the source recording is retained for retry; manually supplied VOD originals are never removed by this cleanup.
- Added a persistent Posted tab backed by a local registry. Immediate Zernio posts and opt-in auto-post successes move automatically; manual platform uploads can be marked posted by the creator. Scheduled posts are not marked as posted prematurely.
- Added per-clip delete, select-all across the entire current tab, delete-selected, and delete-all-current-tab actions for both Clips and Posted.
- Added automatic multi-frame facecam detection for live streams and local VODs, with separate editable facecam and gameplay regions.
- Added rendered MP4 output previews using the same crop, layout, and subtitle filter graph as final clips.
- Added six caption animation modes, the GTA Neon style, five caption-location presets, and cleaner default caption sizing.
- Expanded profanity matching and added word-level beep or mute processing for censored audio intervals.
- Raised the default and minimum live-recording video bitrate to 8,000 Kbps.
- Rewrote the README and updated the GitHub Pages site to announce the 4.0 roadmap, local-first credential requirements, creator workflow, and licence.

### Changed
- Direct publishing now supports per-post account selections and caption overrides without modifying the saved sidecar caption.
- Kept manual upload pages as a fallback; users still attach the local file and press Publish themselves.
- Changed profanity handling so the original, uncensored transcript is used for viral-moment scoring. Optional censoring only changes rendered audio, captions, and generated post copy; it never rejects a clip or blocks publishing.
- Clarified that no API key is required for local capture, local transcription, or rendering. Zernio credentials are only needed for direct publishing; hosted AI credentials are only needed when the user selects a hosted provider.
- Corrected package metadata to identify the proprietary non-commercial licence rather than MIT.
- Promoted the Creator Studio, multi-creator workflow, editing, framing, and publishing improvements to the 4.0.0 major release.

### Verification
- Windows PC: 177 unittest tests passed; Python compilation passed; frontend lint reported 0 errors; React production build passed; the 4.0.0 Windows installer compiled successfully.
- Compiled all application and test Python modules using the installed StreamSnip runtime.
- Verified embedded app and GitHub Pages JavaScript with Node syntax checks; parsed the landing page and confirmed there are no duplicate IDs or broken in-page anchors.
- Added regression coverage for live recording cleanup, retaining sources after render failures, persistent Posted state, and immediate-versus-scheduled Zernio posting callbacks.
- No real social post was created during this test run. A real live capture and long-duration VOD session still need a user-session acceptance test.

## [3.0.0] - 2026-11-22

### Major release

- Ships the transcript-grounded title and description generation overhaul as the 3.0.0 major release.
- Keeps gemini-3.1-flash-lite as the creator-copy default and honors the exact Gemini model saved in AI settings.
- Retries transient Gemini metadata failures once against the same selected model instead of silently switching Gemini models.
- Validates titles, quotes, and descriptions against the actual clip transcript; rejects generic clickbait, unsupported ownership or event claims, invented quotes, and generic filler.
- When Gemini is unavailable, attempts the installed Ollama model and then uses concise transcript excerpts rather than dumping the full transcript.
- Updates the Windows installer metadata, README version, and download site to 3.0.0.

### Verification

- Runs regression tests for Gemini model selection and retry, transcript grounding, quote validation, and safe fallback behavior.
- Windows installer is built from the same 3.0.0 source revision; see the GitHub release for the installer and SHA-256 checksum.

## [2.1.5] - 2026-11-22

### Changed

- Set `gemini-3.1-flash-lite` as the default Gemini model in new AI settings and preserve an existing explicit model selection.
- Keep post-metadata requests on the selected Gemini model; retry that model once rather than silently rotating copy generation to another Gemini model.
- When Gemini metadata generation fails, try the installed local Ollama model before falling back to short, exact transcript excerpts.
- Strengthen title and description prompts and validation to reject generic clickbait, unsupported claims, invented quotes, and transcript dumps.
- Replace the previous raw-transcript metadata fallback with a concise extractive title and short spoken-line excerpts.

### Tests

- Added coverage for the default/preserved Gemini 3.1 model, same-model retry, local Ollama fallback, grounding corrections, and concise fallback copy.
- Verified the regression suite on Windows and Ubuntu with Python 3.10 and 3.12.

## [2.1.4] - 2026-11-22

### Added

- Added a default-on profanity filter for timestamped transcripts.
- Matching words and phrases are masked in subtitles and generated clip metadata, while their audio intervals are muted in exported videos.
- Added an in-app switch and custom word/phrase list so creators can tune or disable filtering.

### Tests

- Added regression coverage for exact-token matching, custom phrases, preserved word timestamps, toggle behavior, and audio mute intervals.

## [2.1.3] - 2026-11-22

### Changed

- Rewrote the support-terminal startup message to clearly warn users to keep the terminal open while StreamSnip AI runs.
- Explained that users must click **Quit** inside the app and wait for shutdown before closing the terminal.
- Warned that closing the terminal directly may interrupt active recording, clip processing, or uploads.
- Updated the README and GitHub Pages site to describe provider-matched automatic titles/descriptions and the explicit safe-shutdown instructions.

Notable StreamSnip AI changes are documented here. Complete release notes and downloadable assets are available on the [GitHub Releases page](https://github.com/sifat-jaman-13/stream-clip-ai/releases).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use semantic versioning.

## [2.1.2] - 2026-11-22

### Changed

- Uninstall now removes the app-local Python virtual environment, pip dependencies, and downloaded Whisper speech models.
- Setup records whether it installed Python 3.12 or FFmpeg through WinGet; uninstall removes only those globally installed dependencies and leaves pre-existing tools alone.
- Existing clips, recordings, and local settings are retained.

### Tests

- Added verification for app-local dependency cleanup and dependency ownership tracking.

## [Unreleased]

## [2.1.1] - 2026-11-22

### Changed

- Clarified that Hugging Face authentication is optional and unauthenticated model downloads may be slower.
- Remember the first-run Hugging Face setup choice, including skipping it, so the launcher does not ask on every start.
- Save a supplied Hugging Face token in the existing local AI settings; users can add a token later from AI settings.
- Mask token entry so the credential is not echoed in the setup console.

### Tests

- Added coverage for preserving the one-time Hugging Face setup marker in AI settings.

## [2.1.0] - 2026-11-22

### Changed

- Simplified AI settings copy to describe automatic clip-title and description generation without third-party tool references.
- AI titles and descriptions are now generated automatically for every clip; the old on/off setting is ignored.
- Post-copy generation follows the same provider selected for highlight detection, with transcript-based copy retained for Hook words mode and provider failures.
- Removed the separate AI-copy toggle from the settings interface.
- Removed the end-card text overlay and synthetic CTA voice generation from settings and clip rendering.

### Tests

- Added regression coverage proving legacy opt-out settings cannot disable automatic copy generation and copy uses the selected highlight provider.

## [2.0.9] - 2026-11-22

### Changed

- Reworked the shared AI post-copy prompt for Gemini, Ollama, and Hugging Face to use the same creator-style format: catchy Title Case titles, relevant emojis, quote-led captions with explanatory context, creator credit, and ready-to-post hashtags.
- Added a style example based on the requested streamer-clip caption format and explicit safeguards against assigning one speaker's actions to another.
- Added validation to reject quote-only descriptions that omit the explanatory caption.
- Updated the AI settings hint and documentation to explain that the same writing instructions are provider-independent.

### Tests

- Added regression coverage for creator-style formatting, quote-only rejection, and ready-to-post hashtag output.
- Exercised live copy generation with the saved Gemini key and the installed local Ollama model llama3.2:3b; Ollama outputs that fail the copy checks use the safe transcript fallback.

### Changed

- Bumped StreamSnip AI to 2.0.9.

## [2.0.8] - 2026-11-22

### Fixed

- Added gemini-3.1-flash-lite as the dedicated lightweight fallback for AI post copy; it was verified to generate copy with the saved API credential. Highlight-analysis model selection remains unchanged.
- Gemini post-copy now makes at most one fallback request to the default model when the selected model is quota-limited, unavailable, or returns unusable JSON; invalid credentials are not retried.
- Tightened the prompt to favor sentence-case title openers accepted by the grounded-copy validator.

### Changed

- Bumped StreamSnip AI to 2.0.8.

## [2.0.7] - 2026-11-22

### Added

- Added transcript-grounded AI post-copy generation using the selected Gemini, Ollama, or Hugging Face provider, with a single bounded request per completed clip.
- Added automatic AI-written titles and descriptions for completed clips.
- Added strict title/description/hashtag validation, a transcript-based fallback, and a conservative sentence-case/proper-name check to reject unsupported locations or game titles.
- Per-clip TXT sidecars now contain clean post-ready copy; source filenames and timestamps remain in the internal `clips_metadata.txt` index.
- Added provider, format, validation, and renderer regression coverage for AI post metadata.

### Changed

- Bumped StreamSnip AI to 2.0.7 and included the new metadata module in source packaging, installer, and PyInstaller configuration.

## [2.0.6] - 2026-11-21

### Added

- Generated clips now receive matching TXT sidecars with a transcript-derived title on the first line and a full description below it, plus creator credit, hashtags, filenames, and source timestamps. A cumulative `clips_metadata.txt` index is also maintained.

## [2.0.5] - 2026-11-21

### Changed

- Relaxed Gemini's viral rubric to reward emotion, absurdity, irony, escalation, risky decisions, strong reactions, and memorable quotes—not only explicit payoffs.
- Returned sub-80 candidates for transparent scoring while keeping the user's configured threshold as the final clip gate.
- Reduced score dampening so Gemini's contextual judgment remains primary when speech recognition misses visual context.

## [2.0.4] - 2026-11-21

### Fixed

- Corrected Gemini rotation regression coverage for a backup model that succeeds before exhausting its retry budget.

## [2.0.3] - 2026-11-21

### Changed

- Gemini now performs two complete model-rotation rounds before Ollama fallback, staying on each model until all three attempts are exhausted.

## [2.0.2] - 2026-11-21

### Fixed

- Gemini quota/rate-limit errors now skip repeated attempts for the same model and rotate immediately to the next available model.

## [2.0.1] - 2026-11-21

### Added

- Added a persistent live diagnostic log with pause/resume, clear-view, and download controls in the web UI.
- Runtime logs are also saved to `streamsnip.log` in the app data directory for post-failure troubleshooting.

## [2.0.0] - 2026-11-21

### Added

- Activity logs now include the transcribed words for every processed chunk, capped to keep the UI responsive.
- Any processed recording chunk that produces zero clips is deleted immediately after processing.

### Changed

- Promoted the strict AI-only clipping workflow to the 2.0 release line.

## [1.2.14] - 2026-11-21

### Changed

- AI highlight providers are now strict: an empty, invalid, failed, or below-threshold AI result creates no clips and does not fall back to hook/audio peaks.
- In live mode, a chunk with no qualifying AI moment is deleted after processing to prevent ordinary footage from accumulating.

## [1.2.13] - 2026-11-21

### Fixed

- Moved Hugging Face token entry to the first interactive setup step and made the terminal prompt explicit, avoiding the installer-launched PowerShell input behavior that could silently skip the token.

## [1.2.12] - 2026-11-21

### Changed

- Made the Hugging Face token prompt prominent and explicit before speech-model downloads; token entry remains hidden and optional.

## [1.2.11] - 2026-11-21

### Added

- Windows setup now asks for an optional Hugging Face token with hidden input before downloading speech models, enabling authenticated downloads and higher Hub rate limits without writing the token to the setup log.

## [1.2.10] - 2026-11-21

### Fixed

- Fixed Windows PowerShell 5.1 setup quoting that corrupted the embedded speech-model bootstrap script before Python could run it.

## [1.2.9] - 2026-11-21

### Fixed

- Replaced shared Hugging Face snapshot loading with verified, app-owned Whisper model folders so a missing `model.bin` cannot repeatedly reopen a stale cache snapshot.
- The Windows installer now downloads and verifies every speech model from the app's model list before its first launch.

## [1.2.8] - 2026-11-21

### Fixed

- Made AI highlight scoring strict: Gemini and Ollama must provide an explicit score, receive a viral-moment rubric, and have each score conservatively calibrated against nearby transcript engagement before the configured viral-score floor is applied.

## [1.2.7] - 2026-11-21

### Fixed

- Resolved UI assets from both source-layout and installed-layout paths so the StreamSnip AI header logo and browser/app favicon load correctly from the Windows installer.
- Added regression coverage for the installer's sibling `source` and `assets` directories.

## [1.2.6] - 2026-11-21

### Added

- Added in-app controls to clear saved Gemini and Hugging Face credentials without editing local JSON files.
- Added cross-platform regression-test automation, issue forms, contribution guidance, and a private-reporting security policy.

### Changed

- Reworked the README to match current installation, AI provider, privacy, Docker, publishing, shutdown, and development behavior.
- Aligned the in-app About panel, package metadata, Docker branding, source documentation, and GitHub repository metadata with the StreamSnip AI project.
- Restored the standard MIT license text so repository tooling can identify it correctly.

### Security

- Clearing a saved Hugging Face token now also removes matching process environment values.
- Confirmed the previously exposed local Hugging Face token is rejected remotely, absent from reachable Git history, and removed from known local settings/environment locations.

## [1.2.5] - 2026-11-20

### Fixed

- Prioritized `gemini-3.8-flash` and migrated the retired `gemini-2.5-flash` setting.
- Added full Gemini text-model discovery and three attempts per model before Ollama fallback on retryable failures.
- Made the provider test exercise real text generation and report the successful model.
- Made Quit/app-window close stop the local server, recording/rendering work, and tracked child-process trees.
- Preserved safe page reloads with a reconnect grace period.

### Validation

- Added regression coverage for Gemini rotation, provider checks, process-tree shutdown, and app-window lifecycle.

## [1.2.4] - 2026-11-20

### Added

- New StreamSnip AI app icon and brand artwork.
- In-app Gemini/Hugging Face connection testing.

### Fixed

- Added clearer Zernio DNS diagnostics and retries.
- Updated the default Hugging Face hosted model and migrated the retired default.
- Applied the app icon consistently to the launcher and installer.

## [1.2.3] - 2026-11-20

### Fixed

- Corrected Windows Python detection when the `py` launcher exists without Python 3.12.
- Reused supported Python 3.10-3.12 installations and created an isolated app runtime.
- Improved FFmpeg discovery, PATH refresh, repeat launches, setup diagnostics, and installer completion.

[Unreleased]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v4.0.0...HEAD
[4.0.0]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v3.0.0...v4.0.0
[3.0.0]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v2.1.5...v3.0.0
[2.1.5]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v2.1.4...v2.1.5
[2.1.4]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v2.1.3...v2.1.4
[2.0.9]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v2.0.8...v2.0.9
[2.0.7]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v2.0.6...v2.0.7
[2.0.6]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v2.0.5...v2.0.6
[2.0.5]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v2.0.4...v2.0.5
[2.0.4]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v2.0.3...v2.0.4
[2.0.3]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v2.0.2...v2.0.3
[2.0.2]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v1.2.14...v2.0.0
[1.2.14]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v1.2.13...v1.2.14
[1.2.13]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v1.2.12...v1.2.13
[1.2.12]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v1.2.11...v1.2.12
[1.2.11]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v1.2.10...v1.2.11
[1.2.10]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v1.2.9...v1.2.10
[1.2.9]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v1.2.8...v1.2.9
[1.2.8]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v1.2.7...v1.2.8
[1.2.7]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v1.2.6...v1.2.7
[1.2.6]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v1.2.5...v1.2.6
[1.2.5]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v1.2.4...v1.2.5
[1.2.4]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v1.2.3...v1.2.4
[1.2.3]: https://github.com/sifat-jaman-13/stream-clip-ai/releases/tag/v1.2.3

### Metadata and cross-browser QA — 24 November 2026

- Reworked the transcript-only metadata fallback to remove common ASR fillers/repetitions, filter intro and subscribe boilerplate, rank complete specific moments, and avoid double-quoted transcript dumps in descriptions.
- Added a clear review note and an activity-log warning when the available transcript is too unclear to produce reliable post copy. Existing clip sidecars are preserved; the new logic applies to newly rendered clips.
- Clarified browser status: Playwright package availability is separate from whether an upload browser session is currently open.
- Fresh validation: **144 backend tests passed**, Python compilation passed, React production build passed, frontend lint reported 0 warnings/errors, all 19 themes and 15 navigation routes passed browser QA, and Firefox/Chrome/Edge launch smoke tests passed.
- No live recording, clip deletion, credential write, AI vendor request, or social post was triggered during this QA run.

## Default-browser manual posting (24 Nov 2026)

- Removed Playwright-based manual upload automation and all dedicated browser-profile creation.
- Manual Post now opens the selected platform URL through the operating system's default browser, preserving the user's ordinary browser profile and sign-in.
- Removed the browser picker and Playwright dependency. Video selection and metadata paste are manual; the final Publish click remains with the user.
- Added regression tests proving legacy browser selections are ignored and no profile directory is created.

## Zernio-only publishing cleanup (25 Nov 2026)

- Removed the legacy manual platform-opening and external-post marking flows; publishing is exclusively through Zernio.
- Removed obsolete browser automation packaging, API actions, UI styles, and documentation.
- Preserved Zernio account configuration, publishing callbacks, and existing clip/recording data.
