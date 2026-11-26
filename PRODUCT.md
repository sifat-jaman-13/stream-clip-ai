# Product

## Platform

Native Windows desktop application built with WinUI 3 and backed by a local Python media engine. The primary supported installation is Windows 10/11 x64. A React and TypeScript dashboard is maintained as a separate browser-oriented interface and development path.

## Users

Primary user: an individual creator or clip editor using a desktop PC to monitor stream sources, capture live content, process recorded VODs, review generated clips, and prepare short-form social posts.

## Product purpose

StreamSnip AI is a local-first creator clipping workspace. It connects source selection, live capture, creator monitoring, transcription, AI-assisted highlight analysis, facecam-aware framing, captioned rendering, clip review, metadata, and social publishing. Success means moving from a live moment or recorded VOD to a reviewed short while preserving user control over capture, media, settings, and the final publishing action.

## Positioning

A desktop media workstation that connects stream capture and creator monitoring to transcription, highlight selection, clip rendering, review, and publishing preparation. Local media processing remains on the user's computer. Hosted AI and social services are used only when configured and invoked by the user.

## Operating architecture

- **Native shell:** WinUI 3 owns the installed Windows desktop interface, navigation, native controls, and application lifecycle.
- **Local engine:** Python owns capture, creator monitoring, transcription orchestration, AI analysis, FFmpeg rendering, file operations, and publishing integration.
- **Local transport:** FastAPI exposes engine services over loopback only. The native shell starts and supervises the Python process and uses the per-process session token for state-changing requests.
- **Browser interface:** The React/Vite dashboard remains a separate browser-oriented frontend and developer workflow; it is not the installed WinUI 3 shell.
- **Storage:** Installed application settings, engine configuration, and the clip library live under the user's local application data. User data must not be included in source-control or installer build artefacts unless explicitly intended.

## Publishing and external services

Publishing is handled exclusively through the configured Zernio integration and its connected **Facebook, Instagram, and YouTube** accounts. TikTok is not supported by this integration.

StreamSnip discovers all supported accounts returned by Zernio and provides an individual posting-enabled control for each account. It does not impose its own API-key connection count, per-platform account slots, or posting quota. Zernio and the connected social platforms determine account availability and posting limits. Different keys can belong to the same Zernio billing workspace and therefore share its request allowance; a distinct key does not prove an independent budget.

Workspace request throttling, account-specific posting caps, and upstream platform errors are handled separately. Publishing results are checked per destination; only confirmed successful destinations are added to the Published registry. A stable idempotency key is reused for retries of the same logical post.

## Capabilities and constraints

- The native application includes Dashboard, Live Studio, Creators, Clip library, Published, Hype words, Publishing, Settings, Activity, Help, and About.
- Live Studio groups Source, Capture, AI provider, Transcription, and Captions into pre-capture setup.
- Capture never begins automatically when a page opens; it requires an explicit user action.
- Creator profiles support independent live monitoring and recorded-VOD folder watching.
- Faster-Whisper and YuNet run locally when their dependencies and model assets are installed.
- Hosted AI providers receive transcript text when selected; local Hook Words and a local Ollama instance are alternatives.
- Provider availability, connected social accounts, and publishing outcomes depend on external configuration and responses.
- The local API must remain bound to loopback and must not be exposed to an untrusted LAN or the public internet.
- Preserve API contracts, user data, credentials, and operational behavior when changing the frontend or native host.
- Do not invent engine state, processing progress, clip content, provider success, or posting status.

## Brand and appearance

- Product name: StreamSnip AI.
- Default visual system: Odysseus graphite with cyan information accents and coral actions.
- The React interface has multiple curated themes and font choices; JetBrains Mono is the default.
- The native interface mirrors the core semantic palette and typography.
- The interface is an original creator workspace informed by familiar creator-studio patterns, not a pixel copy of another product.

## Product principles

- Keep capture state and destructive actions explicit and understandable.
- Make the journey from source to reviewed clip direct and predictable.
- Preserve user control over monitoring, recording, and publishing.
- Surface real engine state and actionable errors rather than decorative metrics.
- Keep the workspace responsive and usable during long-running local processing.
- Explain when transcript text is sent to a hosted AI provider.

## Accessibility

Use semantic controls, visible keyboard focus, sufficient contrast, labelled inputs, keyboard-operable tabs, and reduced-motion support. Status must be conveyed through text or icons as well as color.
