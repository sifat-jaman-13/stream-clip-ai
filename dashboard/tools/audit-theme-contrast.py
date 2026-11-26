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

rules = {}
for match in re.finditer(r'html\[data-theme=["\']([^"\']+)["\']\]\s*\{([^}]*)\}', CSS, re.S):
    rules[match.group(1)] = dict(
        (name, value.upper())
        for name, value in re.findall(r'--([a-z-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;', match.group(2))
    )

theme_ids = [
    "odysseus", "studio-light", "studio-dark", "github", "nord", "odysseas",
    "ocean", "forest", "solarized", "rose-graphite", "ember", "slate",
]
issues = []
print("Theme contrast audit (WCAG relative luminance)")
print("theme           ink    body   muted  quiet  accent text")
for theme in theme_ids:
    tokens = rules.get(theme, {})
    required = ("app-bg", "surface", "ink", "body", "muted", "quiet", "accent", "accent-ink")
    missing = [name for name in required if name not in tokens]
    if missing:
        issues.append(f"{theme}: missing {', '.join(missing)}")
        continue

    backgrounds = (tokens["app-bg"], tokens["surface"])
    measurements = {
        "ink": min(contrast(tokens["ink"], background) for background in backgrounds),
        "body": min(contrast(tokens["body"], background) for background in backgrounds),
        "muted": min(contrast(tokens["muted"], background) for background in backgrounds),
        "quiet": min(contrast(tokens["quiet"], background) for background in backgrounds),
        "accent": contrast(tokens["accent-ink"], tokens["accent"]),
    }
    print(
        f"{theme:15} "
        f"{measurements['ink']:5.2f}  {measurements['body']:5.2f}  "
        f"{measurements['muted']:5.2f}  {measurements['quiet']:5.2f}  "
        f"{measurements['accent']:5.2f}"
    )
    floors = {"ink": 7.0, "body": 4.5, "muted": 4.5, "quiet": 4.5, "accent": 4.5}
    for token, floor in floors.items():
        if measurements[token] < floor:
            issues.append(f"{theme}: {token} contrast {measurements[token]:.2f}:1 is below {floor:.1f}:1")

if issues:
    print("\nFAIL")
    for issue in issues:
        print(" -", issue)
    raise SystemExit(1)

print("\nPASS: all 12 themes meet the configured text and accent contrast floors.")
