"""
CHAMELEON layout engine — Step 1: compliant baseline (uniform letterbox).

Every element is scaled by ONE factor s = min(W/sw, H/sh) and the whole
design is centred on the target canvas, so images keep their exact aspect
ratio and the source's intentional overlaps are preserved. Backgrounds are
stretched to fill the canvas. Text is re-fitted with the renderer's own
measurement so nothing overflows its box. Finally every element is clamped
so both its axis box and its rotated box are inside the canvas.

Only x, y, width, height (and font_size for text) are ever changed; every
other key is copied verbatim. This file is also the fallback for the full
engine built in later steps (see HANDOFF.md).
"""

import copy
import math
from pathlib import Path
from typing import Any

import skia  # installed with cr-renderer

from renderer.converter import convert as _conv
from renderer.converter.wrap import char_widths, wrap_text

_FONTS_DIR = Path(__file__).resolve().parent.parent / "brand_kit" / "fonts"
_FM = None
_TYPEFACES: dict = {}


# ---------------------------------------------------------------- text measurement
def _font_manager():
    global _FM
    if _FM is None:
        _FM = _conv._get_renderer(str(_FONTS_DIR)).font_manager
    return _FM


def _faces(el):
    """(weight, style) exactly as the converter + cr-renderer derive them."""
    weight = _conv._normalize_weight(el.get("font_weight"))
    bold = weight in _conv._BOLD_WEIGHTS
    italic = _conv._is_italic(el.get("font_style"))
    return weight, _conv._weight_style_to_font_style(bold, italic)


def _typeface(family, weight, style):
    key = (family, weight, style)
    if key not in _TYPEFACES:
        draw_weight = "bold" if style in ("bold", "bolditalic") else "regular"
        _TYPEFACES[key] = skia.Typeface.MakeFromData(_font_manager().lookup(family, draw_weight, style))
    return _TYPEFACES[key]


def text_layout(el, fs, width):
    """Mirror the renderer: wrap at the float size without letter spacing, draw at
    int(fs) with letter spacing; text is top-aligned in its box.
    Returns (lines, widest drawn line, block height, widest single word)."""
    content = str(el.get("content", ""))
    family = el.get("font_family", "")
    weight, style = _faces(el)
    lines = wrap_text(content, char_widths(_font_manager(), family, weight, style, float(fs), content),
                      float(width)).split("\n")
    font = skia.Font(_typeface(family, weight, style), int(fs))
    ls = float(el.get("letter_spacing", 0) or 0)

    def drawn(s):
        glyphs = font.textToGlyphs(s)
        return sum(font.getWidths(glyphs)) + ls * max(0, len(glyphs) - 1)

    widest = max((drawn(ln) for ln in lines), default=0.0)
    word = max((drawn(w) for w in content.split()), default=0.0)
    m = font.getMetrics()
    lh = float(el.get("line_height", 1.2) or 1.2)
    block_h = (len(lines) - 1) * fs * lh + (m.fDescent - m.fAscent)
    return lines, widest, block_h, word


def fit_text_in_box(el):
    """Largest integer font_size <= current that fits the element's box
    (width: every drawn line and every word; height: the text block)."""
    el["width"] = max(1.0, float(el["width"]))
    el["height"] = max(1.0, float(el["height"]))
    fs = max(1, int(el["font_size"]))
    while True:
        _, widest, block_h, word = text_layout(el, fs, el["width"])
        if widest <= el["width"] + 0.5 and word <= el["width"] + 0.5 and block_h <= el["height"] + 0.5:
            break
        if fs == 1:
            # Even 1px does not fit (e.g. large fixed letter_spacing): grow the box to the
            # drawn text instead of letting it overflow, keeping its alignment anchor.
            need_w = max(widest, word) + 1.0
            if need_w > el["width"]:
                align = el.get("text_align", "left")
                shift = (need_w - el["width"]) * (0.5 if align == "center" else 1.0 if align == "right" else 0.0)
                el["x"] -= shift
                el["width"] = need_w
                _, widest, block_h, word = text_layout(el, fs, el["width"])
            el["height"] = max(el["height"], math.ceil(block_h) + 1.0)
            break
        fs -= 1
    el["font_size"] = fs


# ---------------------------------------------------------------- geometry helpers
def _rot_extent(w, h, deg):
    if not deg:
        return w, h
    t = math.radians(deg)
    c, s = abs(math.cos(t)), abs(math.sin(t))
    return w * c + h * s, w * s + h * c


def _effective_extent(el):
    """Half-sizes that must fit: the larger of the axis box and the rotated box
    (they share a centre). main.py checks the axis box; the pixels follow the rotated one."""
    rw, rh = _rot_extent(el["width"], el["height"], el.get("rotation") or 0)
    return max(el["width"], rw), max(el["height"], rh)


def clamp_inside(el, W, H):
    bw, bh = _effective_extent(el)
    if bw > W or bh > H:  # too big for the canvas: shrink about the centre
        k = min(W / bw, H / bh) * 0.999
        cx, cy = el["x"] + el["width"] / 2, el["y"] + el["height"] / 2
        el["width"], el["height"] = el["width"] * k, el["height"] * k
        el["x"], el["y"] = cx - el["width"] / 2, cy - el["height"] / 2
        if el["type"] == "text":
            el["font_size"] = max(1, int(el["font_size"] * k))
            fit_text_in_box(el)
        bw, bh = _effective_extent(el)
    cx = min(max(el["x"] + el["width"] / 2, bw / 2), W - bw / 2)
    cy = min(max(el["y"] + el["height"] / 2, bh / 2), H - bh / 2)
    el["x"], el["y"] = cx - el["width"] / 2, cy - el["height"] / 2


def _covers(el, cw, ch):
    x0, y0 = max(0.0, el["x"]), max(0.0, el["y"])
    x1, y1 = min(cw, el["x"] + el["width"]), min(ch, el["y"] + el["height"])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0) / (cw * ch)


def is_background(el, cw, ch):
    return el["type"] != "text" and _covers(el, cw, ch) >= 0.9


# ---------------------------------------------------------------- entry point
def letterbox(source: dict, target_canvas: dict) -> dict:
    W, H = int(target_canvas["width"]), int(target_canvas["height"])
    sw, sh = float(source["canvas"]["width"]), float(source["canvas"]["height"])
    s = min(W / sw, H / sh)
    ox, oy = (W - sw * s) / 2, (H - sh * s) / 2

    out = {"canvas": {"width": W, "height": H}, "elements": copy.deepcopy(source["elements"])}
    for el in out["elements"]:
        if is_background(el, sw, sh):
            el.update(x=0.0, y=0.0, width=float(W), height=float(H))
            continue
        el.update(x=ox + el["x"] * s, y=oy + el["y"] * s, width=el["width"] * s, height=el["height"] * s)
        if el["type"] == "text":
            el["font_size"] = max(1, int(el["font_size"] * s))
            fit_text_in_box(el)

    for el in out["elements"]:
        clamp_inside(el, W, H)
        for k in ("x", "y", "width", "height"):
            el[k] = round(float(el[k]), 2)
        clamp_inside(el, W, H)  # rounding can nudge an edge by 0.005 px
    return out


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    """Step 1: compliant letterbox baseline. Later steps replace this body with the
    structure-search engine and keep letterbox() as the fallback."""
    return letterbox(source, target_canvas)
