# StreamSnip AI - QA Report

**Test date:** 24 November 2026
**Environment:** Windows local app, Python engine + React/Vite dashboard

## Result

- Backend test suite: **133 passed**
- Frontend build: **passed**
- Frontend lint: **0 errors, 10 React hook warnings**
- Browser navigation: **14 of 14 routes loaded**
- UI interaction suite: **40 of 40 checks passed**
- Responsive layout: **28 of 28 route/viewport checks passed** at 320px and 375px
- Read-only API checks: **all checked endpoints returned HTTP 200**
- Favicon: **HTTP 200**
- Real clip TXT sidecars: **4 of 4 returned HTTP 200**
- Unauthenticated write check: **HTTP 403**, as expected

## Features exercised

Dashboard customization and panel visibility; live/VOD source-mode controls; simulated main-session start, graceful stop and immediate stop; simulated creator addition, start/stop, VOD watcher, folder actions and removal; ten-slot capacity display and 11th-slot guard; all four layout modes; canvas dragging; layout preset save/apply/delete; source-frame capture handler; layout save handler; clip selection, clear selection, filtering, details modal, metadata save; published view rendering; recording/output folder picker handlers; bitrate slider; hype-word editor; all five AI provider choices; Ollama model discovery handler; AI connection-test and save handlers; transcription provider selection; caption color/position controls; advanced subtitle controls; auto-post warning; activity pause/clear/resume; Help accordion controls; dark-mode persistence; global search navigation.

## Fixes made during QA

1. Corrected the clip-detail TXT sidecar link to use the actual `<clip-name>.txt` route rather than `<clip-name>.mp4.txt`.
2. Changed the AI settings metadata display to read **Always on**, matching the backend which always enables generated TXT post metadata.
3. Corrected narrow-mobile top-bar sizing. The full route set now passes at 320px and 375px without page-level horizontal overflow.
4. Updated the stale creator-monitor regression test to verify ten concurrent monitors and reject an eleventh, matching the current backend limit.
5. Added a favicon link to the dashboard HTML.

## Important test boundaries

UI write operations and actions that could affect real data were tested with a separate headless browser and mocked API responses. No actual live stream, VOD capture, creator monitor, AI vendor request, Zernio publish, clip deletion, or real settings/credential write was performed. The ten-active-monitor view was simulated in the browser; backend concurrency capacity was tested with mocked engines.

The sample files in the `out` folder were inspected without modifying them. `caption-test.mp4` is a valid 3-second H.264 sample. Three other sample MP4 files are only 5–10 bytes and are invalid placeholders (FFprobe reports a missing MP4 `moov` atom); they are not suitable for playback tests.

The ten lint warnings are React hook guidance warnings in existing code; lint reported no errors.
## UTF-8 display repair — 24 November 2026

- Repaired mojibake in the React workspace source (`dashboard/src/App.tsx`) and the embedded legacy dashboard / Python UI strings (`autoclip.py`).
- Restored readable punctuation, arrows, ellipses, keyboard glyphs and dimension separators; replaced unrecoverable placeholder glyphs with readable `N/A` or `x` text.
- Scanned project source files for common mojibake markers and replacement characters: **0 remaining source hits**.
- Live browser verification: **14/14 React routes passed** with zero visible mojibake/replacement characters and no browser errors; legacy root dashboard also passed.
- Production frontend build passed; Python compilation passed; backend test suite remained **133 passed**; lint reports 0 errors and 10 React hook warnings.
- The app was restarted using the project virtual environment. Loserfruit and Zerkaa creator monitors are currently active and recording; the main capture session is idle.
## Creator Studio publishing, shutdown and Live Studio tabs — 24 November 2026

