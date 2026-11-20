#!/usr/bin/env python3
"""Verify every colour pair in app/static/style.css against WCAG.

Surfaces here are GRADIENTS, so each one contributes three sample colours --
its base, its lit top stop (-hi) and its shaded bottom stop (-lo). Every
foreground is checked against ALL of them, because text sitting on a gradient
has to stay legible across the whole span, not just at the midpoint.

    python3 tools/check_contrast.py

Reads the tokens straight out of the stylesheet, so it catches you if you
change a colour. Exits non-zero on any failure -- usable in CI or a hook.
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
STOPS = ["", "-hi", "-lo"]
# foreground token -> (minimum ratio against every surface stop, why)
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
    """Pull the light (:root) and dark ([data-theme=dark]) token blocks out."""
    css = re.sub(r"/\*.*?\*/", "", open(CSS).read(), flags=re.S)
    themes = {}
    for selector, body in re.findall(
            r"(:root(?:\[data-theme=\"dark\"\])?)\s*\{(.*?)\n\}", css, re.S):
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
    missing_theme = {"light", "dark"} - set(themes)
    if missing_theme:
        print(f"Could not read theme(s): {', '.join(missing_theme)}",
              file=sys.stderr)
        return 2

    failures = []
    for theme in ("light", "dark"):
        tokens = themes[theme]
        print(f"\n=== {theme} ===")
        needed = ({s + st for s in SURFACES for st in STOPS}
                  | {a + st for a in ACCENTS for st in STOPS}
                  | set(RULES) | {"on-accent"})
        absent = sorted(needed - set(tokens))
        if absent:
            print(f"  MISSING: {', '.join(absent)}")
            failures += absent
            continue

        surface_stops = [(f"{s}{st}", tokens[s + st])
                         for s in SURFACES for st in STOPS]
        print(f"  {len(tokens)} tokens, {len(surface_stops)} surface stops")

        def worst(fg):
            name, ratio = min(((n, contrast(tokens[fg], c))
                               for n, c in surface_stops), key=lambda x: x[1])
            return name, ratio

        def report(label, ratio, need, where=""):
            ok = ratio >= need
            if not ok:
                failures.append(f"{theme}: {label}")
            tail = f"  worst: --{where}" if where else ""
            print(f"  [{'pass' if ok else 'FAIL'}] {label:<40} "
                  f"{ratio:5.2f}:1 (>= {need}){tail}")

        for tok, (need, why) in RULES.items():
            where, ratio = worst(tok)
            report(f"--{tok} ({why})", ratio, need, where)
        for tok in ACCENTS:
            where, ratio = worst(tok)
            report(f"--{tok} as text", ratio, 4.5, where)
        for tok in ACCENTS:
            ratio = min(contrast(tokens["on-accent"], tokens[tok + st])
                        for st in STOPS)
            report(f"--on-accent across --{tok} fill", ratio, 4.5)

    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED")
        return 1
    print("All contrast checks passed across every gradient stop "
          "(WCAG AA, AAA for body text).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
