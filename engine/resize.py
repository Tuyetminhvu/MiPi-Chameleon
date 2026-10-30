"""CHAMELEON layout engine -- structure search over an XY-cut tree (see HANDOFF.md).

Pipeline
  1. Classify: background (non-text, >=90% canvas), decor (shape, eff. opacity < .5),
     content blocks = union-find over group_id + >=25% source overlap (intentional layering).
  2. Source structure = recursive XY-cut of the block boxes (a tree of H/V stacks).
  3. Search: discrete structure variables (root orientation, root track partition,
     flip/keep of each inner node) x continuous scale s (binary search, exact text
     measurement through the renderer's own wrap + skia fonts) x style knobs
     (rho = text/image scale ratio, gamma = type-hierarchy compression).
  4. Score every feasible candidate with an explicit geometric objective; keep the best.
  5. Fallback: uniform letterbox scale (always valid).
No semantic ids, no _note fields, no ML.
"""
import copy
import itertools
import math
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent  # engine/ sits in the repo root
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
import skia  # noqa: E402
from renderer.converter import convert as conv  # noqa: E402
from renderer.converter.wrap import char_widths, wrap_text  # noqa: E402

ABS_FLOOR = 6   # px. Hard minimum for any text: x-height ~3.3px (Sans) / 3.0px (Serif) at 1x raster.
EMERGENCY_FLOORS = (5, 4)   # over-constrained mode only, and only for below-median-importance text
_FM = None
_TF = {}
_CW = {}
_LAY = {}
ASSET_SIZE = {}


def fm():
    global _FM
    if _FM is None:
        _FM = conv._get_renderer(str(REPO / "brand_kit" / "fonts")).font_manager
    return _FM


# ------------------------------------------------------------------ text measurement
def _faces(el):
    weight = conv._normalize_weight(el.get("font_weight"))
    bold = weight in conv._BOLD_WEIGHTS
    style = conv._weight_style_to_font_style(bold, conv._is_italic(el.get("font_style") or el.get("italic")))
    key = (el.get("font_family"), weight, style)
    if key not in _TF:
        try:
            rt = skia.Typeface.MakeFromData(fm().lookup(key[0], "bold" if bold else "regular", style))
        except Exception:
            rt = None
        _TF[key] = (weight, style, rt)
    return _TF[key]


def text_layout(el, fs, width):
    """Exactly what the converter + renderer do: wrap at float size (we only use ints),
    draw at int size + letter_spacing. Returns (lines, max_line_w, block_h)."""
    content = str(el.get("content", ""))
    key = (id(el), fs, round(width, 1))
    if key in _LAY:
        return _LAY[key]
    weight, style, rt = _faces(el)
    ck = (id(el), fs)
    if ck not in _CW:
        try:
            _CW[ck] = char_widths(fm(), el.get("font_family"), weight, style, float(fs), content)
        except Exception:
            _CW[ck] = [0.55 * fs] * len(content)
    lines = wrap_text(content, _CW[ck], width).split("\n")
    ls = float(el.get("letter_spacing", 0) or 0)
    if rt is not None:
        f = skia.Font(rt, int(fs))
        lws = [sum(f.getWidths(f.textToGlyphs(ln))) + ls * max(0, len(ln) - 1) for ln in lines]
        m = f.getMetrics()
        asc_desc = m.fDescent - m.fAscent
    else:
        lws = [0.55 * fs * len(ln) + ls * max(0, len(ln) - 1) for ln in lines]
        asc_desc = 1.2 * fs
    lh = float(el.get("line_height", 1.2) or 1.2)
    res = (lines, max(lws) if lws else 0.0, (len(lines) - 1) * fs * lh + asc_desc)
    _LAY[key] = res
    return res


def fit_text(el, fs, avail, floor=1):
    """Largest integer font <= fs whose wrapped block fits avail width (no overflow,
    letter-spacing included). Returns (fs, box_w, block_h, lines)."""
    fs = max(1, int(fs))
    while True:
        w = avail
        for _ in range(4):
            lines, mw, bh = text_layout(el, fs, w)
            if mw <= w + 0.5:
                bw = min(avail, math.ceil(mw) + 1)
                if text_layout(el, fs, bw)[0] != lines:
                    bw = w
                return fs, bw, bh, lines
            w = w - (mw - w) - 1
            if w < 0.4 * avail:
                break
        if fs <= floor:  # cannot fit at the floor: report true width -> candidate is infeasible
            lines, mw, bh = text_layout(el, fs, avail)
            return fs, max(avail, math.ceil(mw) + 1), bh, lines
        fs = max(floor, fs - 1 if fs < 24 else int(fs * 0.93))


# ------------------------------------------------------------------ geometry helpers
def rot_aabb(x, y, w, h, deg):
    if not deg:
        return (x, y, x + w, y + h)
    cx, cy, t = x + w / 2, y + h / 2, math.radians(deg)
    c, s = abs(math.cos(t)), abs(math.sin(t))
    hw, hh = (w * c + h * s) / 2, (w * s + h * c) / 2
    return (cx - hw, cy - hh, cx + hw, cy + hh)


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter(a, b):
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def union(bs):
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def alpha(c):
    m = re.findall(r"[\d.]+", str(c or ""))
    return float(m[3]) if len(m) >= 4 else 1.0


