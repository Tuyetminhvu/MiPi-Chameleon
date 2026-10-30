"""Generate a varied, schema-valid stress set for the arena.

Writes task JSONs ({task_id, source, target_canvas}) into ./cases/.
Run from the repo root:  python3 <this file> <repo_root> <out_dir>
"""
import copy
import json
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

# Catalogue-like real-world formats (name, w, h). Hidden targets are "real
# platform formats" per RULES.md; these are representative, not official.
TARGETS = {
    "ig_post": (1080, 1080),
    "ig_portrait": (1080, 1350),
    "ig_story": (1080, 1920),
    "yt_thumb": (1280, 720),
    "fb_link": (1200, 628),
    "li_banner": (1584, 396),
    "leaderboard": (728, 90),
    "skyscraper": (160, 600),
    "med_rect": (300, 250),
    "pinterest": (1000, 1500),
}

WHITE = "rgba(255,255,255,1)"
ORANGE = "rgba(232,106,58,1)"
PLUM = "rgba(43,27,46,1)"


def T(id, x, y, w, h, content, size, z=5, family="Solstice Sans", **kw):
    d = {"id": id, "type": "text", "x": x, "y": y, "width": w, "height": h,
         "z_index": z, "content": content, "font_family": family,
         "font_size": size, "color": kw.pop("color", WHITE),
         "text_align": kw.pop("text_align", "center")}
    d.update(kw)
    return d


def I(id, x, y, w, h, asset, z=3, fit="contain", **kw):
    d = {"id": id, "type": "image", "x": x, "y": y, "width": w, "height": h,
         "z_index": z, "asset_id": asset, "fit": fit}
    d.update(kw)
    return d


def S(id, x, y, w, h, z=2, shape="rectangle", fill=ORANGE, **kw):
    d = {"id": id, "type": "shape", "x": x, "y": y, "width": w, "height": h,
         "z_index": z, "shape_type": shape, "fill_color": fill}
    d.update(kw)
    return d


BG = lambda w, h: I("bg", 0, 0, w, h, "solstice_bg_gradient.png", z=0, fit="cover")

designs = {}

# --- the three official samples (source only) ---
for f in sorted((REPO / "input").glob("*.json")):
    t = json.loads(f.read_text())
    designs[t["task_id"]] = t["source"]

# --- many text boxes, long copy (portrait) ---
designs["many_text"] = {"canvas": {"width": 1080, "height": 1350}, "elements": [
    BG(1080, 1350),
    I("logo", 60, 50, 240, 80, "solstice_logo_lockup.png", z=4),
    T("title", 60, 170, 960, 200, "The Golden Hour Tasting Series: Six Evenings of Botanical Discovery",
      64, family="Solstice Serif", font_weight="bold", text_align="left"),
    T("p1", 60, 400, 960, 120, "Join our head blender for an intimate walk through the season's harvest, from wild honey to blood orange zest and smoked rosemary.", 26, text_align="left"),
    T("p2", 60, 540, 960, 120, "Each evening pairs three small-batch infusions with seasonal plates from local kitchens, served on the rooftop as the sun goes down.", 26, text_align="left"),
    T("p3", 60, 680, 960, 90, "Seats are limited to forty guests per night and are released every Monday at noon.", 26, text_align="left"),
    T("dates", 60, 800, 960, 160, "Fri 12 Jun  ·  Sat 13 Jun  ·  Fri 19 Jun  ·  Sat 20 Jun  ·  Fri 26 Jun  ·  Sat 27 Jun", 30,
      font_weight="bold", color="rgba(240,178,66,1)", text_align="left"),
    S("cta_bg", 60, 1010, 420, 90, z=3, fill=ORANGE, corner_radius=45, group_id="cta"),
    T("cta_label", 60, 1035, 420, 44, "Reserve a Seat", 24, font_weight="bold", group_id="cta"),
    T("footer", 60, 1280, 960, 40, "Must be 21+. Limited availability. Menu subject to change. solstice.com/tasting", 14,
      color="rgba(255,255,255,0.6)", text_align="left"),
]}

# --- multiple images with different proportions (landscape), incl. missing assets ---
designs["multi_image"] = {"canvas": {"width": 1920, "height": 1080}, "elements": [
    BG(1920, 1080),
    I("logo", 80, 60, 360, 120, "solstice_logo_lockup.png", z=4),
    I("bottle_a", 120, 260, 500, 500, "solstice_bottle.png", z=3),
    I("photo_wide", 700, 260, 640, 360, "lifestyle_photo_16x9.png", z=3),
    I("photo_tall", 1420, 200, 380, 676, "lifestyle_photo_9x16.png", z=3),
    T("cap_a", 120, 780, 500, 60, "Blood Orange", 32, font_weight="bold"),
    T("cap_wide", 700, 640, 640, 60, "Rooftop tastings every Friday", 32),
    T("cap_tall", 1420, 900, 380, 60, "New: Smoked Rosemary", 28),
    T("headline", 700, 760, 640, 200, "Three Flavors. One Summer.", 72, family="Solstice Serif", font_weight="bold"),
]}

