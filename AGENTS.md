# StreamSnip AI — UI engineering rules

Before changing any UI, read `DESIGN.md` and inspect the current rendered or native interface. This is an **Operate** product: creators need to configure capture, monitor processing, review clips, and publish with confidence. Prioritize scanability, predictable controls, readable states, and useful content density over decorative effects.

## Required design references

Use these three user-provided design skill repositories as the design and review standard:

- Taste Skill: https://github.com/sifat-jaman-13/taste-skill
  - Use its disciplined system for palette selection, typography, spacing, contrast, restrained color, copy, and cohesive component families.
  - Adapt the principles to an operational desktop application; do not import marketing-page effects that distract from capture and clip review.
- Emil Kowalski Skills: https://github.com/sifat-jaman-13/skills
  - Use purposeful micro-interactions, immediate feedback, clear pressed/focus states, and reduced-motion support.
  - Animate `transform` and `opacity` by default; never use `transition: all`; avoid layout-shifting motion and JS-driven per-frame React state.
  - Turn explicit user design corrections into durable project rules.
- Impeccable: https://github.com/sifat-jaman-13/impeccable
  - Inspect the incumbent product before changing it. Preserve product behavior and existing visual identity during refinement.
  - Review hierarchy, responsive behavior, accessibility, empty/error/loading states, and visual consistency.
  - Run `npx --yes impeccable@4.10.0 detect dashboard/src --json` after React UI changes and resolve findings or document a justified false positive.

## Color and appearance

- Keep at least 12 complete palettes available in both React and WinUI. The palette IDs and key colors must match across `App.tsx`, `App.css`, and `MainPage.xaml.cs`.
- Keep the appearance selector and Settings > Appearance synchronized. Custom accent selection must persist and reset to the selected theme's accent.
- The user accent changes primary actions and current selections only. It must not replace success, warning, error, or informational status colors.
- Pick button foreground text using WCAG relative-luminance contrast, not a simple brightness threshold.
- Keep primary text at 7:1 or better and body, muted, quiet, and button text at 4.5:1 or better against the surfaces where they are used.
- Run `python dashboard/tools/audit-theme-contrast.py` and `python dashboard/tools/audit-theme-parity.py` after palette changes.

## Component craft

- Keep labels, hints, controls, and page headings readable. Metadata may be secondary, but never shrink essential instructions to tiny text.
- Prefer spacing, clear alignment, and one restrained surface level over nested decorative panels, accent rails, heavy shadows, or glow.
- Use semantic theme tokens rather than hard-coded palette values in shared components.
- Give every interactive control a keyboard-visible focus state and a useful disabled, loading, success, or error state.
- Respect `prefers-reduced-motion`.
- Do not alter capture, transcription, AI, rendering, creator monitoring, storage, or publishing behavior during a visual-only change.

## Safe collaboration

- Inspect `git status` and file timestamps before editing; the working tree may contain another contributor's changes.
- Make focused edits to separate components or sections. Re-read before writing and use hash-checked edits when the file may be changing concurrently.
- Never reset, clean, overwrite, or stop another contributor's process to make a UI change.
- Run the React production build/lint and the WinUI build after shared component changes.