def eff_opacity(el):
    a = float(el.get("opacity", 1) if el.get("opacity") is not None else 1)
    return a * alpha(el.get("fill_color")) if el["type"] == "shape" else a


def missing(el):
    return el["type"] == "image" and not (REPO / "brand_kit" / "assets" / str(el.get("asset_id", ""))).is_file()


def asset_size(aid):
    if aid not in ASSET_SIZE:
        try:
            from PIL import Image
            im = Image.open(REPO / "brand_kit" / "assets" / aid)
            bb = im.split()[-1].getbbox() if im.mode in ("RGBA", "LA") else None
            ASSET_SIZE[aid] = (im.size, bb or (0, 0) + im.size)
        except Exception:
            ASSET_SIZE[aid] = None
    return ASSET_SIZE[aid]


def visible_box(el):
    x, y, w, h = el["x"], el["y"], el["width"], el["height"]
    if el["type"] == "text":
        lines, mw, bh = text_layout(el, max(1, int(el.get("font_size", 24))), w)
        al = el.get("text_align", "left")
        x0 = (w - mw) / 2 if al == "center" else (w - mw if al == "right" else 0)
        b = (x + x0, y, x + x0 + mw, y + bh)
    elif el["type"] == "image" and el.get("fit", "contain") == "contain" and asset_size(el.get("asset_id", "")):
        (iw, ih), ab = asset_size(el["asset_id"])
        s = min(w / iw, h / ih)
        ox, oy = x + (w - iw * s) / 2, y + (h - ih * s) / 2  # opaque-pixel box of the letterboxed asset
        b = (ox + ab[0] * s, oy + ab[1] * s, ox + ab[2] * s, oy + ab[3] * s)
    else:
        b = (x, y, x + w, y + h)
    r = el.get("rotation") or 0
    return rot_aabb(b[0], b[1], b[2] - b[0], b[3] - b[1], r) if r else b


def hull_box(el):
    """Everything that must stay on canvas: rotated element box + text ink."""
    ax = (el["x"], el["y"], el["x"] + el["width"], el["y"] + el["height"])  # main.py checks this box
    b = union([ax, rot_aabb(el["x"], el["y"], el["width"], el["height"], el.get("rotation") or 0)])
    return union([b, visible_box(el)]) if el["type"] == "text" else b


# ------------------------------------------------------------------ analysis
def analyse(src, merge_overlap=True):
    cw, ch = src["canvas"]["width"], src["canvas"]["height"]
    els = src["elements"]
    bgs, decor, content = [], [], []
    for e in els:
        if e["type"] != "text" and inter((e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]),
                                         (0, 0, cw, ch)) >= 0.9 * cw * ch:
            bgs.append(e)
        elif e["type"] == "shape" and eff_opacity(e) < 0.5:
            decor.append(e)
        else:
            content.append(e)
    par = list(range(len(content)))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i
    vb = [visible_box(e) for e in content]
    for i, j in itertools.combinations(range(len(content)), 2):
        gi, gj = content[i].get("group_id"), content[j].get("group_id")
        sm = min(area(vb[i]), area(vb[j])) or 1
        ov = inter(vb[i], vb[j]) / sm >= 0.5
        if (gi and gi == gj) or (ov and (merge_overlap or containment(content[i], content[j]))):
            par[find(i)] = find(j)
    clusters = {}
    for i, e in enumerate(content):
        clusters.setdefault(find(i), []).append(e)
    leaves = [make_leaf(es) for es in clusters.values()]
    free_decor = []
    for d in decor:  # decor mostly covering one block travels with it (glow behind product)
        db = hull_box(d)
        best = max(leaves, key=lambda L: inter(db, L["box"]), default=None)
        if best is not None and inter(db, best["box"]) >= 0.5 * area(db):
            best["els"].append(d)
            best["box"] = union([best["box"], db])
            best["kind"] = "rigid"
        else:
            free_decor.append(d)
    fmax = max([e["font_size"] for e in els if e["type"] == "text"] or [1])
    amax = max([area(L["box"]) for L in leaves] or [1])
    importance(leaves, fmax, amax)
    leaves = [containerise(L, fmax, amax) for L in leaves]
    return bgs, free_decor, leaves, fmax


def contains(s_, o):
    """Directional: filled unrotated shape s_ holds >=90% of o's ink (pill / panel behind text)."""
    if s_["type"] != "shape" or s_.get("shape_type") == "line" or s_.get("rotation") or o.get("rotation"):
        return False
    return inter((s_["x"], s_["y"], s_["x"] + s_["width"], s_["y"] + s_["height"]), visible_box(o)) >= 0.9 * area(visible_box(o))