# --- text on a decorative panel (containment, no group), overlay, deco line, letter spacing, style runs ---
designs["text_on_panel"] = {"canvas": {"width": 1080, "height": 1080}, "elements": [
    S("solid_bg", 0, 0, 1080, 1080, z=0, fill="rgba(250,240,225,1)"),
    I("product", 540, 120, 480, 480, "solstice_bottle.png", z=2),
    S("glow", 600, 180, 360, 360, z=1, shape="ellipse", fill="rgba(240,178,66,1)", opacity=0.35),
    S("panel", 60, 560, 720, 420, z=3, fill=PLUM, corner_radius=24),
    T("kicker", 100, 600, 640, 40, "LIMITED RELEASE", 20, z=4, font_weight="bold",
      color="rgba(240,178,66,1)", text_align="left", letter_spacing=6),
    T("headline", 100, 650, 640, 180, "Smoked Rosemary & Wild Honey", 56, z=4, family="Solstice Serif",
      font_weight="bold", text_align="left", style_runs=[{"start": 17, "end": 27, "color": "rgba(240,178,66,1)"}]),
    S("rule", 100, 850, 200, 4, z=4, shape="line", fill=ORANGE, stroke_color=ORANGE, stroke_width=4),
    T("body", 100, 870, 640, 80, "Available in stores from June. Find a stockist near you.", 22, z=4, text_align="left"),
    I("logo_dark", 820, 960, 210, 70, "solstice_logo_lockup.png", z=4),
]}

# --- rotated sticker group overlapping the product (intentional), rotated image ---
designs["rotated_sticker"] = {"canvas": {"width": 1080, "height": 1350}, "elements": [
    BG(1080, 1350),
    I("product", 290, 250, 500, 500, "solstice_bottle.png", z=3),
    S("sticker_bg", 640, 260, 220, 220, z=4, shape="ellipse", fill=ORANGE, rotation=15, group_id="sticker"),
    T("sticker_txt", 650, 330, 200, 80, "NEW 20% OFF", 30, z=5, font_weight="bold", rotation=15, group_id="sticker"),
    I("tilted_logo", 80, 80, 300, 100, "solstice_logo_lockup.png", z=4, rotation=-8),
    T("headline", 90, 820, 900, 160, "Taste the Last Light of Summer", 64, family="Solstice Serif", font_weight="bold"),
    S("cta_bg", 330, 1050, 420, 90, z=3, corner_radius=45, group_id="cta"),
    T("cta_label", 330, 1075, 420, 44, "Find a Store", 24, font_weight="bold", group_id="cta"),
]}

# --- minimal: solid shape background + single text, no images ---
designs["minimal"] = {"canvas": {"width": 1200, "height": 628}, "elements": [
    S("bg_rect", 0, 0, 1200, 628, z=0, fill=PLUM),
    T("msg", 100, 214, 1000, 200, "Golden hour, bottled.", 96, family="Solstice Serif", font_weight="bold"),
]}

# --- no background element at all (white canvas), dark text ---
designs["no_bg"] = {"canvas": {"width": 1080, "height": 1080}, "elements": [
    I("product", 80, 140, 440, 440, "solstice_bottle.png", z=2),
    T("headline", 560, 200, 460, 240, "Botanical. Sparkling. Yours.", 60, family="Solstice Serif",
      font_weight="bold", color="rgba(43,27,46,1)", text_align="left"),
    T("body", 560, 460, 460, 160, "Crafted in tiny batches with nothing artificial, ever. Twelve flavors and counting.", 26,
      color="rgba(60,60,60,1)", text_align="left"),
    S("cta_bg", 560, 680, 300, 72, z=3, corner_radius=36, group_id="cta"),
    T("cta_label", 560, 698, 300, 36, "Shop now", 24, font_weight="bold", group_id="cta"),
    T("legal", 80, 1000, 920, 40, "Alcohol-free. Contains natural flavors.", 16, color="rgba(90,90,90,1)"),
]}

# --- variable-count badges + long unbreakable word ---
designs["badges_longword"] = {"canvas": {"width": 1080, "height": 1080}, "elements": [
    BG(1080, 1080),
    T("headline", 90, 120, 900, 200, "Supercalifragilisticexpialidociously Refreshing", 72, family="Solstice Serif", font_weight="bold"),
] + sum([[S(f"b{i}_bg", 60 + (i % 3) * 330, 420 + (i // 3) * 80, 300, 56, z=3, corner_radius=28, group_id=f"b{i}",
              fill=ORANGE if i % 2 == 0 else PLUM),
          T(f"b{i}_lbl", 60 + (i % 3) * 330, 434 + (i // 3) * 80, 300, 28, lbl, 16, z=4, font_weight="bold", group_id=f"b{i}")]
         for i, lbl in enumerate(["VEGAN", "ZERO SUGAR", "SMALL BATCH", "AWARD WINNING 2026", "NEW", "ORGANIC"])], []) + [
    I("product", 340, 600, 400, 400, "solstice_bottle.png", z=3),
]}

# --- target assignment: every design gets a spread incl. extremes ---
plan = {
    "warmup_01": ["ig_portrait", "ig_story", "yt_thumb", "leaderboard", "skyscraper"],
    "core_01": ["li_banner", "ig_story", "med_rect", "leaderboard", "pinterest"],
    "advanced_01": ["leaderboard", "ig_post", "yt_thumb", "skyscraper", "med_rect"],
    "many_text": ["ig_post", "yt_thumb", "li_banner", "med_rect"],
    "multi_image": ["ig_story", "ig_post", "leaderboard", "skyscraper"],
    "text_on_panel": ["ig_story", "li_banner", "fb_link", "leaderboard"],
    "rotated_sticker": ["yt_thumb", "li_banner", "ig_post", "leaderboard"],
    "minimal": ["ig_story", "leaderboard", "skyscraper"],
    "no_bg": ["fb_link", "ig_story", "leaderboard"],
    "badges_longword": ["li_banner", "skyscraper", "med_rect", "ig_story"],
}

n = 0
for dname, tnames in plan.items():
    for tn in tnames:
        w, h = TARGETS[tn]
        task = {"task_id": f"{dname}__{tn}", "source": copy.deepcopy(designs[dname]),
                "target_canvas": {"width": w, "height": h}}
        (OUT / f"{dname}__{tn}.json").write_text(json.dumps(task, indent=1))
        n += 1
print(f"wrote {n} cases to {OUT}")
