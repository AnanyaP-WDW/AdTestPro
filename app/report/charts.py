"""Server-rendered chart helpers.

Everything the report visualises is HTML + CSS except the dimension radar, which
needs a real polygon. That one is emitted as a self-contained SVG data URI so the
identical markup renders in both the browser and WeasyPrint.
"""

from __future__ import annotations

import base64
import math
from typing import Optional, Sequence

# Neutral palette that reads on both the light and dark report surfaces.
_GRID = "#c9cac3"
_AXIS = "#8a8f98"
_INK = "#454a53"
_ACCENT = "#1e4bc8"
_FILL = "rgba(30, 75, 200, 0.16)"


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def radar_svg(labels: Sequence[str], values: Sequence[Optional[float]], *,
              max_value: float = 5.0, size: int = 260) -> Optional[str]:
    """Return an SVG data URI for a dimension profile, or None if unusable.

    Needs at least 3 axes with values; fewer is not a meaningful polygon.
    """
    points = [(str(label), v) for label, v in zip(labels, values) if v is not None]
    if len(points) < 3 or max_value <= 0:
        return None

    cx = cy = size / 2
    radius = size * 0.34
    n = len(points)
    angles = [(-math.pi / 2) + (2 * math.pi * i / n) for i in range(n)]

    def xy(angle: float, r: float) -> tuple[float, float]:
        return (cx + r * math.cos(angle), cy + r * math.sin(angle))

    def poly(r: float) -> str:
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(a, r) for a in angles))

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
             f'width="{size}" height="{size}" role="img">',
             f"<title>Dimension profile: "
             + "; ".join(f"{_esc(label)} {v:.2f} of {max_value:g}" for label, v in points)
             + "</title>"]
    # rings
    for level in range(1, int(max_value) + 1):
        r = radius * level / max_value
        parts.append(f'<polygon points="{poly(r)}" fill="none" stroke="{_GRID}" '
                     'stroke-width="1"/>')
    # spokes
    for a in angles:
        x, y = xy(a, radius)
        parts.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
                     f'stroke="{_GRID}" stroke-width="1"/>')
    # data polygon
    data_r = [radius * min(float(v), max_value) / max_value for _, v in points]
    data_poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in
                         (xy(a, r) for a, r in zip(angles, data_r)))
    parts.append(f'<polygon points="{data_poly}" fill="{_FILL}" stroke="{_ACCENT}" '
                 'stroke-width="2" stroke-linejoin="round"/>')
    for a, r in zip(angles, data_r):
        x, y = xy(a, r)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{_ACCENT}"/>')
    # axis labels
    for a, (label, _v) in zip(angles, points):
        x, y = xy(a, radius * 1.18)
        anchor = "middle"
        if x > cx + 2:
            anchor = "start"
        elif x < cx - 2:
            anchor = "end"
        parts.append(f'<text x="{x:.1f}" y="{y:.1f}" fill="{_INK}" font-size="10" '
                     f'font-family="sans-serif" text-anchor="{anchor}" '
                     f'dominant-baseline="middle">{_esc(label)}</text>')
    parts.append("</svg>")
    return data_uri("".join(parts))