def containment(a, b):
    """A filled, unrotated shape that contains the other element (panel / pill behind text)."""
    for s_, o in ((a, b), (b, a)):
        if s_["type"] == "shape" and s_.get("shape_type") != "line" and not s_.get("rotation") and not o.get("rotation"):
            sb = (s_["x"], s_["y"], s_["x"] + s_["width"], s_["y"] + s_["height"])
            ob = visible_box(o)
            if inter(sb, ob) >= 0.9 * area(ob):
                return True
    return False


def containerise(L, fmax, amax):
    """Cluster = [shape containing all others] -> container node whose content can reflow."""
    es = L["els"]
    if len(es) < 2 or L["kind"] != "rigid":
        return L
    for sh in es:
        rest = [e for e in es if e is not sh]
        if sh["type"] == "shape" and all(contains(sh, e) for e in rest) and any(e["type"] == "text" for e in rest):
            kids = [make_leaf([e]) for e in rest]
            importance(kids, fmax, amax)
            sub = xycut(kids)
            ib = union([k["ink"] for k in kids])  # padding measured to the label ink, not its loose box
            sb = (sh["x"], sh["y"], sh["x"] + sh["width"], sh["y"] + sh["height"])
            pad = (ib[0] - sb[0], ib[1] - sb[1], sb[2] - ib[2], sb[3] - ib[3])
            return {"o": "C", "shape": sh, "kids": [sub], "align": ["s"], "pad": pad, "box": sb, "els": es,
                    "imp": L["imp"], "ftop": max(e["font_size"] for e in rest if e["type"] == "text")}
    return L


def importance(leaves, fmax, amax):
    for L in leaves:  # importance without labels: type size, ink area, colour alpha
        imp = 0.3
        for e in L["els"]:
            if e["type"] == "text":
                v = (e["font_size"] / fmax) ** 0.7 * (1.15 if conv._normalize_weight(e.get("font_weight")) == "bold" else 1)
                v *= 0.6 if alpha(e.get("color")) < 0.75 else 1
            elif e["type"] == "image":
                v = 0.25 + 0.75 * math.sqrt(area(L["box"]) / amax)
                v = 0.15 if missing(e) else v  # placeholder box: demote, never hide
            else:
                v = 0.3
            imp = max(imp, v)
        L["imp"] = imp


def make_leaf(es):
    box = union([hull_box(e) for e in es])
    texts = [e for e in es if e["type"] == "text"]
    single_text = len(es) == 1 and texts and not (es[0].get("rotation") or 0)
    return {"leaf": True, "els": es, "box": box, "ink": union([visible_box(e) for e in es]), "kind": "text" if single_text else "rigid",
            "has_text": bool(texts), "fmin": min([e["font_size"] for e in texts] or [0]),
            "ftop": max([e["font_size"] for e in texts] or [0])}


def xycut(items):
    if len(items) == 1:
        return items[0]
    best = None
    for o, a0, a1 in (("V", 1, 3), ("H", 0, 2)):
        its = sorted(items, key=lambda L: L["box"][a0])
        groups, cur, end, gaps = [], [its[0]], its[0]["box"][a1], []
        pext = its[0]["box"][a1] - its[0]["box"][a0]
        for L in its[1:]:
            ext_l = L["box"][a1] - L["box"][a0]
            if L["box"][a0] >= end - max(2, 0.3 * min(ext_l, pext)):
                groups.append(cur)
                gaps.append(L["box"][a0] - end)
                cur = []
            cur.append(L)
            if L["box"][a1] > end:
                end, pext = L["box"][a1], ext_l
        groups.append(cur)
        if len(groups) > 1:
            ext = max(L["box"][a1] for L in items) - min(L["box"][a0] for L in items)
            g = max(gaps) / (ext or 1)
            if best is None or g > best[0]:
                best = (g, o, groups)
    if best is None:  # no clean cut: force the least-overlapping split by centre order
        for o, a0, a1 in (("V", 1, 3), ("H", 0, 2)):
            bx = lambda L: L.get("ink", L["box"])  # noqa: E731  ink, not the (possibly loose) text box
            its = sorted(items, key=lambda L: bx(L)[a0] + bx(L)[a1])
            for k in range(1, len(its)):
                ov = max(bx(L)[a1] for L in its[:k]) - min(bx(L)[a0] for L in its[k:])
                ext = min(min(bx(L)[a1] - bx(L)[a0] for L in its[:k]), min(bx(L)[a1] - bx(L)[a0] for L in its[k:]))
                r = ov / max(ext, 1)
                if r < 0.6 and (best is None or -r > best[0]):
                    best = (-r, o, [its[:k], its[k:]])
    if best is None:  # still nothing: overlapping cluster moves as one rigid unit
        m = make_leaf([e for L in items for e in L["els"]])
        m["kind"], m["imp"] = "rigid", max(L["imp"] for L in items)
        return m
    _, o, groups = best
    kids = []
    for g in groups:
        k = xycut(g)
        kids.extend(k["kids"] if not k.get("leaf") and k["o"] == o else [k])
    node = {"o": o, "kids": kids}
    node["box"] = union([k["box"] for k in kids])
    node["align"] = [src_align(node, k) for k in kids]
    return node


