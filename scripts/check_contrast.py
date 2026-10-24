"""Measure text contrast in the active shell's stylesheet against WCAG 2.2 AA.

The agreed standard is WCAG 2.2 AA: a contrast ratio of at least 4.5:1 for normal text and
3:1 for large text (18.66px bold or 24px and above) and for user-interface component
boundaries. This script measures; it does not decide whether a colour is tasteful.

It cannot lay the page out, so it cannot know every real foreground/background pairing. It
resolves a background in this order: the rule's own `background`, then the declared container
background for that selector, then the page background. `CONTAINERS` is therefore part of the
measurement and must be kept truthful when the layout changes.

Colours it cannot resolve are reported as skipped rather than silently passed.

    python scripts/check_contrast.py            # report every measured pair
    python scripts/check_contrast.py --failures # only what misses the standard
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLESHEET = ROOT / "app/blackbox_static/simple.css"

NORMAL_TEXT = 4.5
LARGE_TEXT = 3.0

#: Page background, used when nothing nearer is declared.
PAGE = "#f6f7fb"

#: Background a selector actually sits on, by substring match on the selector text. Ordered:
#: the first match wins, so put the more specific container first.
CONTAINERS: tuple[tuple[str, str], ...] = (
    (".brand-icon", "#5146ce"),
    (".primary", "#5146ce"),
    ("#finding-review", "#ffffff"),
    (".app-header", "#ffffff"),
    (".brand", "#ffffff"),
    ("nav", "#ffffff"),
    (".judge-reason", "#f7f6fd"),
    (".provenance", "#f7f6fd"),
    (".transcript", "#fafbfe"),
    (".cal-table", "#ffffff"),
    (".cal-pick", "#ffffff"),
    (".metric", "#ffffff"),
    (".verdict-card", "#ffffff"),
    (".check", "#ffffff"),
    (".notice", "#fff8e8"),
    (".unknown", "#fff8e8"),
    (".helper", "#ffffff"),
    ("blockquote", "#fafbfe"),
    ("details", "#ffffff"),
    ("summary", "#ffffff"),
    ("article", "#ffffff"),
    ("table", "#ffffff"),
    ("th", "#ffffff"),
    ("td", "#ffffff"),
    ("input", "#ffffff"),
    ("textarea", "#ffffff"),
    ("select", "#ffffff"),
    ("button", "#ffffff"),
    ("label", "#ffffff"),
)

#: Selectors measured against the large-text threshold, with why.
LARGE: tuple[tuple[str, str], ...] = (
    ("h1", "page heading, well above 24px"),
    ("h2", "section heading, above 24px"),
    (".stat-value", "large numeric display"),
    (".eyebrow", "uppercase label above 18.66px bold"),
)

#: Selectors whose colour is not text, so a text ratio does not apply.
NON_TEXT = ("--border", "::backdrop", "border", "outline", "fill", "stroke")

HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
DECLARATION = re.compile(r"([-a-zA-Z]+)\s*:\s*([^;]+)")


def channel(value: int) -> float:
    fraction = value / 255
    return fraction / 12.92 if fraction <= 0.03928 else ((fraction + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    text = colour.lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    red, green, blue = (int(text[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def ratio(foreground: str, background: str) -> float:
    first, second = luminance(foreground), luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def tokens(css: str) -> dict[str, str]:
    """Resolve the `--name: #hex` custom properties so `var(--name)` can be measured."""
    found = {}
    for name, value in DECLARATION.findall(css):
        if name.startswith("--"):
            match = HEX.search(value)
            if match:
                found[name] = match[0]
    return found


#: The only named colours this stylesheet uses. Kept explicit rather than guessed.
NAMED = {"white": "#ffffff", "black": "#000000"}


def resolve(value: str, variables: dict[str, str]) -> str | None:
    match = HEX.search(value)
    if match:
        return match[0]
    for name, colour in NAMED.items():
        if re.search(rf"\b{name}\b", value):
            return colour
    reference = re.search(r"var\(\s*(--[-a-zA-Z0-9]+)", value)
    if reference:
        return variables.get(reference[1])
    return None


def background_for(selector: str, own: str | None) -> tuple[str, str]:
    if own:
        return own, "own background"
    for needle, colour in CONTAINERS:
        if needle in selector:
            return colour, f"container {needle}"
    return PAGE, "page background"


def threshold_for(selector: str) -> tuple[float, str]:
    for needle, why in LARGE:
        if needle in selector:
            return LARGE_TEXT, why
    return NORMAL_TEXT, "normal text"


def measure() -> tuple[list[dict], list[str]]:
    css = STYLESHEET.read_text(encoding="utf-8")
    variables = tokens(css)
    rows, skipped = [], []
    for selector, body in RULE.findall(css):
        selector = " ".join(selector.split())
        if any(needle in selector for needle in ("@", "::backdrop")):
            continue
        declarations = dict(DECLARATION.findall(body))
        if "color" not in declarations:
            continue
        if any(needle in selector for needle in NON_TEXT):
            continue
        foreground = resolve(declarations["color"], variables)
        own = resolve(declarations.get("background", ""), variables) or resolve(
            declarations.get("background-color", ""), variables
        )
        if not foreground:
            skipped.append(f"{selector}: colour {declarations['color'].strip()} not resolvable")
            continue
        background, source = background_for(selector, own)
        limit, why = threshold_for(selector)
        value = ratio(foreground, background)
        rows.append(
            {
                "selector": selector,
                "foreground": foreground,
                "background": background,
                "background_source": source,
                "ratio": round(value, 2),
                "required": limit,
                "kind": why,
                "passes": value >= limit,
            }
        )
    return rows, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--failures", action="store_true", help="Print only failing pairs.")
    args = parser.parse_args(argv)
    rows, skipped = measure()
    failures = [row for row in rows if not row["passes"]]
    shown = failures if args.failures else rows
    for row in sorted(shown, key=lambda r: r["ratio"]):
        mark = "ok  " if row["passes"] else "FAIL"
        print(
            f"{mark} {row['ratio']:>5}:1 (needs {row['required']}) "
            f"{row['foreground']} on {row['background']} [{row['background_source']}] "
            f"{row['kind']} — {row['selector']}"
        )
    for note in skipped:
        print(f"skip  {note}")
    print(f"\nWCAG 2.2 AA: {len(rows)} measured, {len(failures)} failing, {len(skipped)} skipped.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
