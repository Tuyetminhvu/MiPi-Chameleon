# Chameleon Stage 1 — Arena decision and implementation handoff

Decision date: 25 Oct 2026 · Repo inspected: github.com/jhaaj08/chameleon @ a44a060

**Winner: "Search-lite"** — a structure search over an XY-cut tree of the design, with exact renderer-matched text fitting and a binary search on scale, followed by a weighted score. No runtime model and no new dependencies.

Arena format: five roles were run as independent agents (Simple, Search, Hybrid builders, Adversarial reviewer, and a Judge, which was the orchestrator). Each builder wrote a working prototype outside the project and ran it through the same harness. The judge re-ran every prototype independently before using its numbers.

---

## 0. Evidence base

### Verified requirements (repo + PDF agree)

| Requirement | Source |
|---|---|
| Entry point is `resize(source, target_canvas) -> dict` in `engine/resize.py`. `main.py` is the orchestrator and should not need editing. | resize.py, main.py, README, PDF §7.1 |
| Same element ids, same count, nothing added or removed; required fields present. | resize.py docstring, RULES.md, schema |
| Mutable fields: x, y, width, height, and `font_size` for text. `content` and `font_family` are fixed for Stage 1. | RULES.md "Adaptive typography" |
| Non-background images keep their box aspect within about 5%, unless `fit: "cover"`. | resize.py docstring |
| Never regenerate, redraw or replace pixels. This is **disqualifying**. | RULES.md, PDF §7.2 |
| Nothing off-canvas. `main.py` checks the **axis-aligned** box with a ±0.5 px tolerance. | main.py `self_check` |
| Both the JSON (structural) and the PNG (rendered by the official renderer, scored by an AI evaluator) are judged. | RULES.md, PDF §7.2 |
| Offline: Docker `--network none`, everything installed at build time. | README, Dockerfile, PDF §4 |
| No hard time limit; quality comes first. | RULES.md, PDF §7.2 |
| Hidden targets are real platform formats from a fixed catalogue. | RULES.md, PDF §7.2 |
| No semantic labels at scoring time (ids such as "headline" cannot be relied on). | FAQ Q1 |

Team constraint added by you: no hiding elements, no opacity tricks, no shrinking things to meaningless sizes.

### Verified renderer behaviour (from code, confirmed against rendered pixels)

1. **Text is top-aligned in its box.** The block height is `(n-1)*fs*lh + (descent - ascent)`. There is no vertical centring and no clipping, so labels must be centred by positioning their boxes.
2. **Wrapping and font size.**
   - The renderer wraps greedily at spaces only, measuring at the **float** size, **without** `letter_spacing`.
   - It draws at **`int(font_size)`** and does add `letter_spacing`.
   - Therefore always emit integer font sizes and measure spaced text yourself.
   - A word wider than its box overflows; it is never broken.