def src_align(node, kid):
    a0, a1 = (0, 2) if node["o"] == "V" else (1, 3)
    l = kid["box"][a0] - node["box"][a0]
    r = node["box"][a1] - kid["box"][a1]
    ext = node["box"][a1] - node["box"][a0]
    return "c" if abs(l - r) < 0.15 * ext else ("s" if l < r else "e")


def leaves_of(n):
    return [n] if n.get("leaf") else [L for k in n["kids"] for L in leaves_of(k)]


def need(n):
    """Ink area a subtree's text wants (chars x fs^2) -> share of width in an H stack."""
    a = 0.0
    for L in leaves_of(n):
        for e in L["els"]:
            if e["type"] == "text":
                a += max(4, len(str(e.get("content", "")))) * e["font_size"] ** 2 * 0.6
            else:
                a += 0.5 * (L["box"][2] - L["box"][0]) * (L["box"][3] - L["box"][1]) / max(1, len(L["els"]))
    return math.sqrt(max(a, 1.0))


def has_flex(n):
    return any(L["kind"] == "text" for L in leaves_of(n))


# ------------------------------------------------------------------ candidate structures
def inner_nodes(n, acc):
    if not n.get("leaf"):
        for k in n["kids"]:
            if not k.get("leaf"):
                if k["o"] != "C":
                    acc.append(k)
                inner_nodes(k, acc)
    return acc


def mk(o, kids, align=None):
    flat, fal = [], []
    for i, k in enumerate(kids):
        if not k.get("leaf") and k["o"] == o:
            flat.extend(k["kids"])
            fal.extend(k["align"])
        else:
            flat.append(k)
            fal.append(align[i] if align else "c")
    if len(flat) == 1:
        return flat[0]
    return {"o": o, "kids": flat, "align": fal, "box": union([k["box"] for k in flat])}


def rebuild(n, flips):
    if n.get("leaf"):
        return n
    kids = [rebuild(k, flips) for k in n["kids"]]
    if n["o"] == "C":
        return dict(n, kids=kids)
    if id(n) in flips:
        return mk("H" if n["o"] == "V" else "V", kids)
    return mk(n["o"], kids, n["align"])


def structures(tree, max_cands=400):
    root = tree if not tree.get("leaf") else {"o": "V", "kids": [tree], "align": ["c"], "box": tree["box"]}
    inn = inner_nodes(root, [])
    # hard constraint: repeated structures (same orientation, kid count, ~same kid sizes) flip together
    sig = {}
    for x in inn:
        dims = tuple(sorted((round((k["box"][2] - k["box"][0]) / 20), round((k["box"][3] - k["box"][1]) / 20)) for k in x["kids"]))
        sig.setdefault((x["o"], len(x["kids"]), dims), []).append(x)
    classes = list(sig.values())
    if len(classes) <= 5:
        flipsets = [set(id(x) for c, f in zip(classes, bits) if f for x in c)
                    for bits in itertools.product([0, 1], repeat=len(classes))]
    else:
        flipsets = [set(), set(id(x) for x in inn)] + [set(id(x) for x in inn if x["o"] == o) for o in "HV"]
    out = []
    for fl in flipsets:
        kids = [rebuild(k, fl) for k in root["kids"]]
        n = len(kids)
        for o in "VH":
            al = root["align"] if o == root["o"] else None
            for k in range(1, min(4, n) + 1):
                if k > 1 and n < 3:
                    continue
                for cuts in itertools.combinations(range(1, n), k - 1):
                    if k == 1:
                        st = mk(o, kids, al)
                    else:
                        b = (0,) + cuts + (n,)
                        st = mk(o, [mk("H" if o == "V" else "V", kids[b[i]:b[i + 1]]) for i in range(k)])
                    out.append((st, len(fl) + 2 * (k - 1) + (o != root["o"])))
    return out[:max_cands]


# ------------------------------------------------------------------ evaluation of one candidate
class Ctx:
    def __init__(self, W, H, sw, sh, fmax, compact=False):
        self.W, self.H, self.src = W, H, (sw, sh)
        self.m = 2.0 if compact else max(4.0, min(64.0, 0.045 * min(W, H)))
        self.g = 2.0 if compact else max(3.0, min(36.0, 0.022 * min(W, H) + 0.008 * max(W, H)))
        self.snat = math.sqrt(W * H / (sw * sh))
        self.fref = fmax
        self.floor0 = max(9, round(0.0105 * math.sqrt(W * H)))
        self.minimg = max(16.0, 0.18 * min(W, H))      # floor for an image's VISIBLE short side
        self.missing_cap = max(16.0, 0.12 * min(W, H))  # cap for a missing-asset placeholder
        self.low_floor = None   # emergency floor for below-median-importance text (set by resize)
        self.imp_med = 0.0
        self.fmin_text = 1.0
        self.bump = True        # hierarchy +1px rule (dropped only in the very last stage)
        self.aw, self.ah = W - 2 * self.m, H - 2 * self.m

    def text_floor(self, L, floor, src_fs):
        """Floor for one text: emergency floor only for below-median importance; text that was
        >=15% larger than the smallest source text keeps one extra px (never equalise hierarchy)."""
        f = floor
        if self.low_floor is not None and L.get("imp", 1.0) < self.imp_med:
            f = min(f, self.low_floor)
        return f + (1 if self.bump and src_fs >= 1.15 * self.fmin_text else 0)


