# Product

## Platform

Windows 10/11 desktop application using a single local-first application stack:

- Backend: FastAPI (Python), bound to loopback.
- Frontend: React + TypeScript + Vite. This is the only application interface.
- Desktop shell: pywebview hosting the same production React build in Edge WebView2.
- Processing: faster-whisper, FFmpeg, OpenCV/YuNet, and existing Python media services.

## Users

Primary user: an individual creator or clip editor using a desktop PC to monitor stream sources, capture live content, process recorded VODs, review generated clips, and prepare short-form social posts.

## Product purpose

StreamSnip AI is a local-first creator clipping workspace. It connects source selection, live capture, creator monitoring, transcription, AI-assisted highlight analysis, facecam-aware framing, captioned rendering, clip review, metadata, and social publishing. Success means moving from a live moment or recorded VOD to a reviewed short while preserving user control over capture, media, settings, and the final publishing action.

## Positioning

A desktop media workstation that connects stream capture and creator monitoring to transcription, highlight selection, clip rendering, review, and publishing preparation. Local media processing remains on the user's computer. Hosted AI and social services are used only when configured and invoked by the user.

## Operating architecture

- Desktop shell: pywebview creates the Windows window, supervises the Python process, and shuts it down when the user quits.
- Local engine: Python owns capture, creator monitoring, transcription orchestration, AI analysis, FFmpeg rendering, file operations, and publishing integration.
- Local transport: FastAPI exposes engine services over loopback only. The shell starts the service and uses the per-process session token for state-changing requests.
- Application interface: dashboard/ contains the only React/Vite UI. Browser development and the installed Windows app use the same frontend build.
- Storage: settings, engine configuration, and the clip library live under the user's local application data. User data must not be included in source-control or installer build artifacts unless explicitly intended.

## Publishing and external services

Publishing is handled exclusively through the configured Zernio integration and its connected Facebook, Instagram, and YouTube accounts. TikTok is not supported by this integration.

StreamSnip discovers all supported accounts returned by Zernio and provides an individual posting-enabled control for each account. It does not impose its own API-key connection count, per-platform account slots, or posting quota. Zernio and the connected social platforms determine account availability and posting limits. Different keys can belong to the same Zernio billing workspace and therefore share its request allowance; a distinct key does not prove an independent budget.

Workspace request throttling, account-specific posting caps, and upstream platform errors are handled separately. Publishing results are checked per destination; only confirmed successful destinations are added to the Published registry. A stable idempotency key is reused for retries of the same logical post.

## Capabilities and constraints

- The desktop application includes Dashboard, Live Studio, Creators, Clip library, Scheduled, Hype words, Publisher, Settings, Activity, Help, and About.
- Live Studio groups Source, Capture, AI provider, Transcription, Framing, and Captions into pre-capture setup.
- Capture never begins automatically when a page opens; it requires an explicit user action.
- Creator profiles support independent live monitoring and recorded-VOD folder watching. Each profile owns its facecam/game regions, video layout/aspect ratio, and caption appearance; AI/caption providers, clipping thresholds, and profanity filtering remain shared defaults.
- Faster-Whisper and YuNet run locally when their dependencies and model assets are installed.
- Hosted AI providers receive transcript text when selected; local Hook Words and a local Ollama instance are alternatives.
- Provider availability, connected social accounts, and publishing outcomes depend on external configuration and responses.
- The local API must remain bound to loopback and must not be exposed to an untrusted LAN or the public internet.
- Preserve API contracts, user data, credentials, and operational behavior when changing the application.
- Do not invent engine state, processing progress, clip content, provider success, or posting status.

## Brand and appearance

- Product name: StreamSnip AI.
- Default visual system: Studio Dark.
- Studio Light and Solarized Paper are the primary alternate palettes; additional palettes remain in the advanced appearance list.
- The appearance system is implemented once in React/CSS, not mirrored in XAML.
