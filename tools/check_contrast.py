#!/usr/bin/env python3
"""Verify every colour pair in app/static/style.css against WCAG.

Reads the OKLCH tokens straight out of the stylesheet -- so if you change a
colour, this tells you whether it still passes. No dependencies.

    python3 tools/check_contrast.py

Exits non-zero if anything fails, so it works in a pre-commit hook or CI.
"""
import math
import os
import re
import sys

CSS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "app", "static", "style.css")

M2 = [[ 4.0767416621, -3.3077115913,  0.2309699292],
      [-1.2684380046,  2.6097574011, -0.3413193965],
      [-0.0041960863, -0.7034186147,  1.7076147010]]

SURFACES = ["bg-dark", "bg", "bg-light", "highlight"]
ACCENTS = ["primary", "secondary", "danger", "warning", "success", "info"]
# token -> (minimum ratio against every surface, why)
RULES = {
    "text":       (7.0, "AAA body text"),
    "text-muted": (4.5, "AA secondary text"),
    "border":     (3.0, "AA non-text contrast"),
}


def oklch_to_srgb(L, C, H):
    a = C * math.cos(math.radians(H))
    b = C * math.sin(math.radians(H))
    lms = [L + 0.3963377774 * a + 0.2158037573 * b,
           L - 0.1055613458 * a - 0.0638541728 * b,
           L - 0.0894841775 * a - 1.2914855480 * b]
    cubed = [v ** 3 for v in lms]
    return [min(1.0, max(0.0, sum(M2[i][j] * cubed[j] for j in range(3))))
            for i in range(3)]


def luminance(colour):
    r, g, b = oklch_to_srgb(*colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(c1, c2):
    l1, l2 = luminance(c1), luminance(c2)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def parse():
    """Pull the two themes' token blocks out of the stylesheet."""
    css = open(CSS).read()
    # Strip comments so hex annotations can't be mistaken for declarations.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    themes = {}
    # :root block = light; the [data-theme="dark"] block = dark.
    blocks = re.findall(r"(:root(?:\[data-theme=\"dark\"\])?)\s*\{(.*?)\n\}",
                        css, re.S)
    for selector, body in blocks:
        name = "dark" if "dark" in selector else "light"
        tokens = {}
        for tok, L, C, H in re.findall(
                r"--([a-z-]+):\s*oklch\(([\d.]+)\s+([\d.]+)\s+([\d.]+)\)", body):
            tokens[tok] = (float(L), float(C), float(H))
        if tokens:
            themes.setdefault(name, {}).update(tokens)
    return themes


def main():
    themes = parse()
    if len(themes) < 2:
        print("Could not read both themes out of style.css", file=sys.stderr)
        return 2

    failures = 0
    required = set(SURFACES) | set(ACCENTS) | set(RULES) | {"on-accent"}
    for theme in ("light", "dark"):
        tokens = themes[theme]
        print(f"\n=== {theme} ===")
        missing = required - set(tokens)
        if missing:
            print(f"  MISSING tokens: {', '.join(sorted(missing))}")
            failures += len(missing)
            continue
        print(f"  {len(tokens)} tokens defined")

        def check(label, ratio, need):
            nonlocal failures
            ok = ratio >= need
            if not ok:
                failures += 1
            flag = "pass" if ok else "FAIL"
            print(f"  [{flag}] {label:<42} {ratio:5.2f}:1  (>= {need})")

        for tok, (need, why) in RULES.items():
            worst = min(contrast(tokens[tok], tokens[s]) for s in SURFACES)
            check(f"--{tok} on worst surface ({why})", worst, need)
        for tok in ACCENTS:
            worst = min(contrast(tokens[tok], tokens[s]) for s in SURFACES)
            check(f"--{tok} as text on worst surface", worst, 4.5)
        for tok in ACCENTS:
            check(f"--on-accent on --{tok} fill",
                  contrast(tokens["on-accent"], tokens[tok]), 4.5)

    print()
    if failures:
        print(f"{failures} check(s) FAILED")
        return 1
    print("All contrast checks passed (WCAG AA, AAA for body text).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