def leaf_scale(L, P, C):
    s, rho, gam, floor = P
    bw, bh = L["box"][2] - L["box"][0], L["box"][3] - L["box"][1]
    if L["has_text"]:
        sb = min(s * rho * (C.fref / L["ftop"]) ** (1 - gam), max(s * rho, 1.25 * C.snat))
        sb = max(sb, floor / L["fmin"])
    else:
        sb = s
        ink = L.get("ink", L["box"])
        vis = [d for d in (ink[2] - ink[0], ink[3] - ink[1]) if d >= 1] or [1.0]
        if any(e["type"] == "image" for e in L["els"]):
            want = min(C.minimg, 1.5 * C.snat * min(vis))
            sb = max(sb, want / min(vis))
            if all(missing(e) for e in L["els"] if e["type"] == "image"):
                sb = min(sb, C.missing_cap / min(vis))
        else:  # rules / lines: minimum on their long side
            sb = max(sb, 12.0 / max(vis))
    return min(sb, C.aw / max(bw, 1), C.ah / max(bh, 1))


def size(n, avail, P, C, S):
    if n.get("leaf"):
        if n["kind"] == "text":
            e = n["els"][0]
            s, rho, gam, floor = P
            k = min(s * rho * (C.fref / e["font_size"]) ** (1 - gam), max(s * rho, 1.25 * C.snat))
            fl = C.text_floor(n, floor, e["font_size"])
            want = max(fl, round(k * e["font_size"]))
            fs, bw, bh, lines = fit_text(e, want, max(avail, 1), fl)
            S[id(n)] = (bw, math.ceil(bh), fs, lines)
        else:
            sb = leaf_scale(n, P, C)
            bad = n["has_text"] and sb * n["fmin"] < C.text_floor(n, P[3], 0) - 0.01  # rigid text under floor
            S[id(n)] = ((n["box"][2] - n["box"][0]) * sb + (1e6 if bad else 0), (n["box"][3] - n["box"][1]) * sb, sb)
        return S[id(n)][:2]
    g = C.g
    if n["o"] == "C":
        s, rho, gam, floor = P
        k = min(1.0 * s * rho, max(1.0, C.snat))
        pl, pt, pr, pb = n["pad"]
        cw_, ch_ = size(n["kids"][0], max(1.0, avail - (pl + pr) * k), P, C, S)
        fs = [S[id(L)][2] / L["els"][0]["font_size"] for L in leaves_of(n) if L["kind"] == "text"]
        k = max(min(fs + [k]) if fs else k, 0.0)
        S[id(n)] = (cw_ + (pl + pr) * k, ch_ + (pt + pb) * k, k)
        return S[id(n)][:2]
    if n["o"] == "V":
        ws, hs = zip(*[size(k, avail, P, C, S) for k in n["kids"]])
        S[id(n)] = (max(ws), sum(hs) + g * (len(hs) - 1))
    else:
        fixed = {i: size(k, 1e9, P, C, S) for i, k in enumerate(n["kids"]) if not has_flex(k)}
        rem = avail - sum(w for w, _ in fixed.values()) - g * (len(n["kids"]) - 1)
        flex = [i for i in range(len(n["kids"])) if i not in fixed]
        wt = {i: need(n["kids"][i]) for i in flex}
        tot = sum(wt.values()) or 1
        dims = dict(fixed)
        for i in flex:
            dims[i] = size(n["kids"][i], max(1.0, rem * wt[i] / tot), P, C, S)
        ws = [dims[i][0] for i in range(len(n["kids"]))]
        hs = [dims[i][1] for i in range(len(n["kids"]))]
        S[id(n)] = (sum(ws) + g * (len(ws) - 1), max(hs))
    return S[id(n)]


def feasible(st, P, C):
    S = {}
    w, h = size(st, C.aw, P, C, S)
    return w <= C.aw + 0.5 and h <= C.ah + 0.5, S


def solve(st, C, rho, gam, floors=None):
    """Pressure levels relax the font floor (never below ABS_FLOOR unless emergency floors
    are passed explicitly); binary search the global scale s."""
    floors = floors or [max(ABS_FLOOR, int(C.floor0 * m)) for m in (1.0, 0.85, 0.7)] + [ABS_FLOOR]
    for lvl, floor in enumerate(floors):
        lo, hi = C.snat * 0.02, C.snat * 1.15
        ok, S = feasible(st, (hi, rho, gam, floor), C)
        if ok:
            return (hi, rho, gam, floor), S, lvl
        ok, S = feasible(st, (lo, rho, gam, floor), C)
        if not ok:
            continue
        for _ in range(13):
            mid = math.sqrt(lo * hi)
            ok2, S2 = feasible(st, (mid, rho, gam, floor), C)
            if ok2:
                lo, S = mid, S2
            else:
                hi = mid
        return (lo, rho, gam, floor), S, lvl
    return None


