from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
APP = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "src" / "App.css").read_text(encoding="utf-8")
NATIVE = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.xaml.cs").read_text(encoding="utf-8")

theme_section = APP.split("const themes:", 1)[1].split("\n];", 1)[0]
react = {}
for match in re.finditer(
    r'\{\s*id:\s*"([^"]+)"\s*,\s*name:\s*"([^"]+)"[^\[]*colors:\s*\[([^\]]+)\]',
    theme_section,
):
    colors = re.findall(r'"(#[0-9a-fA-F]{6})"', match.group(3))
    react[match.group(1)] = (
        colors[0].upper(), colors[1].upper(), colors[2].upper(), colors[-1].upper()
    )

css = {}
for match in re.finditer(r'html\[data-theme=["\']([^"\']+)["\']\]\s*\{([^}]*)\}', CSS, re.S):
    tokens = dict(
        (name, value.upper())
        for name, value in re.findall(r'--([a-z-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;', match.group(2))
    )
    css[match.group(1)] = tuple(
        tokens.get(name) for name in ("app-bg", "surface", "line", "accent")
    )

native_section = NATIVE.split("private static readonly ThemePalette[] Themes", 1)[1].split("\n\t};", 1)[0]
native = {}
for line in native_section.splitlines():
    if "new ThemePalette(" not in line:
        continue
    values = re.findall(r'"([^"]*)"', line)
    if len(values) < 15:
        continue
    native[values[0]] = (
        values[2].upper(), values[3].upper(), values[10].upper(), values[11].upper()
    )

issues = []
print("Theme parity audit")
for theme, react_colors in react.items():
    css_colors = css.get(theme)
    native_colors = native.get(theme)
    if css_colors != react_colors or native_colors != react_colors:
        issues.append(
            f"{theme}: React={react_colors}, CSS={css_colors}, WinUI={native_colors}"
        )
        print("FAIL", theme)
    else:
        print("PASS", theme)

if len(react) != 12:
    issues.append(f"Expected 12 React themes, found {len(react)}")
if set(react) != set(native):
    issues.append("React and WinUI theme id sets differ")

if issues:
    print("\nFAIL")
    for issue in issues:
        print(" -", issue)
    raise SystemExit(1)

print("\nPASS: all 12 palette colors match across React, CSS, and WinUI.")