3. **Opacity.** Element `opacity` is ignored for text (only the colour's alpha counts). For shapes, element opacity is multiplied by the fill alpha.
4. **Image fit.**
   - `contain` letterboxes the image inside its box.
   - `cover` centre-crops.
   - A **missing asset renders as a visible grey "missing asset" box** at the element's size.
5. **Text height must be greater than 0.** A text with `height: 0` makes the renderer crash (pydantic validation), so always emit text width and height ≥ 1.
6. **Placeholder assets have large transparent margins.** The bottle's opaque content is 341×551 inside 800×800; the logo's is 364×216 inside 900×300.
7. **Small text renders poorly.** At 7 px or smaller, text drawn at an integer size looks badly kerned, so prefer ≥ 8 px wherever space allows.

### Conflicts found

- **FAQ.md is stale.** It describes running a separate `transformer-convertor` app on :5050 and a "required viewer add-on" for Stage 1. README and the PDF say the renderer is already vendored and the add-on is finale-only. **Follow README/PDF.**
- **Wording mismatch.** The PDF refers to "Section 9.1" and "Section 5" for fixed materials; the actual sections are §7.1 and §4. This is wording only.
- **`style_runs` end index.** The schema says it is exclusive; the converter treats it as inclusive (off by one). Not our bug, but worth reporting.
- **Off-canvas source elements.** The Level 2 README says a corner-bleeding decorative circle is "expected", but the rule says nothing may be off-canvas. We clamp everything; see the open questions.

### Executed vs proposed

| Executed | Not executed |
|---|---|
| Baseline run | Docker build/run (no daemon in the arena workspace) |
| 3 prototypes × 2 rounds × 57 cases through the official render path | Official scorer (unknown) |
| Pixel check of the text measurer (±2 px) | Hidden cases |
| Judge re-runs of all six prototypes | Real brand assets |
| Ablation of the refinement stage | |
| Winner run through the real `main.py` in a throwaway repo copy (all 3 samples pass self-check) | |

---

## A. Comparison

These are judge re-runs on the shared harness, which is not the official scorer.
- **Main:** 41 cases (3 samples × 5 targets, plus 7 synthetic designs).
- **Adversarial:** 16 cases written by the reviewer.

### Round 1 (main set)

| | Simple | Search | Hybrid |
|---|---|---|---|
| Lines | 469 | 710 | 887 |
| Unwanted-overlap cases | 1 | 0 | 0 |
| Min font | 8 | 3 | 6 |
| Cases with min font < 9 px | 6 | 6 | 13 |
| Max seconds | 3.2 | 1.8 | 0.09 |

### Round 2 (revised; main / adversarial)

| | Simple r2 | **Search r2** | Hybrid r2 |
|---|---|---|---|
| Lines | 500 | 769 | 1069 |
| Crashes, ID/field errors, aspect violations, text overflow, off-canvas | 0 / 0 | **0 / 0** | 0 / 0 |
| Unwanted-overlap cases (pairs) | 0 / 2 (2) | **0 / 2 (15)** ¹ | 0 / 3 (15) |
| Min font px | 3 / **1** | **7 / 4** | 5 / 3 |
| Cases with min font < 9 px | 7 / 1 | **2 / 2** | 11 / 3 |
| Tiny-element cases | 0 / 2 | 0 / 1 ² | 0 / 0 |
| Max seconds | 8.0 / 9.5 | 1.8 / 3.3 | 0.16 / 0.46 |

¹ 14 of Search's 15 adversarial pairs are in `advanced_to_320x50`, which no engine can satisfy (see G). The other pair is `collage_overlap_to_fb` at 0.07; that overlap already existed in the source, so it is a harness false positive.
² The flagged element is the empty-string text, which is harmless.

### Qualitative comparison

| | Simple | Search | Hybrid |
|---|---|---|---|
| Rendered quality (visual judgement) | Large text; pills balloon on small canvases; off-centre until r2 | **Most balanced; best hierarchy; faithful on near-size changes** | Good; varied templates |
| Compliance | Equalises or crushes text when stressed | **Best** | Overlap only under pressure |
| Generalization | XY-cut + flex wrap | **Structure chosen by measured fit** | Template buckets; rearranged near-size cases |
| Complexity | Lowest | Medium | Highest; can't shrink below ~700 lines |
| Dependencies | stdlib + repo renderer | stdlib + repo renderer | stdlib + repo renderer |

### Observed failures by reviewer case

| Case | Simple | Search | Hybrid |
|---|---|---|---|
| 320×50 | text 1–4 px (r2) | text 4 px + 14 overlaps + oversized placeholder | 12 overlaps + 3 px |
| Hierarchy | lost under stress (r1) | — | — |
| `near_fb_to_yt` (logo flips side) | — | — | yes |
| Images torn from captions | — | — | yes |
| Billboard chips at 9 px | — | yes | — |
| Tiny source logo stays tiny | — | yes | — |

## B. Winner and why

**Search-lite wins**, based on Search r2 with the fixes listed in C.

1. **Best compliance under stress.** It is the only engine with 0 overlaps and a minimum font of 7 px on the full main set after round 2. Outside the impossible 320×50 case it emits no unwanted overlaps at all.
2. **Most generalizable mechanism.** It does not hard-code "row vs column vs template per aspect bucket". It enumerates layout structures and lets exact measurement decide. That is why the same code handled banners, skyscrapers and near-size changes. Its centre shift on `near_fb_to_yt` was 0.057, against Hybrid's 0.649.
3. **Best rendered result by visual review** of all three contact sheets for both rounds. It keeps a clear size hierarchy, keeps panels as cards, keeps the sticker on the product, and reflows long copy into two columns on 336×280.
4. **Size is acceptable.** It is longer than Simple, but Simple's cheaper scan regressed when hardened (1–4 px fonts, 9.5 s). Hybrid grew to 1,069 lines and its builder said it cannot honestly get below about 700.
5. **No model.** Nothing in the evidence needed one: geometry plus `group_id` recovered every structure in 57 cases. The model list, size limit and hardware are still unconfirmed anyway.

### Components kept from the losers

- **From Hybrid: missing-asset demotion with a hard cap.** If the file is absent from `brand_kit/assets`, cap its visible short side at `max(16, 0.12 × min(W, H))`. Search's own ×0.45 rule failed in its emergency path: a 104×46 placeholder dominated the 320×50 render.
- **From Simple: a "never equalise hierarchy" rule.** Any text 15% or more larger in the source keeps a floor at least one step higher.

### Components dropped

- Hybrid's templates.
- Simple's flex-wrap scan.
- Search's "detach sticker" second tree. It is rarely chosen; remove it unless a test needs it.

### Component kept after ablation

The **style refinement stage stays, reduced.** Disabling it changed 30 of 57 outputs with identical metrics, but text was visibly smaller and weaker in most of them (side-by-side renders were viewed). Keep `rho ∈ {1.0, 1.33}` and `gam ∈ {1.0, 0.8}`.

## C. Minimal architecture

```
engine/
  resize.py     # entry: resize(); orchestration, pressure ladder, fallback          (~120 lines)
  measure.py    # renderer-matched text layout + fit_text, asset sizes/alpha boxes    (~110)
  structure.py  # classify, clusters, containers, importance, XY-cut, structure enum (~220)
  solve.py      # Ctx, size/place, solve (bisection), score, emit, finish/clamp      (~230)
```

`main.py`, `renderer/` and the Dockerfile are unchanged. No new requirements: skia comes in via cr-renderer, and numpy is not needed.

### Verified schema fields used

- **Read:** `canvas.width`/`height`; element `id`, `type`, `x`, `y`, `width`, `height`, `rotation`, `opacity`, `z_index`, `group_id`.
- **Text:** `content`, `font_family`, `font_size`, `font_weight`, `font_style`, `color` (alpha), `text_align`, `line_height`, `letter_spacing`.
- **Image:** `asset_id`, `fit`.
- **Shape:** `shape_type`, `fill_color` (alpha), `corner_radius`.
- **Written:** only `x`, `y`, `width`, `height`, `font_size`. Every other key is copied verbatim, including unknown keys such as `_note`.

### Internal representation

```
Leaf   {kind: "text" | "rigid" | "container", els: [element...], box: src ink box,
        imp: float, has_text, fmin, ftop}
  text      = one ungrouped text element (reflowable: own font size + wrap width)
  rigid     = group / overlap cluster scaled uniformly (images, rotated items, stickers)
  container = filled unrotated shape holding >=90% of the ink of its texts (pill, button, panel);
              child layout reflows inside, padding measured from source, pill grows to fit label
Node   {o: "V" | "H" | "C", kids: [...], align: ["s"|"c"|"e" per kid], box}
Background = non-text covering >=90% of canvas -> stretched to (0,0,W,H)
Decor      = shape with effective opacity < 0.5 not containing text -> proportional, clamped
```

### Numbered algorithm

1. **Classify** each element as background, decor or content.
2. **Cluster** content with union-find. Elements join if they share a `group_id`, or if their ink boxes overlap by at least 50% of the smaller box. A contain-image's ink is its alpha bounding box mapped into the box when the asset exists; otherwise the element box. Each cluster becomes a container (if it qualifies), a text leaf, or a rigid leaf.
3. **Importance per leaf.** Importance only weights size loss; it never hides anything.
   - Text: `(fs/fmax)^0.7`, ×1.15 if bold, ×0.6 if colour alpha < 0.75.
   - Image: `0.25 + 0.75·sqrt(area/max_area)`, ×0.15 if the asset is missing.
   - Cluster: the maximum of its members.
4. **XY-cut** the leaf ink boxes recursively, cutting at the largest gap and tolerating overlaps under 30%. If there is no clean cut, force a split at the minimum overlap. Record each child's source alignment (start/centre/end).
5. **Candidate structures**, capped at 400:
   - Flip classes for inner nodes. Repeated sibling patterns flip together (a hard constraint); if there are more than 5 classes, use 4 preset flip sets.
   - Root orientation: V or H.
   - Track partitions of the root's children into k ≤ 4 rows or columns, contiguous so reading order is kept.
   - Edit cost = number of flips + 2(k−1) + [root orientation changed].
6. **Solve each structure** with `solve(st, rho=1, gam=1)`. For each floor level in `[floor0, 0.85·floor0, 0.7·floor0, ABS_FLOOR=6]`, binary-search the global scale `s` over `[0.02, 1.15]·snat` for 13 iterations. Here `snat = sqrt(W·H / (sw·sh))` and `floor0 = max(9, round(0.0105·sqrt(W·H)))`. Inside `size()`:
   - **Text:** wanted size = `round(s·rho·(fmax/fs)^(1−gam)·fs)`, capped at `max(s·rho, 1.25·snat)·fs` and floored by the level. `fit_text` takes the largest integer size ≤ wanted whose wrapped lines fit the available width, including letter spacing, and whose longest word fits. Box = the measured ink width × block height.
   - **Rigid:** uniform scale `sb`. The image floor is applied to the **visible** short side: `minimg = min(max(16, 0.18·min(W,H)), 1.5·snat·src_visible_short)`. A missing asset's visible short side is capped at `max(16, 0.12·min(W,H))`. A rigid leaf whose text would drop below the level floor is infeasible.
   - **Container:** size the child at width `avail − padding·k`; padding scales with the child's text scale.
   - **V stack:** width = max of children; height = sum + gaps.
   - **H stack:** fixed children take their width; flexible (text) children share the remainder in proportion to `need = chars × fs²`.

   A structure is feasible if its root fits `(W − 2m) × (H − 2m)`. Margin `m = clamp(0.045·min(W,H), 4, 64)`; gap `g = clamp(0.022·min + 0.008·max, 3, 36)`.
7. **Score** each feasible structure (lower is better):
   ```
   1.0·Σimp·max(0, ln(snat/eff_scale))/Σimp    # important things keep natural size
   + 2.0·Σ max(0, floor0 − fs)/floor0           # readability shortfall
   + 0.15·hierarchy_inversions/n_text           # bigger source font stays bigger
   + 0.5·(1 − fill)                             # canvas usage
   + 0.2·relation_flips                         # above/below vs left/right fidelity to source
   + 0.03·one_word_lines + 0.02·max(0, lines−6) # rag quality
   + 0.02·edit_cost + 0.4·pressure_level
   ```
8. **Refine** the best 5 structures by re-solving with `rho ∈ {1.0, 1.33}` × `gam ∈ {1.0, 0.8}`, adding `0.03·(|ln rho| + (1−gam))`. Keep the minimum.
9. **Place.** Lay out V/H stacks with source alignment. At the root, spread the free space into gaps (at most +2.5·g each) and centre the remainder.
10. **Emit.**
    - Text: box, integer `font_size`, width/height ≥ 1, height = measured block height.
    - Rigid: each member gets `x0 + (src.x − box.x)·sb`, and so on. Text inside a rigid leaf is re-fitted as an integer size.
    - Container shape: the solved box. The label box is centred vertically inside it by position (the renderer top-aligns text).
11. **Finish.**
    - Backgrounds become (0, 0, W, H).
    - Decor keeps its relative centre with scale `sqrt(min·max)` of the axis ratios, capped at 0.6·min(W,H).
    - **Clamp** each element's centre so that **both** the axis box and the rotated AABB are inside the canvas. Shrink about the centre only if needed, and re-fit text after any shrink.
    - Round to 0.01, then re-clamp.
12. **Pressure ladder** (B in D below), applied when step 6 finds no feasible structure at `ABS_FLOOR`. It never overflows, never goes off-canvas, never hides and never puts text on text.
    1. Collapse margins and gaps to 2 px and retry.
    2. Move image-only rigid leaves out of the flow into a backdrop row behind the text. Each keeps its image floor; missing assets get the smallest slot. Text-over-image is the one constraint sacrificed here.
    3. Only if text alone still cannot fit at 6 px: below-median-importance texts may go to 5 px, then 4 px. Above-median text stays at 6 px or more.
    4. Log `PRESSURE=<level>` to stderr.
13. **Fallback** (never reached in 57 cases): uniform letterbox of the source layout, text re-fitted at ≥ `ABS_FLOOR`, then step 11.

## D. Pseudocode

```python
# engine/resize.py
ABS_FLOOR = 6
def resize(source, target_canvas):
    src = copy.deepcopy(source)                    # never mutate input
    W, H = target_canvas["width"], target_canvas["height"]
    bgs, decor, leaves, fmax = analyse(src)        # structure.py
    if not leaves:
        return fallback(src, W, H, bgs, decor)
    out = {"canvas": {"width": W, "height": H}, "elements": copy.deepcopy(src["elements"])}
    by_id = {e["id"]: e for e in out["elements"]}

    for stage in ("normal", "compact", "backdrop", "emergency5", "emergency4"):
        C = Ctx(W, H, src["canvas"], fmax, compact=(stage != "normal"))
        flow = leaves if stage in ("normal", "compact") else text_or_container_leaves(leaves)
        floors = floors_for(stage, C, leaves)       # per-leaf floor map for emergency stages
        cands = []
        for st, cost in structures(xycut(flow)):
            r = solve(st, C, 1.0, 1.0, floors)
            if r:
                cands.append((score(st, *r, cost, C)[0], st, cost))
        if cands:
            break
    else:
        return fallback(src, W, H, bgs, decor)

    if stage not in ("normal", "compact"):
        place_backdrop([L for L in leaves if L not in flow], C, by_id)
        log_pressure(stage)
    best = min(refine(st, cost, C, floors)
               for _, st, cost in sorted(cands, key=lambda t: t[0])[:5])
    emit(best.st, best.S, best.pos, C, by_id)
    return finish(out, src, bgs, decor, W, H)

def refine(st, cost, C, floors):
    best = None
    for rho in (1.0, 1.33):
        for gam in (1.0, 0.8):
            r = solve(st, C, rho, gam, floors)
            if r:
                sc, pos = score(st, *r, cost, C)
                sc += 0.03 * (abs(math.log(rho)) + (1 - gam))
                best = min(best, Cand(sc, st, r.S, pos))   # by score
    return best

# engine/solve.py
def solve(st, C, rho, gam, floors):
    for lvl, floor in enumerate(floors.levels):
        lo, hi = 0.02 * C.snat, 1.15 * C.snat
        ok, S = feasible(st, (hi, rho, gam, floor), C)
        if ok:
            return (hi, rho, gam, floor), S, lvl
        ok, S = feasible(st, (lo, rho, gam, floor), C)
        if not ok:
            continue
        for _ in range(13):
            mid = math.sqrt(lo * hi)
            ok2, S2 = feasible(st, (mid, rho, gam, floor), C)
            lo, hi, S = (mid, hi, S2) if ok2 else (lo, mid, S)
        return (lo, rho, gam, floor), S, lvl
    return None

def feasible(st, P, C):
    S = {}
    w, h = size(st, C.aw, P, C, S)
    return (w <= C.aw + 0.5 and h <= C.ah + 0.5), S

# engine/measure.py  (mirrors converter + cr-renderer exactly)
def text_layout(el, fs, width):                    # fs is int
    widths = char_widths(FM, fam, weight, style, float(fs), content)   # renderer measures at float
    lines = wrap_text(content, widths, width).split("\n")
    font = skia.Font(typeface, int(fs))
    line_w = [sum(font.getWidths(font.textToGlyphs(l))) + ls * max(0, len(l) - 1) for l in lines]
    m = font.getMetrics()
    block_h = (len(lines) - 1) * fs * lh + (m.fDescent - m.fAscent)
    return lines, max(line_w), block_h

def fit_text(el, want, avail, floor):
    for fs in range(int(want), floor - 1, -1):
        if longest_word_width(el, fs) > avail:
            continue
        lines, w, h = text_layout(el, fs, avail)
        if w <= avail:
            return fs, w + 1, h, lines            # +1 px slack against float rounding
    return None                                    # infeasible at this floor

# engine/structure.py
def analyse(src):
    bgs = [e for e in els if e["type"] != "text" and covers(e, canvas) >= 0.9]
    decor = [e for e in els if e["type"] == "shape" and eff_alpha(e) < 0.5 and not holds_text(e)]
    clusters = union_find(content, lambda a, b: same_group(a, b) or ink_overlap(a, b) >= 0.5)
    leaves = [containerise(c) or make_leaf(c) for c in clusters]
    for L in leaves:
        L["imp"] = importance(L, fmax, amax)
    return bgs, decor, leaves, fmax
```

## E. Implementation sequence

Each step ends with observable acceptance criteria. Run the harness with:

```
python3 tools/arena_harness.py --repo . --resize engine/resize.py --cases tests/cases --out /tmp/run_main --sheet
python3 tools/arena_harness.py --repo . --resize engine/resize.py --cases tests/cases_adv --out /tmp/run_adv --sheet
```

| # | Step | Accept when |
|---|---|---|
| 0 | Copy the kit into the repo (`tools/`, `tests/`, `docs/arena/`). Run the harness on the **untouched** baseline. | Main aggregate shows `aspect_viol 38`, `off_canvas_axis 5`, `min_font_px_overall 1` (this reproduces the baseline). |
| 1 | **Usable compliant baseline, about 2 h.** Uniform letterbox of the source (`s = min(W/sw, H/sh)`, centred). Backgrounds stretched; decor proportional; text `font_size = max(1, int(fs·s))` with a re-fit so lines fit the box; text w/h ≥ 1; clamp both axis box and rotated box. **Commit; this is a safe fallback submission.** | Both sets: `crashes 0`, `id_or_field_errors 0`, `immutable_changed 0`, `off_canvas_axis 0`, `off_canvas_rotated 0`, `aspect_viol 0`, `text_overflow_elems 0`, `input_mutated 0`. `python -m engine.main` prints OK for all 3 samples. |
| 2 | `measure.py`: `text_layout`, `fit_text`, asset size / alpha box with caching. | A unit check renders 10+ texts alone (transparent canvas). The alpha bbox of the PNG lies within ±3 px of predicted ink in x, and within [pred_top, pred_bottom] in y. Integer font sizes only. |
| 3 | `structure.py`: classify, clusters, containers, importance, XY-cut. Add a `--debug-tree` print. | On the samples: `bg` is background; `deco_circle_*` are decor; the badge, CTA and ribbon groups become container or rigid; `rotated_sticker` keeps sticker + product as one rigid unit; `text_on_panel` has the panel as a container with kicker/headline/rule/body inside, and glow + product clustered. |
| 4 | `solve.py` with a **single** structure (source tree as-is) + `solve` + `emit` + `finish`. Keep step 1 as `fallback`. | Main set, portrait/square/story targets only (`--filter ig_`): 0 overlaps, 0 overflow, min font ≥ 9. |
| 5 | Structure enumeration + `score` + top-5 refinement. | **Main set:** `unwanted_overlap_cases 0`, `text_overflow_elems 0`, `min_font_px_overall ≥ 7`, `cases_min_font_lt9 ≤ 2`, `max_secs < 5`. **Visual:** compare your `contact_sheet.png` to `docs/arena/evidence/reference_main_sheet.png`; no layout should be clearly worse. |
| 6 | Pressure ladder (step 12) + missing-asset cap + visible-image floor + hierarchy-floor rule. | **Adversarial set:** 0 crashes / overflow / off-canvas / aspect. In `advanced_to_320x50`: **no overlap pair where both elements are text**; `holiday_watermark` short side ≤ 16 px; every above-median-importance text ≥ 6 px; nothing below 4 px. `missing_main_product_to_story`: product placeholder short side ≤ 0.12×1080 ≈ 130 px. `advanced_01__leaderboard` (main): the logo's **visible** height ≥ 16 px. |
| 7 | Docker: `docker build --platform linux/amd64 -t chameleon .` then run with `--network none` (README command). Write the README approach section. | The container processes `input/` with 3× OK and PNGs identical in layout to the local run. No network errors. |

## F. Validation checklist

Run this before every submission.

**Structure**
- [ ] Output ids = input ids exactly, no duplicates, same count.
- [ ] Every required field present for its type.
- [ ] Only x, y, width, height and font_size differ from the input; every other key is identical, unknown keys included. The harness reports this as `immutable_changed`.
- [ ] No NaN or inf; `font_size` is an integer ≥ 1; text width and height ≥ 1.
- [ ] The input dict is not mutated (`input_mutated 0`).

**Geometry (exact)**
- [ ] Axis box inside the canvas (±0.5) for every element, as `main.py` checks.
- [ ] Rotated AABB inside the canvas for rotated elements.
- [ ] Non-background, non-cover images keep box aspect within 5%; the target is exact uniform scaling.
- [ ] Text: renderer-replicated lines fit the box width (letter spacing included); block height ≤ box height; no word wider than the box; ink fully on canvas.
- [ ] No new overlaps: output ink-box intersection > 2% of the smaller, unless same group, background, decor, or ≥ 25% overlap in the source. Text-on-text is **never** allowed.

**Readability (exact sizes, visual estimates)**
- [ ] Min font ≥ 7 on all main cases; ≥ 6 for above-median-importance text everywhere.
- [ ] Hierarchy: no text that was ≥ 15% larger in the source renders smaller.
- [ ] Contrast estimate ≥ 3 on new placements. This is an estimate: we can't change colours, so it only flags text moved onto a different background.

**Rendered output (visual, by a human)**
- [ ] Open the main and adversarial `contact_sheet.png` files.
- [ ] Check the three official samples at full size in `output/`.
- [ ] Look for: logo visible; missing-asset box small; pills hug their labels; no lopsided centring; near-size targets look like the source.

**Runtime**
- [ ] `max_secs < 5` on both sets. There is no limit, but this is a safety margin against the unconfirmed reference hardware.

**Docker**
- [ ] Build plus `--network none` run succeeds.

## G. Known limitations and open rule questions

### Known limitations (with evidence)

1. **Over-constrained extremes cannot be solved honestly.** `advanced_01` (17 elements, 140-character headline, 190-character subhead) into 320×50 cannot be legible with nothing hidden, nothing overlapping and copy unchanged. The ladder makes the failure predictable: text-over-image, small low-importance text. It still looks bad, and every engine failed here in a different way.
2. **Text that sits on product art in the source stays on it** ("BOLD OVER THE BOTTLE"). Colours can't be changed and moving it breaks intent; the median-luminance contrast estimate does not flag it.
3. **Tiny source logos are only partly promoted** by the visible-image floor. There is no reliable way to tell a logo from an icon without labels.
4. **XY-cut is weakest on free-form or diagonal layouts.** It forces cuts, and the result is a reasonable list layout rather than a designed one (`diagonal_stagger_*`).
5. **Score weights were tuned on 57 cases.** Hidden cases may prefer different trade-offs. Warmup-style sparse designs under-fill tall canvases, because text growth is capped at 1.25·snat.
6. **The harness is not the scorer.**
   - Its overlap rule uses contain-fitted boxes, not alpha, so it gives one known false positive (collage).
   - Contrast is an estimate.
   - The AI evaluator's rubric and weights are unknown.
7. **The placeholder brand kit is a risk.** The real assets will be swapped in, so alpha-box ink depends on the files present at run time. If an asset is absent from *our* container, the engine treats it as missing and shrinks it.

### Ask the organisers

1. Under extreme pressure, may an element be scaled very small, or must every element stay legible? Is dropping or merging ever allowed in Stage 1? (The PDF lists graceful dropping as a finale idea.)
2. How are "unwanted collisions" measured: element boxes, or rendered ink? Source-relative?
3. At scoring time, will hidden-case assets be inside our container's `brand_kit/assets`? This affects missing-asset detection and alpha-trimmed layout.
4. Should source elements that intentionally bleed off the canvas (the Level 2 decorative circle) be clamped, or allowed to bleed?
5. Is the "nothing off-canvas" check axis-aligned only, or does it also cover the rotated extent? We satisfy both.
6. What is the final model list, size limit and reference hardware (RAM/CPU)? We use no model, so this is low risk.
7. Confirm that FAQ.md (separate converter app; Stage 1 viewer add-on) is superseded by README and the PDF.
8. Is the `style_runs` end index inclusive or exclusive? The renderer treats it as inclusive.

## H. Ready-to-paste coding prompt

```
You are implementing the Stage-1 layout engine for the Adobe "Chameleon" hackathon in this repository.
Read HANDOFF.md (sections C, D, E, F) before writing code. The approach is already decided; do not
substitute a different algorithm, add a model, or add dependencies.

GROUND RULES
- Edit only: engine/resize.py, and new modules engine/measure.py, engine/structure.py, engine/solve.py.
  Do NOT modify engine/main.py, renderer/, brand_kit/, Dockerfile, requirements.txt, or input/ samples.
- Entry point stays: resize(source: dict, target_canvas: dict) -> dict. Never mutate `source` (deepcopy).
- Output = {"canvas": target_canvas, "elements": [...]}: same ids/count/order; change ONLY x, y, width,
  height, and font_size (text). Copy every other key verbatim, including unknown keys like "_note".
- Never read element ids or "_note"/"_adversarial_note" for meaning. Use geometry, type, group_id,
  z_index, opacity/alpha, font size, and asset files only.
- Never regenerate/replace image pixels. Never change content, font_family, colors, opacity, z_index,
  rotation, fit, asset_id, group_id.
- Never hide elements: no zero/near-zero sizes, no opacity changes, no moving off-canvas.
- font_size must be an integer >= 1; text width/height >= 1 (renderer crashes on height 0).
- Import renderer helpers exactly like the harness does: `from renderer.converter import convert as conv`,
  `from renderer.converter.wrap import char_widths, wrap_text`; FontManager via
  `conv._get_renderer(str(BRAND / "fonts")).font_manager`, where
  BRAND = Path(__file__).resolve().parent.parent / "brand_kit". Cache typefaces and layouts per call.

RENDERER FACTS YOU MUST MATCH (verified)
- Text is top-aligned; block height = (n-1)*fs*line_height + (descent - ascent) at int(fs).
- Wrap = renderer's greedy wrap at spaces, measured at float size WITHOUT letter_spacing; drawn at
  int(fs) WITH letter_spacing. A word wider than the box overflows (never broken) -> shrink font instead.
- contain images letterbox; cover crops; missing asset renders a visible grey placeholder.

BUILD IN THIS ORDER (stop and run the acceptance check after each step; do not move on until it passes)
Step 1  Compliant baseline in engine/resize.py: uniform letterbox of the source layout (s=min(W/sw,H/sh),
        centred); backgrounds (non-text covering >=90% of source canvas) -> (0,0,W,H); low-opacity decor
        shapes keep relative centre; text font_size=max(1,int(fs*s)) then refit so lines fit;
        clamp_inside() so BOTH the axis box and rotated AABB are inside the canvas (shrink about centre
        only if needed, refit text after shrink); round to 0.01 and re-clamp. Keep this as fallback().
Step 2  engine/measure.py: text_layout(el, fs, width) and fit_text(el, want, avail, floor) exactly as in
        HANDOFF D; asset_size()/visible_box() using alpha bbox when the asset file exists; missing(el).
Step 3  engine/structure.py: analyse() -> backgrounds, decor, leaves (union-find on group_id or >=50%
        ink overlap; containerise filled unrotated shapes holding >=90% of their texts' ink; importance()
        per HANDOFF C step 3); xycut(); structures(tree, max_cands=400) with shared flips and k<=4 tracks.
Step 4  engine/solve.py: Ctx (margins/gaps/snat/floor0 per HANDOFF C step 6), size(), feasible(),
        solve() with floor levels [floor0, .85, .7, 6] and 13-step geometric bisection, place(),
        emit(), finish(). First wire it with only the source tree (no enumeration).
Step 5  Enumerate structures, score() per HANDOFF C step 7, refine top-5 with rho in {1.0,1.33},
        gam in {1.0,0.8}.
Step 6  Pressure ladder (HANDOFF C step 12): compact margins -> image-only rigid leaves to a backdrop
        row behind text (keep image floor; missing assets smallest) -> only below-median-importance text
        may drop to 5 then 4 px. Never text-on-text overlap, never overflow, never off-canvas. Add:
        missing-asset visible short side <= max(16, 0.12*min(W,H)); visible image floor
        min(max(16, 0.18*min(W,H)), 1.5*snat*src_visible_short); hierarchy rule (text >=15% larger in
        source keeps a floor at least one step higher). Print "PRESSURE=<stage>" to stderr when used.
Step 7  Verify in Docker: docker build --platform linux/amd64 -t chameleon . && docker run --rm
        --network none -v $(pwd)/input:/app/input -v $(pwd)/output:/app/output chameleon
        Then add an "Approach" section to README.md (5-10 lines) describing the algorithm.

TESTS (run after every step; paste the aggregate JSON into your reply)
  python3 tools/arena_harness.py --repo . --resize engine/resize.py --cases tests/cases --out /tmp/run_main --sheet
  python3 tools/arena_harness.py --repo . --resize engine/resize.py --cases tests/cases_adv --out /tmp/run_adv --sheet
  python -m engine.main
Acceptance targets (from HANDOFF E):
  After step 1 (both sets): crashes 0, id_or_field_errors 0, immutable_changed 0, off_canvas_axis 0,
    off_canvas_rotated 0, aspect_viol 0, text_overflow_elems 0, input_mutated 0.
  After step 5 (main set): additionally unwanted_overlap_cases 0, min_font_px_overall >= 7,
    cases_min_font_lt9 <= 2, max_secs < 5.
  After step 6 (adv set): in advanced_to_320x50 no overlap pair with two text elements, holiday_watermark
    short side <= 16px, above-median-importance text >= 6px, nothing < 4px; missing_main_product_to_story
    placeholder short side <= ~130px; on tests/cases/advanced_01__leaderboard the logo's visible height
    >= 16px.
A reference prototype that meets most of these is in docs/arena/resize_reference.py (single file,
769 lines). Read it for details, but write the clean 4-module version; do not copy its stage-2
detach-tree or rho/gam grid of 9 (use the reduced grid). Its known bugs you must NOT reproduce:
missing-asset demotion lost in the backdrop path; image floor applied to the element box instead of the
visible box; emergency floors applied to all text instead of below-median importance; fallback()
allows font_size 1.

Do not add UI, CLI flags (other than optional debug), config files, or speculative infrastructure.
When finished, report: files changed, line counts, both harness aggregates, and the 3 sample PNG paths.
```

---

**Kit contents** (copy into the repo root):

| Path | Contents |
|---|---|
| `tools/arena_harness.py` | The evaluation harness. |
| `tools/make_cases.py`, `tools/make_adv_cases.py` | Case generators. The adversarial generator also emits two extra variants, `edge_kitchen_sink_to_banner` and `rotations_to_leader`, which are not in the committed set. |
| `tests/cases/` (41), `tests/cases_adv/` (16) | Schema-valid tasks. |
| `docs/arena/resize_reference.py` | The winning prototype (Search r2). |
| `docs/arena/evidence/` | Baseline and reference contact sheets. |