def place(n, x, y, w, h, S, C, pos, root=False):
    nw, nh = S[id(n)][:2]
    if n.get("leaf"):
        pos[id(n)] = (x, y)
        return
    if n["o"] == "C":
        pos[id(n)] = (x, y)
        k = S[id(n)][2]
        kw, kh = S[id(n["kids"][0])][:2]
        place(n["kids"][0], x + n["pad"][0] * k, y + n["pad"][1] * k, kw, kh, S, C, pos)
        return
    V = n["o"] == "V"
    kids = n["kids"]
    dims = [S[id(k)][:2] for k in kids]
    g, lead = C.g, 0.0
    if root:
        extra = (h - nh) if V else (w - nw)
        d = min(extra / (len(kids) + 1), 2.5 * g)
        g, lead = g + d, (extra - d * (len(kids) - 1)) / 2
    cur = (y if V else x) + lead
    for k, (kw, kh), al in zip(kids, dims, n["align"]):
        if root:
            al = "c" if al == "c" or n["o"] != "V" else al
        if V:
            off = 0 if al == "s" else ((w - kw) / 2 if al == "c" else w - kw)
            place(k, x + off, cur, kw, kh, S, C, pos)
            cur += kh + g
        else:
            off = (h - kh) / 2 if al != "s" else 0
            place(k, cur, y + off, kw, kh, S, C, pos)
            cur += kw + g


def score(st, P, S, lvl, cost, C, src_leaves):
    pos = {}
    rw, rh = S[id(st)][:2]
    place(st, C.m, C.m, C.aw, C.ah, S, C, pos, root=True)
    leaves = leaves_of(st)
    tot = sum(L["imp"] for L in leaves) or 1
    size_t = read_t = lines_t = 0.0
    fonts = []
    for L in leaves:
        if L["kind"] == "text":
            e = L["els"][0]
            fs, lines = S[id(L)][2], S[id(L)][3]
            eff = fs / e["font_size"]
            fonts.append((e["font_size"], fs))
            read_t += max(0, C.floor0 - fs) / C.floor0
            words = len(str(e.get("content", "")).split())
            if words > 1:
                lines_t += 0.03 * sum(1 for ln in lines if len(ln.split()) == 1 and len(lines) > 1)
            lines_t += 0.02 * max(0, len(lines) - 6)
        else:
            eff = S[id(L)][2]
            fonts += [(e["font_size"], max(1, int(e["font_size"] * eff))) for e in L["els"] if e["type"] == "text"]
            bw, bh = S[id(L)][:2]
            if min(bw, bh) < 0.08 * min(C.W, C.H):
                read_t += 0.3
        size_t += L["imp"] * max(0.0, math.log(C.snat / max(eff, 1e-6)))
    inv = sum(1 for (a, fa), (b, fb) in itertools.combinations(fonts, 2) if (a - b * 1.15) * (fa - fb) < 0 and fa != fb
              and abs(a - b) > 0.15 * max(a, b))
    fill = (rw * rh) / (C.aw * C.ah)
    rel = 0
    pairs = list(itertools.combinations(leaves, 2))
    for A, B in pairs:  # reading-relation fidelity (above/below vs left/right)
        sx = (A["box"][0] + A["box"][2] - B["box"][0] - B["box"][2]) / 2
        sy = (A["box"][1] + A["box"][3] - B["box"][1] - B["box"][3]) / 2
        ox, oy = pos[id(A)][0] - pos[id(B)][0], pos[id(A)][1] - pos[id(B)][1]
        rel += (abs(sx) > abs(sy)) != (abs(ox) > abs(oy))
    rel /= max(1, len(pairs))
    total = (1.0 * size_t / tot + 2.0 * read_t + 0.15 * inv / max(1, len(fonts)) + 0.5 * (1 - fill)
             + 0.2 * rel + lines_t + 0.02 * cost + 0.4 * lvl)
    return total, pos


# ------------------------------------------------------------------ output
def containers(n):
    if n.get("leaf"):
        return []
    return ([n] if n["o"] == "C" else []) + [c for k in n["kids"] for c in containers(k)]