- Added platform-aware publishing destinations for individual clips and batches. The picker filters to connected accounts and supports selecting one, several, or all connected platforms; the existing Zernio publishing API receives only the chosen platform/account IDs.
- Added a dedicated single-clip Publish control in the clip row and destination checkboxes in Clip Details.
- Added batch **Publish selected** and a confirmed **Publish all clips** action.
- Added a confirmed **Quit app** button wired to the existing protected `/api/quit` shutdown route. The UI reports that quitting stops the main capture and creator monitors.
- Split Live Studio into **Live capture** and **Monitoring** tabs. Creator monitor management, live monitor capacity, VOD folder watching, and the add-creator form are grouped under Monitoring.
- The default `/` route redirects into the React Creator Studio. The embedded classic UI stays in source as deprecated code and is no longer linked as a normal in-app destination.
- Validation after these changes: production frontend build passed; lint passed with 0 errors and 10 React hook advisory warnings; Python compilation passed; backend test suite **133 passed**.
- Runtime state check after server restart: main capture idle, active publishing idle, Loserfruit and Zerkaa profiles remain saved but are not running. No stream recordings were started by this UI validation.

## UI notifications and diagnostic logging — 24 November 2026

- Added a shared bottom-right notification stack for app API actions. Successful requests show an acknowledgement toast; failures show the action name and returned error. Notifications can be dismissed and expire automatically.
- Publishing toasts say the request was queued and direct the user to Activity for final platform outcomes; they do not claim that a social platform has finished publishing.
- Debounced settings autosaves stay quiet on success to avoid notification spam. Failed autosaves still show an error toast and are reported to the diagnostic log.
- Client action outcomes are recorded through a protected local diagnostic endpoint. Log entries store the API path and a short result message, not request bodies or credentials; common key/token/password patterns are redacted.
- Backend request validation errors and unexpected GET/POST handler exceptions are added to the same live log. Existing capture/render/creator/publishing workers continue to write their operational errors there as well.
- Activity now has **All events** and **Problems only** views with a problem count. The diagnostic log remains downloadable as a text file.
- Smoke checks: protected client-log endpoint wrote a UI event to the live log; invalid `/api/start` returned HTTP 400 and generated an `API VALIDATION ERROR` entry. The invalid request did not start capture. Temporary smoke-test entries were removed afterwards.
- Removed the redundant “Creator Studio is the primary interface” sidebar note; no legacy-interface link is exposed in the new workspace. The root route redirects into the React Creator Studio; classic UI remains only in source as deprecated code.
- Final UI production build passed; lint reports **0 errors** and 10 React-hook advisory warnings. Python compilation and backend test suite passed (**133 tests**).

## Follow-up QA verification ? 24 November 2026

This section supersedes the earlier lint-warning count above for the latest code state.

- Backend regression suite: **133 passed**.
- Frontend TypeScript production build: **passed**.
- Frontend lint: **0 errors, 0 reported diagnostics** across 6 source files and 116 rules. The asynchronous initial settings-hydration effect has a narrowly documented suppression because the analyzer follows its async callback as though it were a synchronous state update; the API-backed state updates occur after requests resolve.
- Python module compilation: **passed**.
- Fresh read-only HTTP smoke checks: **9 of 9 returned HTTP 200** (`/`, `/dashboard/`, `/dashboard/favicon.svg`, `/api/session`, `/api/state`, `/api/creators`, `/api/config`, `/api/publishing/status`, `/api/words`).
- Refactored dashboard layout and layout-preset hydration to initialize from browser storage instead of setting state synchronously in effects. Clip-tab selection now resets with route identity; word-editor and publishing settings hydrate from their authoritative workspace data without effect-driven state copies.
- No live stream/VOD capture, creator-monitor start/stop, AI vendor request, credential write, clip deletion, or social publishing was triggered during this pass.
- Browser interaction and responsive suites were **not rerun in this follow-up pass**; the previously recorded 40/40 interaction and 28/28 responsive results remain historical results from the earlier QA run, not fresh verification of this change set.

## Browser, responsive and accessibility follow-up ? 24 November 2026

Fresh Chromium/Playwright verification against the running local app and the newly built production bundle:

