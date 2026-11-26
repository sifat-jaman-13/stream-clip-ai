---
version: 1
slug: "desktop-streamsnip-desktop-mainpage-xaml"
primary_target: "desktop/StreamSnip.Desktop/MainPage.xaml"
related_targets: ["desktop/StreamSnip.Desktop/MainPage.Live.cs","desktop/StreamSnip.Desktop/MainPage.Dashboard.cs","desktop/StreamSnip.Desktop/MainPage.Library.cs","desktop/StreamSnip.Desktop/App.xaml"]
---

# StreamSnip AI native desktop direction

THESIS
StreamSnip turns a Twitch/YouTube live source or VOD into reviewed, metadata-complete short clips. The interface must make the current source, the real processing phase, and the next safe action obvious.

OWN-WORLD
Preserve the user's explicit Odysseus visual reference: graphite #282C34 ground, #1B2028 main surfaces, #232B35 inset surfaces, cyan #9CDEF2 information, coral #E06C75 primary action, #355A66 structure, #E8F0F4 primary text, #C8D5DC body text, and semantic green/amber states. JetBrains Mono is the user's saved default; keep it consistent, but give the interface a real role-based type scale instead of rendering every sentence as the same tiny mono label. Use WinUI 3 / Windows Fluent native controls, keyboard focus and normal platform behavior. Color, type, density and one signature move only: no costume UI and no invented controls.

STORY
Build a broadcast rundown of the source-to-clip path. A single horizontal processing lane shows Source, Capture, Transcribe, Analyze, Render, Review and Publish. Its markers must reflect actual engine state: complete, current, waiting, failed, or unavailable. The lane is the signature move and must remain informative when idle. This is a working media app, not a decorative dashboard.

FIRST VIEWPORT
Open maximized on the user's 1920x1080 display. Keep the standard left navigation and top utility bar. The Dashboard opens with a strong page title and one clear route to Live Studio, followed by a prominent session/rundown area (real status and progress, never fabricated metrics), then a readable recent-clips list and a compact creator-monitor list. Remove the four-metric hero strip and same-weight stacks of decorative cards. Live Studio keeps one canonical source field and a genuinely useful 16:9 preview region on the left, the four existing setup tabs on the right, and explicit Start/Stop actions in a persistent lower area. Clip Library remains a review surface with real clip rows and a selected-item inspector. Settings remains app-wide storage and appearance only. All eleven existing destinations and all actions stay functional.

FORM
kind: assigned grounded direction
grounding: candidate 5 of seven creator-workspace directions
seed: 802ebfbc
fused raises: Crouwel grid discipline contributes precise alignment; warm consumer-surface discipline contributes plain-language labels and an action-only coral accent; the Saville reference contributes deliberate negative space without replacing the pinned Odysseus palette.
declined: exposure-sheet hatching is too specialized for a creator workstation; the ticket-wallet metaphor would costume standard settings and forms; the dense event-catalog grid belongs only as an optional Clip Library density, not as the global layout.
Audience: streamers and editors managing live capture, VOD processing, clips and publishing. Product clarity beats visual novelty whenever they conflict.

FINISH
Implement the native WinUI surface at full screen. Use the actual app state and real empty/error/loading states. Check contrast, 100% and 125% Windows scaling, 1920x1080 and a smaller desktop viewport, keyboard navigation, no active capture, and engine-unavailable state. Run the WinUI Debug and Release builds, the native Impeccable detector, and existing native/XAML tests. Inspect rendered WinUI snapshots of Dashboard, Live Studio, Clip Library and Settings before accepting the result.
