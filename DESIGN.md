---
name: StreamSnip AI Creator Studio
description: A desktop-first creator workspace for preparing stream capture, shaping clips, and publishing with a local media engine.
colors:
  app-bg: "#282c34"
  surface: "#1b2028"
  surface-soft: "#232b35"
  surface-hover: "#2d3743"
  sidebar-bg: "#171c23"
  ink: "#e8f0f4"
  body: "#c8d5dc"
  muted: "#9cdef2"
  line: "#355a66"
  accent: "#e06c75"
  success: "#80c99a"
  warning: "#e6b96f"
  danger: "#e06c75"
typography:
  family: "JetBrains Mono, Fira Code, Cascadia Code, Consolas, monospace"
  weights: "400, 500, 600, 700"
  numerals: "Tabular for counts, durations, sizes, and progress"
layout:
  sidebar-width: "244px"
  topbar-height: "64px"
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

The visual direction is a restrained graphite studio with arctic-cyan secondary information and a coral action color. The interface should feel like a dependable media workstation: clear states, compact controls, visible configuration, and no decorative UI that competes with the stream or clip.

The source repository and prior Odysseus palette informed the default theme. StreamSnip uses its own information architecture and components.

## Colors

### Odysseus (default)

| Token | Value | Role |
|---|---|---|
| Canvas | #282c34 | Main application background |
| Surface | #1b2028 | Panels and menus |
| Soft surface | #232b35 | Inputs, nested areas, hover bases |
| Hover surface | #2d3743 | Interactive surface emphasis |
| Sidebar | #171c23 | Primary navigation |
| Text | #e8f0f4 | Primary content |
| Body | #c8d5dc | Secondary content |
| Muted | #9cdef2 | Labels and supporting information |
| Border | #355a66 | Structure and separation |
| Accent | #e06c75 | Primary action and current selection |
| Success | #80c99a | Ready and completed states |
| Warning | #e6b96f | Attention and pending states |
| Danger | #e06c75 | Errors and stop actions |

### Available themes

The user may switch themes without changing layout or behavior:

- **Odysseus** - default graphite, cyan, and coral.
- **Studio Light** - neutral light canvas with restrained red actions.
- **Studio Dark** - low-light charcoal with red actions.
- **GitHub Dark** - repository-inspired slate and signal red.
- **Nord** - blue-gray surfaces, frost text, and soft cyan accent.
- **Odysseus Paper** - retained navy, chalk, and orange palette.
- **Ocean Depths** - deep blue and cyan.
- **Forest Night** - evergreen and mint.
- **Solarized Paper** - warm parchment and teal.
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

JetBrains Mono is the application-wide default, as explicitly requested. Use Fira Code, Cascadia Code, and Consolas as fallbacks. The font selector retains Google Sans, Inter, Roboto, Open Sans, Montserrat, Poppins, Lato, Nunito Sans, DM Sans, IBM Plex Sans, Space Grotesk, and Fira Code as alternatives.

Use 12-14px for core desktop controls and body copy, 10-11px for secondary labels, and 15-22px for page and section headings. Keep line height near 1.5 for explanatory text. Use tabular numerals for durations, counts, sizes, and progress. Subtitle output typography is configured separately from the application interface font.

## Layout

- Sidebar width: 244px. Top utility bar: 64px.
- Main workspace is desktop-first and must remain usable at 320px, 768px, 1024px, and 1440px.
- Live Studio follows one canonical order: source, configuration, session status, then Start/Stop.
- Capture, AI provider, Transcription, and Captions are always available as visible tabs inside Live Studio before capture starts. They do not belong in global Settings.
- Keep the source URL as the canonical source for source preview and creator-handle detection.
- Keep a persistent capture action bar at the bottom of the Studio content.
- Global Settings contains application-wide storage and appearance only.
- Do not place a panel inside another panel solely for decoration. Use whitespace and dividers to show hierarchy.

## Elevation & Depth

Use a single restrained shadow token for menus and elevated surfaces. Panels are separated primarily through surface tone and a 1px semantic border. Avoid heavy blur, glowing outlines, and multiple stacked shadows. Sticky capture controls may use the standard panel shadow to remain legible while scrolling.

## Shapes

- Controls: 8px radius.
- Panels: 12px radius.
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