- All **14 React routes** loaded with HTTP 200 and rendered their expected page heading.
- **56/56 route-and-viewport checks passed** across 1440?900, 1024?768, 768?1024, and 390?844. No horizontal document overflow was detected.
- **12/12 safe UI interaction checks passed**, covering the 19-theme chooser, Live Studio tab switching, creator monitor cards, Published navigation, clip search input, Activity filters, Settings subnavigation, and AI-provider choice controls.
- Accessibility-name heuristic: **0 unnamed buttons, links, inputs, selects, textareas, or tabs across all 14 routes**. Added explicit accessible names to the stream URL/file path, layout preset name, clip-library search, storage paths, capture bitrate slider, Zernio API key, and custom hype-word editor.
- Browser page exceptions: **0**. Browser console errors: **0**. Visible mojibake/replacement-character hits across the tested routes and their input placeholders: **0**. Broken images: **0** in the representative screenshot check.
- Updated detailed machine-readable results are in `browser_qa_followup.json`.
- No real capture, creator-monitor start/stop, credential save, AI-provider network test, clip deletion, or social publishing was triggered. The AI provider selector and theme chooser were exercised only in an isolated disposable browser context.
- Final regression pass after the accessibility changes: **133 backend tests passed**, frontend production build passed, Python compilation passed, lint returned **0 diagnostics**, and **9/9 read-only HTTP smoke checks returned 200**.

This verifies the UI routes, selected safe interactions, four viewport sizes, basic accessible naming, and local read-only endpoints. It does not claim exhaustive testing of every possible input combination or live third-party capture/transcription/render/publishing workflows.

## End-to-end media and integration follow-up ? 24 November 2026

Fresh tests using disposable local fixtures and local mock HTTP servers:

- **Real local speech transcription: PASS.** The installed `distil-large-v3` model ran on the NVIDIA RTX 3060 Ti (CUDA) and transcribed 12 words from generated speech in 1.96 seconds. All five target phrases were recovered.
- **FFmpeg layout rendering: 4/4 PASS.** Facecam + game, Blur background, Fill (crop center), and Selected crop each produced valid 1080?1920 MP4 output with audio and a matching TXT metadata sidecar.
- **Output formats: 4/4 PASS.** Verified 9:16 (1080?1920), 16:9 (1920?1080), 1:1 (1080?1080), and 4:5 (1080?1350).
- **Full local VOD-to-clip pipeline: PASS.** A disposable 12-second speech video passed through actual local Whisper transcription, built-in highlight scoring (best score 100), FFmpeg rendering, and metadata generation. One 5.01-second 1080?1920 clip and its TXT sidecar were produced; the source VOD was preserved.
- **Custom OpenAI-compatible AI integration: PASS against local mock server.** Connection testing and highlight-analysis response parsing worked; the status result did not expose the test secret.
- **Zernio publishing workflow: PASS against local mock server.** Connected-account discovery, media presign, binary upload, and post-submission payload construction all succeeded. The test server was local; **no real social post was created and no external network call was made**.
- **Live capture remains unverified.** An isolated local HLS/Streamlink discovery probe stalled. Its test process and child were terminated. This was not a real Twitch/YouTube stream, and no user recording was started.
- **Live app state after testing:** main capture idle; zero active creator monitors; two saved creator profiles; Zernio currently reports not configured.
- Final regression after the tests: **133 backend tests passed**, Python compilation passed, frontend lint returned **0 diagnostics**, production build passed, and **9/9 read-only HTTP endpoints returned 200**.

The machine-readable details are in `end_to_end_qa.json`. These results validate local transcription, clip production, layout/format rendering, and the AI/publishing request paths under mocks. Real live-stream capture and real third-party account authentication/publishing remain outstanding and are not represented as passed.


## Twitch live-detection and runtime audit — 24 November 2026

