---
name: StreamSnip AI Creator Studio
description: A desktop-first creator workspace for preparing stream capture, shaping clips, and publishing with a local media engine.
colors:
  app-bg: "#0f0f0f"
  surface: "#181818"
  surface-soft: "#212121"
  surface-hover: "#2b2b2b"
  sidebar-bg: "#0f0f0f"
  ink: "#f1f1f1"
  body: "#d6d6d6"
  muted: "#aaaaaa"
  line: "#303030"
  accent: "#ff0033"
  success: "#81c995"
  warning: "#f6c26b"
  danger: "#f28b82"
typography:
  family: "JetBrains Mono, monospace"
  weights: "400, 500, 600, 700"
  numerals: "Tabular for counts, durations, sizes, and progress"
layout:
  sidebar-width: "260px"
  topbar-height: "76px"
  studio-content: "Source first, pre-capture setup tabs, session status, persistent action bar"
rounded:
  controls: "8px"
  panels: "12px"
motion:
  easing: "cubic-bezier(.23, 1, .32, 1)"
  standard-duration: "150-220ms"
---

# StreamSnip AI Creator Studio - Design System

## Overview

StreamSnip AI is an operational creator workspace, not a marketing dashboard. Its main job is to let a creator prepare a capture session, monitor processing, review clips, and hand work to publishing.

The default visual direction is Studio Dark: near-black ground, restrained charcoal surfaces, vivid red actions, neutral high-contrast text, and semantic green/amber states. Preserve this exact user-selected palette. The native workspace should feel like a considered broadcast workstation: clear source context, a readable processing rundown, and obvious next actions. Avoid costume UI, dashboard vanity metrics, and decorative card grids.

JetBrains Mono is the default UI family across themes and surfaces, as requested for the creator workstation. Keep Manrope and the other bundled sans-serif and serif options available, and use tabular numerals for operational data. Use the role scale, line height, and spacing to keep dense operational text comfortable to scan.

## Colors

### Studio Dark (default)

| Token | Value | Role |
|---|---|---|
| Canvas | #0F0F0F | Main application background |
| Surface | #181818 | Panels and menus |
| Soft surface | #212121 | Inputs and inset work areas |
| Hover surface | #2B2B2B | Interactive surface emphasis |
| Sidebar | #0F0F0F | Primary navigation |
| Text | #F1F1F1 | Primary content |
| Body | #D6D6D6 | Secondary content |
| Muted | #AAAAAA | Supporting text |
| Border | #303030 | Structure and separation |
| Accent | #FF0033 | Primary action and current selection |
| Success | #81C995 | Ready and completed states |
| Warning | #F6C26B | Attention and pending states |
| Danger | #F28B82 | Errors and stop actions |

### Available themes

The user may switch themes without changing layout or behavior:

- **Studio Dark (default)** - near-black canvas, neutral charcoal surfaces, vivid red actions.
- **Odysseus** - graphite, arctic cyan, coral, and semantic green/amber.
- **Studio Light** - cool porcelain canvas, white panels, crisp graphite labels, and high-contrast signal red.
- **GitHub Dark** - repository-inspired slate and signal red.
- **Nord** - blue-gray surfaces, frost text, and soft cyan accent.
- **Odysseus Paper** - cool paper surfaces with a deep navy navigation rail and burnt-coral actions.
- **Ocean Depths** - deep blue and cyan.
- **Forest Night** - evergreen and mint.
- **Solarized Paper** - warm parchment, deep ink, olive-gray metadata, and dark teal actions.
- **Rose Graphite** - charcoal and muted rose.
- **Ember Studio** - umber and amber.
- **Slate Studio** - cool graphite and steel blue.

The full selector contains at least 12 curated palettes. Users may override the accent color with a six-digit hex value from either the topbar appearance menu or Settings > Appearance, and reset it to the active theme default. The custom accent changes primary actions and active selections only; success, warning, error, and informational colors remain semantically distinct.

Each theme must define the same semantic tokens, with matching app background, surface, border, and accent values in React, CSS, and WinUI. Components must use semantic variables rather than hard-coded palette values. Status must remain understandable through text or icon as well as color.

### Contrast and custom color

- Primary text must reach at least 7:1 against the app canvas and standard surface.
- Body text, muted labels, quiet metadata, and button text must reach at least 4.5:1 against their intended surfaces.
- Accent button text is selected by comparing WCAG relative luminance for dark and light foregrounds. Do not use a raw brightness cutoff.
- A custom accent never changes semantic status colors.

## Typography