def emit(st, S, pos, C, out_by):
    for n in containers(st):
        x, y = pos[id(n)]
        w, h = S[id(n)][:2]
        out_by[n["shape"]["id"]].update(x=x, y=y, width=w, height=h)
    for L in leaves_of(st):
        x, y = pos[id(L)]
        if L["kind"] == "text":
            e = out_by[L["els"][0]["id"]]
            bw, bh, fs, _ = S[id(L)]
            e.update(x=x, y=y, width=max(1.0, bw), height=max(1.0, math.ceil(bh)), font_size=fs)
            continue
        sb = S[id(L)][2]
        bx, by = L["box"][0], L["box"][1]
        for se in L["els"]:
            e = out_by[se["id"]]
            e.update(x=x + (se["x"] - bx) * sb, y=y + (se["y"] - by) * sb,
                     width=se["width"] * sb, height=se["height"] * sb)
            if se["type"] == "text":
                fs = max(1, int(se["font_size"] * sb))
                while fs > 1 and text_layout(se, fs, e["width"])[1] > e["width"] + 0.5:
                    fs -= 1
                e["font_size"] = fs
                bh = text_layout(se, fs, e["width"])[2]
                e["width"] = max(1.0, e["width"])
                e["height"] = max(1.0, e["height"], math.ceil(bh))


def clamp_inside(e, W, H, allow_shrink=True):
    """Both the axis box (main.py self-check) and the rotated AABB (pixels) must be on canvas.
    They share a centre, so clamp the centre by the larger half-extent of the two."""
    def ext():
        b = rot_aabb(0, 0, e["width"], e["height"], e.get("rotation") or 0)
        return max(e["width"], b[2] - b[0]), max(e["height"], b[3] - b[1])
    bw, bh = ext()
    if allow_shrink and (bw > W or bh > H):
        k = min(W / bw, H / bh) * 0.999
        cx, cy = e["x"] + e["width"] / 2, e["y"] + e["height"] / 2
        e["width"], e["height"] = e["width"] * k, e["height"] * k
        e["x"], e["y"] = cx - e["width"] / 2, cy - e["height"] / 2
        if e["type"] == "text":
            fs = max(1, int(e["font_size"] * k))
            while fs > 1 and text_layout(e, fs, e["width"])[1] > e["width"] + 0.5:
                fs -= 1
            e["font_size"] = fs
        bw, bh = ext()
    cx = min(max(e["x"] + e["width"] / 2, bw / 2), W - bw / 2)
    cy = min(max(e["y"] + e["height"] / 2, bh / 2), H - bh / 2)
    e["x"], e["y"] = cx - e["width"] / 2, cy - e["height"] / 2


def finish(out, src, bgs, decor, W, H):
    sw, sh = src["canvas"]["width"], src["canvas"]["height"]
    by = {e["id"]: e for e in out["elements"]}
    for b in bgs:
        by[b["id"]].update(x=0, y=0, width=W, height=H)
    k = min(W / sw, H / sh) ** 0.5 * max(W / sw, H / sh) ** 0.5
    k = min(k, 0.6 * min(W, H) / max(1, max((d["width"] for d in decor), default=1)) if decor else k)
    for d in decor:  # decorative wash: keep relative position, scale, clamp
        cx, cy = (d["x"] + d["width"] / 2) / sw * W, (d["y"] + d["height"] / 2) / sh * H
        by[d["id"]].update(width=d["width"] * k, height=d["height"] * k,
                           x=cx - d["width"] * k / 2, y=cy - d["height"] * k / 2)
    for e in out["elements"]:
        clamp_inside(e, W, H)
        for f in ("x", "y", "width", "height"):
            e[f] = round(float(e[f]), 2)
    return out


def place_backdrop(ls, C, out_by):
    """Image-only blocks spread evenly behind the text flow, each fitted to its slot."""
    ls = sorted(ls, key=lambda L: L["box"][0] + L["box"][1])
    slot = C.aw / max(1, len(ls))
    for i, L in enumerate(ls):
        bw, bh = L["box"][2] - L["box"][0], L["box"][3] - L["box"][1]
        sb = min(slot / max(bw, 1), C.ah / max(bh, 1))
        ink = L.get("ink", L["box"])
        vis = max(1.0, min(ink[2] - ink[0], ink[3] - ink[1]))
        if all(missing(e) for e in L["els"] if e["type"] == "image"):
            sb = min(sb, C.missing_cap / vis)
        x0, y0 = C.m + i * slot + (slot - bw * sb) / 2, C.m + (C.ah - bh * sb) / 2
        for se in L["els"]:
            out_by[se["id"]].update(x=x0 + (se["x"] - L["box"][0]) * sb, y=y0 + (se["y"] - L["box"][1]) * sb,
                                    width=se["width"] * sb, height=se["height"] * sb)


def _fit_in_box(e):
    """Largest integer font that fits the element's own box; if even 1px does not fit
    (e.g. big fixed letter_spacing) grow the box to the drawn text instead of overflowing."""
    e["width"], e["height"] = max(1.0, float(e["width"])), max(1.0, float(e["height"]))
    fs = max(1, int(e["font_size"]))
    while True:
        _, mw, bh = text_layout(e, fs, e["width"])
        if mw <= e["width"] + 0.5 and bh <= e["height"] + 0.5:
            break
        if fs == 1:
            if mw > e["width"]:
                al = e.get("text_align", "left")
                grow = mw + 1.0 - e["width"]
                e["x"] -= grow * (0.5 if al == "center" else 1.0 if al == "right" else 0.0)
                e["width"] += grow
            e["height"] = max(e["height"], math.ceil(text_layout(e, fs, e["width"])[2]) + 1.0)
            break
        fs -= 1
    e["font_size"] = fs


