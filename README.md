# StreamSnip AI

**Capture live streams. Find the moments. Make the clips. Publish without leaving your workspace.**

[![Latest release](https://img.shields.io/github/v/release/sifat-jaman-13/stream-clip-ai)](https://github.com/sifat-jaman-13/stream-clip-ai/releases)
[![Windows](https://img.shields.io/badge/platform-Windows-2563eb)](https://github.com/sifat-jaman-13/stream-clip-ai)
[![Tests](https://github.com/sifat-jaman-13/stream-clip-ai/actions/workflows/tests.yml/badge.svg)](https://github.com/sifat-jaman-13/stream-clip-ai/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/license-proprietary%20non--commercial-orange)](LICENSE)

StreamSnip AI is a local-first clipping studio for streamers and creators. Capture Twitch and YouTube streams, process recorded videos, transcribe speech, find high-potential moments, render captioned clips, review them, and publish through connected social accounts.

- **Stable release:** 3.0.0
- **Next major update:** 4.0 is in active development in this repository. The roadmap below describes the work being integrated; it is not a claim that a new installer has already shipped.
- **Project site:** https://sifat-jaman-13.github.io/stream-clip-ai/

## The next major update — StreamSnip AI 4.0

The 4.0 update is focused on making StreamSnip a creator operations workspace, not just a clip generator.

### Direct publishing is the priority

- Publish a reviewed clip directly from StreamSnip through Zernio.
- Choose connected accounts and platforms for each post.
- Edit the title, description, and hashtags before publishing.
- See upload progress and failures in the app.
- Successful immediate Zernio posts move automatically into a persistent **Posted** tab; after manual uploads, click **Mark as posted** to move the clip there.
- Delete a clip individually, delete selected clips, or delete everything in the current Clips / Posted tab after confirmation.
- Keep manual upload links as a fallback when a creator prefers native platform publishing.
- Auto-post remains opt-in. It is off by default.

The development integration supports connected Zernio social accounts for Instagram, TikTok, Facebook, YouTube, X, LinkedIn, Pinterest, Reddit, Bluesky, Threads, and Google Business, subject to the account permissions and each platform's media rules.

### Live monitor comes first

- Keep a simple single-source Start/Stop capture control at the very top of the workspace.
- Add multiple creators and control each one independently.
- Each creator has their own Start Live and Stop Live controls, just like the single-source workflow.
- Monitor stream state and processing status without stopping other creators.
- Capture up to two live sources concurrently by default; transcription, AI analysis, and rendering share a resource-controlled processing queue.
- Temporary live recording chunks are automatically deleted after a completed analysis when clips were rendered or no worthwhile moment was found. If every render fails, the source is kept for retry.

### Live and recorded VODs never mix

Every creator receives an isolated folder tree:

~~~text
Creators/
  Creator_Name_ID/
    Live/
      Recordings/
      Clips/
    Recorded_VODs/
      Watch_Inbox/
      Clips/
      Processed_Originals/
      Failed/
~~~

Turn on Watch VOD folder for a creator and drop a completed recording into that creator's inbox. StreamSnip waits for the copy to finish, processes the VOD, saves its clips separately, and archives the original. Live clips and recorded-VOD clips remain separate.

### Bring your own transcriber

- Built-in faster-whisper remains the local default.
- Choose a custom command-line transcriber or script instead.
- Pass the source file, output JSON path, and language through placeholders.
- No StreamSnip API key is required for a local transcriber. If your own tool uses a cloud service, its credentials stay with that tool.

### Profanity is a creator choice, not a clip rejection rule

The optional censor can mute detected words and mask captions or generated post copy. It does **not** remove a clip, lower its viral score, or prevent publishing. The original transcript is used for highlight scoring, so strong reactions and memorable language are still considered. Turn censoring off before rendering when you want the original audio and words; re-render existing clips after changing the setting.

## What StreamSnip does

- Capture supported Twitch and YouTube live streams.
- Process complete local video files and recorded VODs.
- Transcribe locally with faster-whisper, or use a custom transcriber command.
- Analyze transcript windows from 3 to 15 minutes while still processing the full recording.
- Use Hook Words, Ollama, Gemini, Hugging Face, or a custom OpenAI-compatible chat-completions provider for highlight analysis.
- Apply a configurable viral-score threshold; scores are estimates, not guarantees of reach.
- Render portrait, landscape, square, and 4:5 clips with customizable crop, layout, captions, and subtitles.
- Generate transcript-grounded titles, descriptions, and hashtags.
- Review and play clips before sharing; the main gallery includes local clips plus each creator's Live and Recorded VOD clips.
- Publish any gallery clip directly through Zernio when connected, or open native upload pages and copy post text manually.
- Track successfully posted clips in a persistent Posted tab, separate from clips still waiting for review or publishing.
- Delete individual clips, selected batches, or all clips in the current tab.
- Keep recordings, clips, AI settings, and credentials in local folders.

## API keys and privacy

The core local workflow does not require an API key:

| Feature | Credential requirement |
| --- | --- |
| Local capture, clipping, FFmpeg rendering | No StreamSnip API key |
| Built-in faster-whisper transcription | No API key; speech models must be available locally |
| Custom local transcriber | No StreamSnip API key; your transcriber may have its own requirements |
| Ollama | Local service; no cloud API key |
| Gemini / Hugging Face / custom hosted AI | The selected provider may require its own key or token |
| Direct social publishing | Zernio API key and connected social accounts |

Credentials are stored in local app settings and are not sent to the browser UI. Do not commit settings files, tokens, API keys, recordings, or generated clips to Git.

Hosted AI providers receive the transcript text needed for analysis and post-copy generation. Choose local Hook Words or Ollama if you do not want to send transcripts to a hosted AI provider. Stream capture and Zernio publishing require an internet connection.

## Bring-your-own transcriber format

Choose **Bring your own transcriber · CLI / script** in Speech settings.

The command supports these placeholders:

- {input} — absolute path to the source video or audio file.
- {output} — temporary JSON output path.
- {language} — selected language value, defaulting to auto.

Example command for whisper.cpp:

~~~text
whisper-cli -f "{input}" -oj -of "{output}"
~~~

The transcriber can write JSON to the output file or print JSON to stdout. The preferred format is:

~~~json
{
  "words": [
    { "start": 0.10, "end": 0.48, "word": "hello" },
    { "start": 0.50, "end": 0.82, "word": "there" }
  ]
}
~~~

A segment-based format is also accepted:

~~~json
{
  "segments": [
    { "start": 0.0, "end": 2.4, "text": "Hello there, welcome back." }
  ]
}
~~~

Word timestamps are best for accurate subtitles and censor timing. Segment-only output is accepted by distributing words evenly across each segment duration, so its word timing is approximate. Commands are launched without a shell; use an executable and arguments rather than shell operators or pipes. Do not paste API keys into the command field because the command is shown in the local UI; use environment variables or your transcriber's own secure local configuration instead.

## Direct publishing and manual fallback

For direct publishing:

1. Open Settings and save your Zernio API key.
2. Identify connected social accounts.
3. Select the account to use for each platform and save.
4. Open a clip's Post dialog, edit its title and description, choose destinations, and select Publish via Zernio.

The app uploads the clip to Zernio and submits the selected accounts. Publishing may fail when an account is disconnected, lacks permissions, or the clip does not meet a platform's media requirements. Check the posting log and the platform's status before retrying.

Manual fallback opens the platform's upload page and copies title/description text. The user must attach the local video and press Publish. Websites do not allow StreamSnip to silently attach a local file or control another site's authenticated form.

## Local folder layout

Creator-specific paths are created under the app's data directory:

- Live recordings: Creator / Live / Recordings
- Live clips: Creator / Live / Clips
- Recorded VOD inbox: Creator / Recorded_VODs / Watch_Inbox
- Recorded VOD clips: Creator / Recorded_VODs / Clips
- Processed originals: Creator / Recorded_VODs / Processed_Originals
- Failed VODs: Creator / Recorded_VODs / Failed

The regular single-source workflow also uses the configured recording and output folders. Existing files are not automatically deleted when you remove a creator profile.

## Install on Windows

Download the latest published installer from [GitHub Releases](https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest).

The installer is unsigned. Review the release notes and SHA-256 checksum before running it. Keep the support terminal open while StreamSnip AI is running. Use **Quit** inside the app and wait for shutdown before closing the terminal; closing the terminal directly may interrupt recording, processing, or uploads.

## Run from source

Requirements: Windows, a supported Python version (3.10–3.12 for the packaged setup), FFmpeg, and the Python packages in requirements.txt.

~~~powershell
git clone https://github.com/sifat-jaman-13/stream-clip-ai.git
cd stream-clip-ai
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python autoclip.py
~~~

If FFmpeg is not on PATH, install it and restart the terminal. The Windows setup script can prepare the app's isolated runtime and speech-model cache.

## Development and tests

Run the complete regression suite:

~~~powershell
python -m pytest -q
python -m py_compile autoclip.py ai_highlights.py post_metadata.py zernio_poster.py
~~~

The classic browser UI is embedded in autoclip.py. To syntax-check its inline JavaScript, extract the final script block and run node --check on it. The separate React dashboard preview lives in [dashboard/](dashboard/); follow [dashboard/README.md](dashboard/README.md) for its Vite development server and local API proxy. After npm run build, the Python HTTP handler serves the React dashboard at /dashboard/ while preserving the classic interface at /. GitHub Actions runs the automated test matrix.

Do not run a real publish test against a creator's connected accounts unless you intend to create a public or scheduled post. Account-list and credential checks are safe read-only integration tests; publishing creates an external side effect.

## Project status

StreamSnip AI is actively developed. The 4.0 roadmap is being integrated and tested before a new installer or tagged release is announced. See [Issues](https://github.com/sifat-jaman-13/stream-clip-ai/issues), [Discussions](https://github.com/sifat-jaman-13/stream-clip-ai/discussions), and the [project site](https://sifat-jaman-13.github.io/stream-clip-ai/) for updates.

## Licence

This repository uses a **Proprietary Non-Commercial Use Licence**. It is source-available, not an OSI-approved open-source licence. Personal, private, and individual educational use is permitted under the licence. Commercial use requires prior written permission. Read [LICENSE](LICENSE) before using or redistributing the software.

---

Built by [Sifat Jaman / ScarZero](https://github.com/sifat-jaman-13).
