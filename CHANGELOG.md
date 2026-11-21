# Changelog

Notable StreamSnip AI changes are documented here. Complete release notes and downloadable assets are available on the [GitHub Releases page](https://github.com/sifat-jaman-13/stream-clip-ai/releases).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use semantic versioning.

## [Unreleased]

## [2.0.7] - 2026-11-22

### Added

- Added transcript-grounded AI post-copy generation using the selected Gemini, Ollama, or Hugging Face provider, with a single bounded request per completed clip.
- Added a UI toggle to enable/disable AI-written titles and descriptions for ScarClipScheduler.
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

[Unreleased]: https://github.com/sifat-jaman-13/stream-clip-ai/compare/v2.0.7...HEAD
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
