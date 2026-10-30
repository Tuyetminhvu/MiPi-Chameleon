"""Arena harness: run a resize() implementation over task JSONs, render through
the OFFICIAL renderer path, and compute exact geometry checks + visual estimates.

Usage (from anywhere):
  python3 harness.py --repo /tmp/chameleon --resize path/to/resize.py \
      --cases cases_dir --out out_dir [--sheet]

This is NOT the official scorer. "exact" metrics replicate the renderer's own
wrap/measure code; "estimate" metrics (contrast, busy background) are heuristics.
"""
import argparse
import importlib.util
import json
import math
import statistics
import sys
import time
import traceback
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--repo", required=True)
ap.add_argument("--resize", required=True)
ap.add_argument("--cases", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--sheet", action="store_true", help="write a contact sheet PNG")
ap.add_argument("--filter", default="", help="substring filter on case names")
args = ap.parse_args()

REPO = Path(args.repo).resolve()
sys.path.insert(0, str(REPO))
from PIL import Image  # noqa: E402
from renderer.converter import convert as conv  # noqa: E402
from renderer.converter.wrap import char_widths, wrap_text  # noqa: E402
from renderer.converter.colorutil import parse_rgba  # noqa: E402
import skia  # noqa: E402

ASSETS = REPO / "brand_kit" / "assets"
FONTS = REPO / "brand_kit" / "fonts"
RENDERER = conv._get_renderer(str(FONTS))
FM = RENDERER.font_manager

MUTABLE = {"x", "y", "width", "height", "font_size"}
REQ_COMMON = ["id", "type", "x", "y", "width", "height"]
REQ_TYPE = {"text": ["content", "font_family", "font_size", "color"],
            "image": ["asset_id"], "shape": ["shape_type", "fill_color"]}


def load_resize(path):
    spec = importlib.util.spec_from_file_location("cand_resize", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.resize


# ---------------------------------------------------------------- geometry
def rot_aabb(x, y, w, h, deg):
    if not deg:
        return (x, y, x + w, y + h)
    cx, cy = x + w / 2, y + h / 2
    t = math.radians(deg)
    c, s = abs(math.cos(t)), abs(math.sin(t))
    hw, hh = (w * c + h * s) / 2, (w * s + h * c) / 2
    return (cx - hw, cy - hh, cx + hw, cy + hh)


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter(a, b):
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def text_layout(el):
    """Replicates converter + cr-renderer text layout. Returns dict with
    lines, rendered ink box (unrotated, element-local -> absolute), overflow."""
    content = str(el.get("content", ""))
    fam = el.get("font_family")
    size = float(el.get("font_size", 24))
    weight = conv._normalize_weight(el.get("font_weight"))
    bold = weight in conv._BOLD_WEIGHTS
    italic = conv._is_italic(el.get("font_style"))
    style = conv._weight_style_to_font_style(bold, italic)
    w = float(el["width"])
    widths = char_widths(FM, fam, weight, style, size, content)  # converter measures at float size
    wrapped = wrap_text(content, widths, w)
    lines = wrapped.split("\n")
    # renderer draws at int(size) with letter spacing
    tf = skia.Typeface.MakeFromData(FM.lookup(fam, "bold" if bold else "regular",
                                               style if style != "regular" else "regular"))
    f = skia.Font(tf, int(size))
    ls = float(el.get("letter_spacing", 0) or 0)
    lws = []
    for ln in lines:
        g = f.textToGlyphs(ln)
        lws.append(sum(f.getWidths(g)) + ls * max(0, len(g) - 1))
    m = f.getMetrics()
    lh = float(el.get("line_height", 1.2))
    block_h = (len(lines) - 1) * size * lh + (m.fDescent - m.fAscent)
    align = el.get("text_align", "left")
    maxw = max(lws) if lws else 0
    if align == "center":
        x0 = (w - maxw) / 2
    elif align == "right":
        x0 = w - maxw
    else:
        x0 = 0
    ink = (el["x"] + x0, el["y"], el["x"] + x0 + maxw, el["y"] + block_h)
    return {"n_lines": len(lines), "max_line_w": maxw, "block_h": block_h,
            "overflow_x": max(0.0, maxw - w), "overflow_y": max(0.0, block_h - float(el["height"])),
            "ink": ink, "int_size": int(size)}


def image_visible_box(el):
    """contain-fit asset rect inside the element box (cover/fill = full box)."""
    x, y, w, h = el["x"], el["y"], el["width"], el["height"]
    if el.get("fit", "contain") != "contain":
        return (x, y, x + w, y + h)
    p = ASSETS / el.get("asset_id", "")
    if not p.is_file():
        return (x, y, x + w, y + h)
    iw, ih = Image.open(p).size
    s = min(w / iw, h / ih)
    nw, nh = iw * s, ih * s
    return (x + (w - nw) / 2, y + (h - nh) / 2, x + (w + nw) / 2, y + (h + nh) / 2)


def ink_box(el):
    if el["type"] == "text":
        b = text_layout(el)["ink"]
    elif el["type"] == "image":
        b = image_visible_box(el)
    else:
        b = (el["x"], el["y"], el["x"] + el["width"], el["y"] + el["height"])
    rot = el.get("rotation", 0) or 0
    if rot:
        cx, cy = el["x"] + el["width"] / 2, el["y"] + el["height"] / 2
        bw, bh = b[2] - b[0], b[3] - b[1]
        # rotate box about element centre (approx: rotate the ink box's own centre offset)
        ox, oy = (b[0] + b[2]) / 2 - cx, (b[1] + b[3]) / 2 - cy
        t = math.radians(rot)
        ncx = cx + ox * math.cos(t) - oy * math.sin(t)
        ncy = cy + ox * math.sin(t) + oy * math.cos(t)
        b = rot_aabb(ncx - bw / 2, ncy - bh / 2, bw, bh, rot)
    return b


def eff_opacity(el):
    a = float(el.get("opacity", 1) if el.get("opacity") is not None else 1)
    if el["type"] == "shape":
        a *= parse_rgba(el.get("fill_color"), (0, 0, 0, 1.0))[3]
    return a


def is_background(el, canvas):
    cw, ch = canvas["width"], canvas["height"]
    b = (el["x"], el["y"], el["x"] + el["width"], el["y"] + el["height"])
    return el["type"] != "text" and inter(b, (0, 0, cw, ch)) >= 0.9 * cw * ch


def is_decor(el):
    return el["type"] == "shape" and eff_opacity(el) < 0.5


# ---------------------------------------------------------------- checks
def check(source, out):
    r = {"errors": [], "warn": []}
    sc, oc = source["canvas"], out.get("canvas", {})
    src_by = {e["id"]: e for e in source["elements"]}
    out_ids = [e.get("id") for e in out.get("elements", [])]
    r["ids_ok"] = sorted(out_ids) == sorted(src_by) and len(out_ids) == len(set(out_ids))
    if not r["ids_ok"]:
        r["errors"].append("id/count mismatch")
    out_by = {e.get("id"): e for e in out.get("elements", [])}
    cw, ch = oc.get("width"), oc.get("height")
    # fields
    changed_immutable = []
    for i, se in src_by.items():
        oe = out_by.get(i)
        if oe is None:
            continue
        for k in REQ_COMMON + REQ_TYPE.get(se["type"], []):
            if k not in oe:
                r["errors"].append(f"{i}: missing {k}")
        for k, v in se.items():
            if k in MUTABLE:
                continue
            if k not in oe or oe[k] != v:
                changed_immutable.append(f"{i}.{k}")
        for k in oe:
            if k not in se and k not in MUTABLE:
                changed_immutable.append(f"{i}.+{k}")
    r["changed_immutable"] = changed_immutable
    if changed_immutable:
        r["warn"].append(f"immutable fields changed: {changed_immutable[:6]}")
    # numeric validity
    for i, oe in out_by.items():
        for k in ("x", "y", "width", "height"):
            v = oe.get(k)
            if not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
                r["errors"].append(f"{i}: bad {k}={v}")
        if oe.get("type") == "text" and not (isinstance(oe.get("font_size"), (int, float)) and oe["font_size"] >= 1):
            r["errors"].append(f"{i}: font_size<1")
    if r["errors"]:
        return r
    # bounds (axis box = what main.py checks) and rotated bbox
    off_axis, off_rot = [], []
    for i, e in out_by.items():
        if e["x"] < -0.5 or e["y"] < -0.5 or e["x"] + e["width"] > cw + 0.5 or e["y"] + e["height"] > ch + 0.5:
            off_axis.append(i)
        rb = rot_aabb(e["x"], e["y"], e["width"], e["height"], e.get("rotation", 0) or 0)
        if e.get("rotation") and (rb[0] < -0.5 or rb[1] < -0.5 or rb[2] > cw + 0.5 or rb[3] > ch + 0.5):
            off_rot.append(i)
    r["off_canvas"] = off_axis
    r["off_canvas_rotated"] = off_rot
    # aspect
    asp = []
    for i, e in out_by.items():
        se = src_by[i]
        if e["type"] == "image" and e.get("fit", "contain") != "cover" and not is_background(se, sc):
            if se["height"] > 0 and e["height"] > 0 and se["width"] > 0:
                err = abs((e["width"] / e["height"]) / (se["width"] / se["height"]) - 1)
                if err > 0.05:
                    asp.append((i, round(err, 3)))
    r["aspect_violations"] = asp
    # degenerate / shrink
    tgt_scale = math.sqrt((cw * ch) / (sc["width"] * sc["height"]))
    shrink = []
    mindim = []
    for i, e in out_by.items():
        se = src_by[i]
        if is_background(se, sc):
            continue
        sa = se["width"] * se["height"]
        oa = e["width"] * e["height"]
        rel = math.sqrt(oa / sa) / tgt_scale if sa > 0 else 1
        shrink.append((round(rel, 3), i))
        if min(e["width"], e["height"]) < 6 and se["type"] != "shape":
            mindim.append(i)
    shrink.sort()
    r["min_rel_scale"] = shrink[:3]
    r["tiny_elements"] = mindim
    # text
    tl = {}
    over = []
    text_off = []
    for i, e in out_by.items():
        if e["type"] != "text":
            continue
        L = text_layout(e)
        tl[i] = L
        if L["overflow_x"] > 1 or L["overflow_y"] > 1:
            over.append((i, round(L["overflow_x"]), round(L["overflow_y"])))
        ib = ink_box(e)
        if ib[0] < -1 or ib[1] < -1 or ib[2] > cw + 1 or ib[3] > ch + 1:
            text_off.append(i)
    r["text_overflow"] = over
    r["text_ink_off_canvas"] = text_off
    sizes = [(tl[i]["int_size"], i) for i in tl]
    r["min_font_px"] = min(sizes) if sizes else None
    # overlaps (source-relative intent)
    unwanted = []
    ids = [i for i in out_by]
    sib = {i: ink_box(src_by[i]) for i in ids}
    oib = {i: ink_box(out_by[i]) for i in ids}
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            i, j = ids[a], ids[b]
            ei, ej = src_by[i], src_by[j]
            if is_background(ei, sc) or is_background(ej, sc):
                continue
            if ei.get("group_id") and ei.get("group_id") == ej.get("group_id"):
                continue
            if is_decor(ei) or is_decor(ej):
                continue
            ov = inter(oib[i], oib[j])
            sm = min(area(oib[i]), area(oib[j])) or 1
            if ov / sm <= 0.02:
                continue
            sov = inter(sib[i], sib[j])
            ssm = min(area(sib[i]), area(sib[j])) or 1
            if sov / ssm >= 0.25:  # intended layering/containment in source
                continue
            unwanted.append((i, j, round(ov / sm, 2)))
    r["unwanted_overlaps"] = unwanted
    return r


def contrast_estimates(out):
    """Render without text; compare each text colour to the median background
    luminance under its ink box. Visual ESTIMATE only."""
    ex, _ = conv.convert_chameleon_to_crello(out, FM, str(ASSETS))
    png = RENDERER.render(ex, max_size=4096, format="png", render_text=False)
    import io
    im = Image.open(io.BytesIO(png)).convert("RGB")
    sx = im.width / out["canvas"]["width"]
    res = []
    for e in out["elements"]:
        if e["type"] != "text":
            continue
        b = ink_box(e)
        box = [int(max(0, b[0] * sx)), int(max(0, b[1] * sx)), int(min(im.width, b[2] * sx)), int(min(im.height, b[3] * sx))]
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            continue
        px = list(im.crop(box).resize((32, 16)).get_flattened_data() if hasattr(Image.Image, "get_flattened_data") else im.crop(box).resize((32, 16)).getdata())

        def lum(c):
            v = [x / 255 for x in c[:3]]
            v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
            return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
        ls = [lum(p) for p in px]
        bgl = statistics.median(ls)
        r_, g_, b_, a_ = parse_rgba(e["color"], (0, 0, 0, 1))
        bgc = statistics.median([p[0] for p in px]), statistics.median([p[1] for p in px]), statistics.median([p[2] for p in px])
        tc = tuple(a_ * c + (1 - a_) * k for c, k in zip((r_, g_, b_), bgc))
        tl_ = lum(tc)
        cr = (max(tl_, bgl) + 0.05) / (min(tl_, bgl) + 0.05)
        busy = statistics.pstdev(ls)
        res.append((round(cr, 2), round(busy, 3), e["id"]))
    res.sort()
    return res


# ---------------------------------------------------------------- main
def main():
    resize = load_resize(args.resize)
    cases = sorted(Path(args.cases).glob("*.json"))
    if args.filter:
        cases = [c for c in cases if args.filter in c.name]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for c in cases:
        task = json.loads(c.read_text())
        src, tgt = task["source"], task["target_canvas"]
        rec = {"case": c.stem}
        t0 = time.time()
        try:
            out = resize(json.loads(json.dumps(src)), dict(tgt))
        except Exception as ex:
            rec["crash"] = repr(ex)
            rec["trace"] = traceback.format_exc()[-800:]
            summary.append(rec)
            print(f"CRASH {c.stem}: {ex!r}")
            continue
        rec["secs"] = round(time.time() - t0, 3)
        mutated = json.dumps(src, sort_keys=True) != json.dumps(task["source"], sort_keys=True)
        rec.update(check(task["source"], out))
        rec["input_mutated"] = mutated
        try:
            rec["contrast_low3"] = contrast_estimates(out)[:3]
        except Exception as ex:
            rec["contrast_low3"] = f"err {ex!r}"
        (out_dir / f"{c.stem}_output.json").write_text(json.dumps(out, indent=1))
        try:
            conv.render_design_to_png(out, ASSETS, out_dir / f"{c.stem}_output.png")
        except Exception as ex:
            rec["render_error"] = repr(ex)
        summary.append(rec)
    # aggregate
    agg = {
        "cases": len(summary),
        "crashes": sum(1 for r in summary if "crash" in r),
        "render_errors": sum(1 for r in summary if "render_error" in r),
        "id_or_field_errors": sum(1 for r in summary if r.get("errors")),
        "immutable_changed": sum(1 for r in summary if r.get("changed_immutable")),
        "off_canvas_axis": sum(1 for r in summary if r.get("off_canvas")),
        "off_canvas_rotated": sum(1 for r in summary if r.get("off_canvas_rotated")),
        "aspect_viol": sum(1 for r in summary if r.get("aspect_violations")),
        "text_overflow_cases": sum(1 for r in summary if r.get("text_overflow")),
        "text_overflow_elems": sum(len(r.get("text_overflow", [])) for r in summary),
        "text_ink_off_canvas": sum(1 for r in summary if r.get("text_ink_off_canvas")),
        "unwanted_overlap_cases": sum(1 for r in summary if r.get("unwanted_overlaps")),
        "unwanted_overlap_pairs": sum(len(r.get("unwanted_overlaps", [])) for r in summary),
        "tiny_elem_cases": sum(1 for r in summary if r.get("tiny_elements")),
        "min_font_px_overall": min((r["min_font_px"][0] for r in summary if r.get("min_font_px")), default=None),
        "cases_min_font_lt9": sum(1 for r in summary if r.get("min_font_px") and r["min_font_px"][0] < 9),
        "low_contrast_lt3": sum(1 for r in summary if isinstance(r.get("contrast_low3"), list)
                                and r["contrast_low3"] and r["contrast_low3"][0][0] < 3),
        "input_mutated": sum(1 for r in summary if r.get("input_mutated")),
        "max_secs": max((r.get("secs", 0) for r in summary), default=0),
    }
    (out_dir / "summary.json").write_text(json.dumps({"aggregate": agg, "cases": summary}, indent=1, default=str))
    print(json.dumps(agg, indent=1))
    if args.sheet:
        make_sheet(cases, out_dir)


def make_sheet(cases, out_dir):
    tiles = []
    for c in cases:
        p = out_dir / f"{c.stem}_output.png"
        if not p.exists():
            continue
        im = Image.open(p).convert("RGB")
        s = min(300 / im.width, 300 / im.height)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))
        tiles.append((c.stem, im))
    cols = 6
    rows = (len(tiles) + cols - 1) // cols
    from PIL import ImageDraw
    sheet = Image.new("RGB", (cols * 310, rows * 325), "white")
    d = ImageDraw.Draw(sheet)
    for k, (name, im) in enumerate(tiles):
        x, y = (k % cols) * 310, (k // cols) * 325
        sheet.paste(im, (x + 5, y + 20))
        d.text((x + 5, y + 4), name[:48], fill="black")
    sheet.save(out_dir / "contact_sheet.png")


if __name__ == "__main__":
    main()