JetBrains Mono is the application-wide default, including WinUI shell controls, dynamically generated text, inputs, buttons, dialogs, and tabs. The bundled variable font is used directly. The font selector retains the bundled sans-serif, serif, and monospace alternatives plus common Windows system families. The selected family must apply consistently across navigation, workspace surfaces, dropdowns, and dialogs. Keep the 14-DIP medium body baseline and restrained line spacing so the monospaced family remains readable in dense workflows.

Use a role-based native desktop scale with a 14-DIP body baseline: Small 13, Medium 14 (default), Large 16, proportionally scaling labels and headings. Preserve heading hierarchy and do not use tiny interface copy. Interactive controls are at least 48px high. Keep line height near 1.45 for explanatory text. Use tabular numerals for durations, counts, sizes, and progress. Subtitle output typography is configured separately from the application interface font.

## Layout

- Sidebar width: 260px. Top utility bar: 76px. Page content uses a 40px desktop gutter.
- Main workspace is desktop-first and opens maximized. Two-column work areas stack below 900px; the sidebar remains independently scrollable.
- Dashboard uses one live seven-stage source-to-publish rundown, then recent clips and creator monitors. Do not use a four-metric hero strip.
- Live Studio uses a single source field, a real 16:9 preview, five pre-capture setup tabs, and a persistent bottom Start/Stop action bar.
- Live Studio follows one canonical order: source, configuration, session status, then Start/Stop.
- Capture, Framing, AI provider, Transcription, and Captions are always available as visible tabs inside Live Studio before capture starts. Framing exposes automatic GPU-first facecam detection and separate draggable/resizable facecam and gameplay regions. They do not belong in global Settings.
- Keep the source URL as the canonical source for source preview and creator-handle detection.
- Keep a persistent capture action bar at the bottom of the Studio content.
- Global Settings contains application-wide storage and appearance only.
- Do not place a panel inside another panel solely for decoration. Use whitespace and dividers to show hierarchy.

## Elevation & Depth

Use a single restrained shadow token for menus and elevated surfaces. Panels are separated primarily through surface tone and a 1px semantic border. Avoid heavy blur, glowing outlines, and multiple stacked shadows. Sticky capture controls may use the standard panel shadow to remain legible while scrolling.

## Shapes

- Controls: 8px radius, at least 48px high where interactive.
- Panels: 12px radius with 26px internal padding.
- Badges and status pills: fully rounded only when they communicate a state.
- Focus rings: 2px accent outline with 2px offset.
- Inputs must preserve native affordances and sufficient target height.

## Components

- Use the shared Panel, Field, Button, StatusPill, Toggle, and toast patterns.
- Use Lucide icons with consistent 15-18px sizing and stroke weight.
- Studio configuration uses accessible tabs (tablist, tab, tabpanel) with keyboard navigation.
- Capture and general configuration auto-save; AI credentials use the explicit Save action.
- Creator handles are inferred from supported channel URLs. A manually entered credit takes precedence until cleared.
- A Gemini key requirement is shown in the AI tab and checked before a Gemini-backed capture starts.
- Empty, loading, saved, error, offline, and active-capture states must be explicit.
- Motion should be short and functional. Respect prefers-reduced-motion.

## Do's and Don'ts

- Do keep all pre-capture options in Live Studio.
- Do show the detected channel handle before capture and make manual override clear.
- Do communicate when a URL cannot expose a channel name.
- Do keep Google API usage and transcript-sharing behavior transparent.
- Do use semantic tokens for every theme.
- Don't hide essential pipeline setup in global Settings.
- Don't duplicate a second source URL field inside caption preview.
- Don't imply that opening Live Studio starts recording.
- Don't use color as the only state indicator.


## UI craft and review

- Treat StreamSnip as an operational media workstation, not a promotional landing page. Keep the stream, clip preview, session state, and next action visually dominant.
- Use a neutral foundation and one active accent. Do not use accent color as decoration or replace semantic status colors with the user accent.
- Give controls readable labels and comfortable hit areas. Keep metadata secondary, but never make essential instructions or control labels tiny.
- Prefer one clear surface level, whitespace, and dividers over nested decorative panels or heavy shadows.
- Motion must communicate feedback or state. Keep common actions immediate; animate only transform and opacity where practical, use short ease-out transitions, and respect reduced-motion preferences.
- Avoid transition: all, layout-shifting animation, scroll reveals, glow effects, and decorative movement.
- Review the result at desktop, tablet, and phone widths. Run the Impeccable detector on source and the rendered app before accepting a UI change.