- Reproduced the intermittent `AssertionError: SRE module mismatch` seen in the monitor logs and traced the cause to interpreter mixing: the app could select a Streamlink executable installed under Python 3.14 while injecting Python 3.11 paths through `PYTHONPATH`.
- Fixed Streamlink executable discovery to prefer the current interpreter's `Scripts` directory, and stopped injecting the app's import paths into standalone Streamlink processes.
- Verified the fix from the system Python 3.11 launcher: it selected the Python 3.14 Streamlink executable without a foreign `PYTHONPATH`, and Streamlink successfully resolved a playable Twitch stream URL for the saved `Zerkaa` channel.
- Started the saved Zerkaa creator monitor through the local app API. The app confirmed `phase=recording`, `running=true`, and 86 MB captured at the follow-up check. The live monitor remains active; no publishing action was triggered.
- Regression suite after the fix: **135 passed**. Python compilation passed. The React production build passed and frontend lint reported **0 warnings and 0 errors**.
- This verifies live stream discovery and the active recording path for Zerkaa on this machine. It does not claim that a rendered clip or social post has completed; the next clip batch was still pending at the time of the check.

## Full frontend/backend and metadata QA — 24 November 2026

- Rebuilt the React production dashboard successfully; frontend lint returned **0 warnings and 0 errors**. Python compilation passed for the application, AI, metadata, browser automation, and publishing modules.
- Backend regression suite: **144 passed**.
- Browser UI checks against a disposable local test server: **15/15 navigation destinations passed**; all **19 themes** applied and persisted, with 19 distinct background/text color pairs; clip search and empty-state text passed; saved clip preview and visible Delete control passed with **51 saved clips** discovered; Publish editor showed all four manual destinations and a visible Post action; responsive checks passed at 1440, 1024, 768, and 390 px; **0 browser page or console errors**.
- Browser engine launch smoke test: **Firefox, Chrome, and Edge 3/3 passed** using their installed runtimes. This verified browser launch and local page rendering only; it did not sign in to social accounts or test a real platform upload.
- Runtime API smoke test after a clean application restart: dashboard, state, configuration, creators, publishing status, browser status, and word-list endpoints returned HTTP 200. The browser-status API now distinguishes Playwright package availability from an actually open automation session.
- Confirmed application state after restart: main capture idle; Zerkaa and Loserfruit monitors stopped; no Streamlink/FFmpeg Twitch recording process active. Existing clips and metadata files were preserved; no clip deletion or social publishing was performed.
- Reviewed **51 existing Zerkaa clip metadata sidecars**. A static audit found 13 descriptions with two transcript quotations, 5 titles longer than 70 characters, and 3 titles matching intro/garbled-speech patterns.
- Reworked the transcript-only fallback to ignore obvious intros/call-to-action fragments, remove common speech fillers and repeated words, prioritize specific complete actions, use one opening quote plus a concise topic-based context sentence, and produce a neutral topic title with an explicit review note when the transcript is too unclear. Low-confidence fallback copy now produces an activity-log warning before the clip is posted.
- Existing sidecars were **not rewritten** because they only retain short transcript excerpts, not the full clip transcript. The improved fallback applies to newly rendered clips. Regenerate old sidecars only when a reliable full transcript or a configured text-generation provider is available.
- Current local AI configuration remains **Hooks**; no Gemini API key is saved and the local Ollama endpoint is unavailable. Therefore the new fallback is deterministic transcript-based copy, not a claim of live Gemini-generated copy. The Gemini/Ollama/hosted metadata network path was not exercised in this pass.
- No real YouTube, Instagram, Facebook, or TikTok upload was performed. Platform-specific upload fields still require live account/session testing. The final platform Publish button remains under the user's control.

## Default-browser publishing correction (24 Nov 2026)

- Removed Playwright from `requirements.txt` and uninstalled it from the local virtual environment.
- Replaced the dedicated persistent-profile launcher with a system-default URL open via Python's standard `webbrowser` module.
- Removed the browser picker and dedicated-profile wording from the Publish UI.
- The upload page opens in the normal default browser; the user manually selects the clip and pastes title/caption using the existing Copy controls. No claim of automatic file selection or metadata fill is made.
- Deleted the local `browser-profiles` directory created by the previous implementation/test.
- Windows default-browser detection resolves to Firefox (default) on this PC. A live smoke test returned success opening `https://www.youtube.com/upload` through the system default handler; Firefox processes were present afterward. The YouTube account's signed-in state could not be independently inspected from the remote session.
- Validation: 145 Python tests passed; dashboard production build passed; lint passed with 0 warnings and 0 errors.