def fallback(src, W, H, bgs, decor):
    """Step-1 letterbox: one uniform scale, centred. Always compliant; used only if the
    search finds nothing (never happened on the 57 test cases)."""
    sw, sh = src["canvas"]["width"], src["canvas"]["height"]
    s = min(W / sw, H / sh)
    ox, oy = (W - sw * s) / 2, (H - sh * s) / 2
    out = {"canvas": {"width": W, "height": H}, "elements": copy.deepcopy(src["elements"])}
    bg_ids = {b["id"] for b in bgs}
    for e in out["elements"]:
        if e["id"] in bg_ids:
            continue
        e.update(x=ox + e["x"] * s, y=oy + e["y"] * s, width=e["width"] * s, height=e["height"] * s)
        if e["type"] == "text":
            e["font_size"] = max(1, int(e["font_size"] * s))
            _fit_in_box(e)
    return finish(out, src, bgs, [], W, H)


def _candidates(tree, C):
    scored = []
    for st, cost in structures(tree):
        r = solve(st, C, 1.0, 1.0)
        if r:
            P, S, lvl = r
            scored.append((score(st, P, S, lvl, cost, C, None)[0], id(st), st, cost))
    return scored


def _engine(src, W, H):
    bgs, decor, leaves, fmax = analyse(src)
    if not leaves:
        return fallback(src, W, H, bgs, decor), "fallback"
    texts = [e for e in src["elements"] if e["type"] == "text"]
    fmin_text = min([e["font_size"] for e in texts] or [1])
    imps = sorted(L["imp"] for L in leaves_of({"kids": leaves}) if L.get("has_text") or L.get("o") == "C")
    imp_med = imps[len(imps) // 2] if imps else 0.0

    def ctx(compact=False, low=None, everyone=False):
        C = Ctx(W, H, src["canvas"]["width"], src["canvas"]["height"], fmax, compact=compact)
        C.fmin_text, C.low_floor = fmin_text, low
        C.imp_med = float("inf") if everyone else imp_med
        C.bump = not everyone
        return C

    # Over-constrained policy -- what gives, in order (never hide, overflow, go off-canvas,
    # or put text on text):
    #   normal -> compact margins/gaps -> image-only blocks become a backdrop row behind the
    #   text -> below-median-importance text may drop to 5px, then 4px -> then all text may.
    flow_all = leaves
    flow_txt = [L for L in leaves if L.get("has_text") or L.get("o") == "C"] or leaves
    stages = [("normal", ctx(), flow_all), ("compact", ctx(True), flow_all),
              ("backdrop", ctx(True), flow_txt)]
    stages += [("emergency%d" % f, ctx(True, f), flow_txt) for f in EMERGENCY_FLOORS]
    stages += [("emergency%d_all" % f, ctx(True, f, everyone=True), flow_txt) for f in EMERGENCY_FLOORS]
    for stage, C, flow in stages:
        scored = _candidates(xycut(flow), C)
        if scored:
            break
    else:
        return fallback(src, W, H, bgs, decor), "fallback"

    out = {"canvas": {"width": W, "height": H}, "elements": copy.deepcopy(src["elements"])}
    by_id = {e["id"]: e for e in out["elements"]}
    if flow is not flow_all:
        place_backdrop([L for L in leaves if L not in flow], C, by_id)
    scored.sort(key=lambda t: t[:2])
    best = None
    for _, _, st, cost in scored[:5]:          # refine: text/image ratio x hierarchy compression
        for rho in (1.0, 1.33):
            for gam in (1.0, 0.8):
                r = solve(st, C, rho, gam)
                if not r:
                    continue
                P, S, lvl = r
                sc, pos = score(st, P, S, lvl, cost, C, None)
                sc += 0.03 * (abs(math.log(rho)) + (1 - gam))
                if best is None or sc < best[0]:
                    best = (sc, st, S, pos)
    emit(best[1], best[2], best[3], C, by_id)
    return finish(out, src, bgs, decor, W, H), stage


def resize(source, target_canvas):
    _LAY.clear()
    _CW.clear()
    W, H = int(target_canvas["width"]), int(target_canvas["height"])
    src = copy.deepcopy(source)  # never touch the caller's dict
    try:
        out, stage = _engine(src, W, H)
    except Exception as ex:  # a bug must never cost a task: fall back to the compliant letterbox
        print(f"[resize] engine error {ex!r}; using letterbox fallback", file=sys.stderr)
        cw, ch = src["canvas"]["width"], src["canvas"]["height"]
        bgs = [e for e in src["elements"] if e["type"] != "text" and inter(
            (e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]), (0, 0, cw, ch)) >= 0.9 * cw * ch]
        out, stage = fallback(src, W, H, bgs, []), "fallback"
    if stage != "normal":
        print(f"[resize] PRESSURE={stage}", file=sys.stderr)
    return out
