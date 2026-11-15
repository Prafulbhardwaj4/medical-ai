"""Captcha image drawn as vector shapes (no <text> elements), so the answer cannot be read
from the SVG markup. Each glyph is a 5x7 grid of cells whose corners are jittered, rotated and
sheared, merged into one filled path, then crossed by noise strokes and dots.
Only the characters in CAPTCHA_ALPHABET (utils/auth.py) have glyphs."""
import math
import random

_FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
}

_COLORS = ["#0f172a", "#1e3a8a", "#0f766e", "#6d28d9", "#9f1239"]
_rnd = random.SystemRandom()


def render_captcha_svg(code: str) -> str:
    width, height = 190, 64
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
             f'<rect width="{width}" height="{height}" fill="#f1f5f9" rx="8"/>']
    for _ in range(3):  # background curves
        x1, y1 = _rnd.uniform(0, width), _rnd.uniform(0, height)
        x2, y2 = _rnd.uniform(0, width), _rnd.uniform(0, height)
        cx, cy = _rnd.uniform(0, width), _rnd.uniform(0, height)
        parts.append(f'<path d="M{x1:.1f} {y1:.1f} Q{cx:.1f} {cy:.1f} {x2:.1f} {y2:.1f}" fill="none" stroke="#cbd5e1" stroke-width="2"/>')
    n = max(len(code), 1)
    slot = width / (n + 0.4)
    for i, ch in enumerate(code):
        rows = _FONT.get(ch.upper())
        if not rows:
            continue
        s = _rnd.uniform(4.0, 4.6)
        cx = slot * (i + 0.75) + _rnd.uniform(-2, 2)
        cy = height / 2 + _rnd.uniform(-4, 4)
        ang = _rnd.uniform(-0.2, 0.2)
        shear = _rnd.uniform(-0.15, 0.15)
        ca, sa = math.cos(ang), math.sin(ang)
        verts = {}
        for r in range(8):
            for c in range(6):
                x = (c - 2.5) * s + _rnd.uniform(-0.1, 0.1) * s
                y = (r - 3.5) * s + _rnd.uniform(-0.1, 0.1) * s
                x += shear * y
                verts[(r, c)] = (cx + x * ca - y * sa, cy + x * sa + y * ca)
        d = []
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == "1":
                    pts = [verts[(r, c)], verts[(r, c + 1)], verts[(r + 1, c + 1)], verts[(r + 1, c)]]
                    mx = sum(p[0] for p in pts) / 4
                    my = sum(p[1] for p in pts) / 4
                    pts = [(mx + (x - mx) * 1.22, my + (y - my) * 1.22) for x, y in pts]  # slight overlap so touching cells join
                    d.append("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z")
        parts.append(f'<path d="{"".join(d)}" fill="{_rnd.choice(_COLORS)}"/>')
    for _ in range(2):  # strokes across the text
        y1, y2 = _rnd.uniform(8, height - 8), _rnd.uniform(8, height - 8)
        parts.append(f'<path d="M2 {y1:.1f} Q{width / 2:.1f} {_rnd.uniform(0, height):.1f} {width - 2} {y2:.1f}" '
                     f'fill="none" stroke="{_rnd.choice(_COLORS)}" stroke-width="1.2" stroke-opacity="0.7"/>')
    for _ in range(25):
        parts.append(f'<circle cx="{_rnd.uniform(0, width):.1f}" cy="{_rnd.uniform(0, height):.1f}" r="1.3" fill="#94a3b8"/>')
    parts.append("</svg>")
    return "".join(parts)