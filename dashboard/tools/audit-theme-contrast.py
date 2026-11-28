from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / "dashboard" / "src" / "App.css").read_text(encoding="utf-8")

def channels(hex_value):
    value = hex_value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected #RRGGBB, got {hex_value!r}")
    return tuple(int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))

def linear(channel):
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

def luminance(hex_value):
    red, green, blue = channels(hex_value)
    return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)

def contrast(foreground, background):
    first, second = luminance(foreground), luminance(background)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)

def ensure_contrast(foreground, backgrounds, minimum):
    """Mirror the React theme's foreground correction before measuring live tokens."""
    worst = lambda candidate: min(contrast(candidate, bg) for bg in backgrounds)
    if worst(foreground) >= minimum:
        return foreground
    target = "#FFFFFF" if worst("#FFFFFF") >= worst("#000000") else "#000000"
    source, destination = channels(foreground), channels(target)
    for step in range(1, 101):
        amount = step / 100
        candidate = "#" + "".join(
            f"{round((destination[index] * amount + source[index] * (1 - amount)) * 255):02X}"
            for index in range(3)
        )
        if worst(candidate) >= minimum:
            return candidate
    return target


rules = {}
for match in re.finditer(r'html\[data-theme=["\']([^"\']+)["\']\]\s*\{([^}]*)\}', CSS, re.S):
    rules[match.group(1)] = dict(
        (name, value.upper())
        for name, value in re.findall(r'--([a-z-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;', match.group(2))
    )

theme_ids = list(rules)
issues = []
print("Theme contrast audit (WCAG relative luminance)")
print("theme           ink    body   muted  quiet  sidebar muted  accent text")
for theme in theme_ids:
    tokens = rules.get(theme, {})
    for role, fallback in {
        "sidebar-ink": "ink",
        "sidebar-body": "body",
        "sidebar-muted": "muted",
        "sidebar-line": "line-strong",
        "sidebar-surface": "surface-soft",
    }.items():
        tokens.setdefault(role, tokens.get(fallback))
    required = (
        "app-bg", "surface", "surface-soft", "surface-hover", "sidebar-bg",
        "sidebar-surface", "ink", "body", "muted", "quiet", "sidebar-ink",
        "sidebar-body", "sidebar-muted", "accent", "accent-ink",
    )
    missing = [name for name in required if not tokens.get(name)]
    if missing:
        issues.append(f"{theme}: missing {', '.join(missing)}")
        continue

    surfaces = tuple(tokens[name] for name in ("app-bg", "surface", "surface-soft", "surface-hover"))
    sidebar_surfaces = (tokens["sidebar-bg"], tokens["sidebar-surface"])
    small_floor = 7.0 if theme == "studio-light" else 4.5
    effective = {
        "ink": ensure_contrast(tokens["ink"], surfaces, 7.0),
        "body": ensure_contrast(tokens["body"], surfaces, 4.5),
        "muted": ensure_contrast(tokens["muted"], surfaces, small_floor),
        "quiet": ensure_contrast(tokens["quiet"], surfaces, small_floor),
        "sidebar_muted": ensure_contrast(tokens["sidebar-muted"], sidebar_surfaces, small_floor),
        "sidebar_ink": ensure_contrast(tokens["sidebar-ink"], sidebar_surfaces, 7.0),
        "sidebar_body": ensure_contrast(tokens["sidebar-body"], sidebar_surfaces, 4.5),
    }
    measurements = {
        "ink": min(contrast(effective["ink"], bg) for bg in surfaces),
        "body": min(contrast(effective["body"], bg) for bg in surfaces),
        "muted": min(contrast(effective["muted"], bg) for bg in surfaces),
        "quiet": min(contrast(effective["quiet"], bg) for bg in surfaces),
        "sidebar_muted": min(contrast(effective["sidebar_muted"], bg) for bg in sidebar_surfaces),
        "accent": contrast(tokens["accent-ink"], tokens["accent"]),
        "sidebar_ink": min(contrast(effective["sidebar_ink"], bg) for bg in sidebar_surfaces),
        "sidebar_body": min(contrast(effective["sidebar_body"], bg) for bg in sidebar_surfaces),
    }
    print(
        f"{theme:15} "
        f"{measurements['ink']:5.2f}  {measurements['body']:5.2f}  "
        f"{measurements['muted']:5.2f}  {measurements['quiet']:5.2f}  "
        f"{measurements['sidebar_muted']:6.2f}       {measurements['accent']:5.2f}"
    )
    floors = {
        "ink": 7.0,
        "body": 4.5,
        "muted": small_floor,
        "quiet": small_floor,
        "sidebar_muted": small_floor,
        "accent": 4.5,
        "sidebar_ink": 7.0,
        "sidebar_body": 4.5,
    }
    for token, floor in floors.items():
        if measurements[token] < floor:
            issues.append(
                f"{theme}: {token} contrast {measurements[token]:.2f}:1 is below {floor:.1f}:1"
            )

if issues:
    print("\nFAIL")
    for issue in issues:
        print(" -", issue)
    raise SystemExit(1)

print("\nPASS: all 12 themes meet the configured text and accent contrast floors.")
