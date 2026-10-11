"""
Pixel Forge core: the Pillow pixelation pipeline shared by the desktop
app (pixel_forge.py) and the Streamlit web app (app.py).

Pure Pillow, no UI code, no network access.
"""

import importlib.util
import io
import os
import sys
from collections import Counter, deque
from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageChops, ImageEnhance

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

GRID_OPTIONS = {"16 x 16": 16, "32 x 32": 32}
PREVIEW_SIZE = 512  # final upscaled output size, in pixels (square)

OUTLINE_MODES = ("off", "outside", "inside")
BACKGROUND_METHODS = ("plain", "ai")

# Optional AI background removal (rembg). The model file lives inside the
# app folder: rembg looks for <U2NET_HOME>/models/<name>/<name>.onnx.
AI_MODEL = "isnet-general-use"
APP_DIR = Path(__file__).resolve().parent
AI_MODEL_FILE = APP_DIR / "models" / AI_MODEL / f"{AI_MODEL}.onnx"

_WORK_SIZE = 512     # subject mode works on a copy at most this big (speed)
_DETECT_SIZE = 256   # background detection runs at this size (pure-Python flood fill)
_COVERAGE = 100      # 0-255: how much of a cell the subject must cover to count as solid


class PixelArt(NamedTuple):
    small: Image.Image          # grid x grid, 1 image pixel = 1 art pixel
    large: Image.Image          # PREVIEW_SIZE x PREVIEW_SIZE, for viewing/export
    subject_found: bool | None  # subject features requested: was a subject found? (None = not requested)
    region: tuple[int, int, int, int]  # square of the source image the art covers (may extend past its edges)


# --------------------------------------------------------------------------
# Image processing
# --------------------------------------------------------------------------

def center_crop_to_square(img: Image.Image) -> Image.Image:
    """Crop the largest centred square out of the image.

    Pixel art grids are square, so squashing a wide photo into 16x16 would
    distort it. Cropping first keeps the subject's proportions intact.
    """
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def pixelate(img: Image.Image, grid: int, colors: int, **options) -> tuple[Image.Image, Image.Image]:
    """Convert an image to pixel art.

    Returns (small, large):
      small - the true grid x grid pixel art (1 image pixel = 1 art pixel)
      large - the same art blown up to PREVIEW_SIZE for viewing/downloading

    Accepts the same keyword options as pixelate_detailed.
    """
    result = pixelate_detailed(img, grid, colors, **options)
    return result.small, result.large


def pixelate_detailed(
    img: Image.Image,
    grid: int,
    colors: int,
    outline: str = "off",
    detail: int = 0,
    line_color: tuple[int, int, int] | None = None,
    fit_subject: bool = False,
    transparent_bg: bool = False,
    scale: float = 1.0,
    offset: tuple[int, int] = (0, 0),
    background: str = "plain",
    enhance: bool = False,
    match_source: bool = False,
) -> PixelArt:
    """The full pipeline.

    With every option at its default this is the plain 3-step conversion
    (downscale -> quantize -> upscale). The options switch on "subject
    mode", which first separates the subject from a plain background:

    outline        - "off", "outside" (line drawn around the subject, on the
                     background) or "inside" (on the subject's own edge pixels)
    detail         - 0 (off) to 100: how readily inner lines are drawn
                     between contrasting regions of the subject
    line_color     - RGB outline colour; None picks a dark shade of the
                     subject's own colours automatically
    fit_subject    - crop to the subject so it fills the grid, instead of
                     a centred square of the whole image
    transparent_bg - remove the background instead of flattening it to a
                     single clean colour
    scale          - subject size in the grid: 1.0 = as framed above, 0.5 =
                     half size with more empty space, 1.5 = zoomed in
                     (edges of the subject may be cropped)
    offset         - (dx, dy) in art pixels: nudges the subject right/down
                     (negative = left/up)
    background     - how the subject is separated: "plain" (flood fill from
                     a plain-coloured border, no dependencies) or "ai"
                     (rembg; works on busy photos, needs install-ai.bat).
                     Choosing "ai" always switches subject mode on.
    enhance        - sprite clean-up for small grids: majority-colour
                     downscale, k-means palette, mild colour boost,
                     despeckle and pixel-perfect outline corners (see
                     _enhanced_downscale). Off = the classic pipeline.
    match_source   - slower pass (~0.1s at 16x16, ~1s at 32x32) that
                     re-colours the sprite to read as close to the source
                     as possible; same silhouette and colour count
                     (see _match_source)

    The colour limit covers everything: the line colour and a flat
    background colour each use up one palette slot (except at very low
    limits, where the subject always keeps at least one colour).
    """
    if outline not in OUTLINE_MODES:
        raise ValueError(f"outline must be one of {OUTLINE_MODES}")
    if background not in BACKGROUND_METHODS:
        raise ValueError(f"background must be one of {BACKGROUND_METHODS}")
    subject_mode = (outline != "off" or detail > 0 or fit_subject or transparent_bg
                    or background == "ai")
    subject = find_subject(img, background) if subject_mode else None
    img = img.convert("RGBA")

    # Which square of the source becomes the grid: the centred square, or
    # (fit) a tight square around the subject widened by one art pixel on
    # every side so an outline always has room. Then scale/offset adjust it.
    if subject is not None and fit_subject:
        x0, y0, x1, y1 = _subject_crop_box(subject.mask, fit=True)
        pad = (x1 - x0) / (grid - 2)
        base = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    else:
        base = _subject_crop_box(img.getchannel("A"), fit=False)
    region = _scale_region(base, grid, scale, offset)

    if subject is None:
        reserve = 1 if (outline != "off" or detail > 0) else 0
        cut = _to_work_size(img.crop(region), _WORK_SIZE) if (enhance or match_source) else None
        if enhance:
            budget = max(1, min(colors, grid * grid) - reserve)
            art = _enhanced_downscale(cut, grid, budget)
        else:
            art = _plain_pipeline(img, region, grid, colors, reserve=reserve)
        if match_source:
            art = _match_source(art, cut)
        if detail > 0 or outline != "off":
            art = add_lines(art, outline, detail, line_color)
    else:
        art = _subject_pipeline(img, subject, region, grid, colors, outline, detail, line_color,
                                transparent_bg, enhance, match_source)

    # ---- STEP 3: UPSCALE with NEAREST NEIGHBOR -----------------------------
    # Nearest neighbour copies each small pixel into a solid square block
    # with no blending at all (512 / 16 = a 32x32 block per art pixel).
    # Any smoothing filter (bilinear, bicubic, lanczos) would blur the
    # edges between blocks and destroy the crisp, blocky pixel look.
    large = art.resize((PREVIEW_SIZE, PREVIEW_SIZE), resample=Image.Resampling.NEAREST)

    return PixelArt(art, large, (subject is not None) if subject_mode else None, region)


def _scale_region(box, grid: int, scale: float, offset: tuple[int, int]) -> tuple[int, int, int, int]:
    """Resize a square source region around its centre (a *smaller* region
    makes the subject *bigger* in the grid), then shift it so the subject
    moves `offset` art pixels."""
    x0, y0, x1, y1 = box
    side = (x1 - x0) / max(scale, 0.01)
    cell = side / grid  # source pixels per art pixel
    cx = (x0 + x1) / 2 - offset[0] * cell
    cy = (y0 + y1) / 2 - offset[1] * cell
    return (round(cx - side / 2), round(cy - side / 2), round(cx + side / 2), round(cy + side / 2))


def _quantize_opaque(small: Image.Image, alpha: Image.Image, colors: int) -> Image.Image:
    """Quantize using a palette built from the visible pixels only, so
    transparent areas (removed background, or padding past the image
    edge) don't waste a palette slot. Returns RGBA with `alpha` applied."""
    spx, apx = small.load(), alpha.load()
    w, h = small.size
    opaque = [spx[x, y][:3] for y in range(h) for x in range(w) if apx[x, y]]
    if opaque:
        strip = Image.new("RGB", (len(opaque), 1))
        strip.putdata(opaque)
        palette = strip.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        art = small.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE).convert("RGBA")
    else:
        art = small.copy()
    art.putalpha(alpha)
    return art


# ---- Enhanced (sprite clean-up) downscale -----------------------------------
# A plain average of each cell turns every edge and texture into an
# in-between colour: at 16x16 that reads as mud and speckle. Hand-made
# sprites instead use a few flat colour regions. These steps get closer.

_ENH_COVERAGE = 80  # a little below _COVERAGE, so thin parts (handles, spikes) survive
_ENH_SHARE = 0.45   # a cell takes its majority colour when that colour covers >= 45% of it
_N8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1))


def _enhanced_downscale(cut: Image.Image, grid: int, colors: int) -> Image.Image:
    """Downscale + quantize tuned for small sprites. `cut` is RGBA with the
    background already transparent (or fully opaque in plain mode)."""
    cut = cut.convert("RGBA")
    alpha_src = cut.getchannel("A")

    # 1. A mild saturation/contrast boost: shrinking always washes colours
    #    out, and small sprites need punchier values to stay readable.
    rgb = ImageEnhance.Contrast(ImageEnhance.Color(cut.convert("RGB")).enhance(1.08)).enhance(1.04)
    cut = rgb.convert("RGBA")
    cut.putalpha(alpha_src)

    # 2. A middle-sized copy, S source samples per art pixel each way
    #    (premultiplied, so transparent pixels don't darken edges).
    s = max(2, min(8, _WORK_SIZE // grid))
    mid = cut.convert("RGBa").resize((grid * s, grid * s), Image.Resampling.BOX).convert("RGBA")
    mpx, mapx = mid.load(), mid.getchannel("A").load()
    size = grid * s
    opaque = [mpx[x, y][:3] for y in range(size) for x in range(size) if mapx[x, y] >= 128]
    art = Image.new("RGBA", (grid, grid), (0, 0, 0, 0))
    if not opaque:
        return art

    # 3. Palette: median cut refined by k-means, which settles on the
    #    colours regions actually use instead of splitting the difference.
    strip = Image.new("RGB", (len(opaque), 1))
    strip.putdata(opaque)
    palette = strip.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, kmeans=8,
                             dither=Image.Dither.NONE)
    entries = palette.getpalette()
    qpx = mid.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE).load()

    # 4. Each cell votes. If one palette colour clearly dominates, the cell
    #    takes it (crisp flat regions, no in-between mud). If the cell is
    #    genuinely mixed, fall back to the palette colour nearest its average.
    avg = cut.convert("RGBa").resize((grid, grid), Image.Resampling.BILINEAR).convert("RGBA")
    avg_idx = avg.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE).load()
    cover = avg.getchannel("A").load()
    apx = art.load()
    for cy in range(grid):
        for cx in range(grid):
            if cover[cx, cy] < _ENH_COVERAGE:
                continue
            votes = Counter(qpx[x, y] for y in range(cy * s, cy * s + s)
                            for x in range(cx * s, cx * s + s) if mapx[x, y] >= 128)
            if not votes:
                continue
            idx, n = votes.most_common(1)[0]
            if n / sum(votes.values()) < _ENH_SHARE:
                idx = avg_idx[cx, cy]
            apx[cx, cy] = (*entries[3 * idx: 3 * idx + 3], 255)

    # 5. Despeckle what's left.
    return _despeckle(art)


def _despeckle(art: Image.Image, max_contrast: int = 60) -> Image.Image:
    """A pixel with no same-colour neighbour (8-way) that is surrounded by
    solid pixels and only mildly different from them is noise: it takes
    its most common neighbour's colour. High-contrast singles (eyes,
    highlights, gems) are kept - those are deliberate detail."""
    w, h = art.size
    px = art.load()
    out = art.copy()
    o = out.load()
    for y in range(h):
        for x in range(w):
            p = px[x, y]
            if not p[3]:
                continue
            around = [px[x + dx, y + dy] for dx, dy in _N8 if 0 <= x + dx < w and 0 <= y + dy < h]
            solid = [n for n in around if n[3]]
            if p in around or len(solid) < 5:
                continue
            best = Counter(solid).most_common(1)[0][0]
            if abs(_luma(best) - _luma(p)) <= max_contrast:
                o[x, y] = best
    return out


def _pixel_perfect(art: Image.Image, line: tuple[int, int, int], was_background: Image.Image) -> Image.Image:
    """Thin the outline to single-pixel stair steps.

    A 4-connected outline doubles up on diagonals: at each step there's an
    extra corner pixel making an 'L'. Pixel artists remove those so lines
    step cleanly. A corner pixel is only removed if doing so doesn't open a
    gap onto the subject.

    `was_background` is the alpha channel from *before* lines were drawn:
    only pixels that were background there may be removed. Detail lines can
    paint the subject's own edge pixels in the line colour, and deleting
    those would punch holes in the silhouette.
    """
    w, h = art.size
    out = art.copy()
    o = out.load()
    target = (*line[:3], 255)
    before = was_background.load()

    def is_line(x, y):
        return 0 <= x < w and 0 <= y < h and o[x, y] == target

    def is_fill(x, y):
        return 0 <= x < w and 0 <= y < h and o[x, y][3] and o[x, y] != target

    changed = True
    while changed:
        changed = False
        for y in range(h):
            for x in range(w):
                if not is_line(x, y) or before[x, y]:
                    continue
                for hx, vy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                    if (is_line(x + hx, y) and is_line(x, y + vy) and not is_line(x + hx, y + vy)
                            and not is_fill(x - hx, y) and not is_fill(x, y - vy)):
                        o[x, y] = (0, 0, 0, 0)
                        changed = True
                        break
    return out


# ---- Match source (the "Match Original" button) -----------------------------
# The live pipeline favours clean flat regions. This slower pass instead
# optimises the sprite's colours to read as close to the source as possible,
# keeping its silhouette and colour count. It minimises, in Lab colour space
# (where distances match how different colours look to the eye):
#   fidelity - the sprite blurred slightly vs the source blurred the same way:
#              does it read like the source at a normal viewing distance?
#              A dark and a light pixel can together stand for a mid-tone
#              texture, which is how artists suggest detail at 16x16.
#   local    - each pixel vs the average colour of its own source area
#   contrast - differences between neighbouring pixels vs the same
#              differences in the source, so highlights and shadow streaks
#              survive instead of being averaged away
#   flatness - a small penalty per neighbour of a different colour, so
#              regions stay clean rather than turning into noise
# Solved with ICM (repeatedly giving each pixel its best colour), then each
# palette colour is refit to the source areas using it, and it repeats.

_BLUR3 = ((-1, -1, 1), (0, -1, 2), (1, -1, 1), (-1, 0, 2), (0, 0, 4), (1, 0, 2),
          (-1, 1, 1), (0, 1, 2), (1, 1, 1))
_MATCH_WEIGHTS = {"fidelity": 1.0, "local": 0.5, "contrast": 0.5, "flatness": 15.0}


def _to_lab(rgb) -> tuple[float, float, float]:
    """sRGB (0-255) -> CIE Lab (D65)."""
    def linear(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(float(v)) for v in rgb[:3])
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _lab_d2(a, b) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _match_source(art: Image.Image, cut: Image.Image, rounds: int = 2, passes: int = 6) -> Image.Image:
    """Re-colour the opaque pixels of `art` to match `cut` (the source
    region, background transparent) as closely as possible. Never adds
    colours or changes which pixels are opaque."""
    w_fid, w_loc, w_con, lam = (_MATCH_WEIGHTS[k] for k in ("fidelity", "local", "contrast", "flatness"))
    grid = art.width
    means = cut.convert("RGBa").resize((grid, grid), Image.Resampling.BOX).convert("RGBA").load()
    apx = art.load()
    cells = [(x, y) for y in range(grid) for x in range(grid) if apx[x, y][3]]
    if not cells:
        return art
    solid = set(cells)
    mean_lab = {c: _to_lab(means[c]) for c in cells}

    def blurred(x, y, colour_of):
        s0 = s1 = s2 = wsum = 0.0
        for dx, dy, wt in _BLUR3:
            n = (x + dx, y + dy)
            if n in solid:
                v = colour_of(n)
                s0 += wt * v[0]; s1 += wt * v[1]; s2 += wt * v[2]; wsum += wt
        return (s0 / wsum, s1 / wsum, s2 / wsum)

    target = {c: blurred(*c, mean_lab.__getitem__) for c in cells}
    nbrs4 = {(x, y): [n for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if n in solid]
             for x, y in cells}
    affected = {(x, y): [(x + dx, y + dy) for dx, dy, _ in _BLUR3 if (x + dx, y + dy) in solid]
                for x, y in cells}

    for _ in range(rounds):
        palette = sorted({apx[c][:3] for c in cells})
        pal_lab = [_to_lab(p) for p in palette]
        index = {p: i for i, p in enumerate(palette)}
        label = {c: index[apx[c][:3]] for c in cells}
        colour_of = lambda n: pal_lab[label[n]]  # noqa: E731 - reads the live labels

        for _ in range(passes):
            changed = False
            for c in cells:
                before = label[c]
                best, best_e = before, None
                mc = mean_lab[c]
                for i, pi in enumerate(pal_lab):
                    label[c] = i
                    e = w_loc * _lab_d2(pi, mc)
                    for a in affected[c]:
                        e += w_fid * _lab_d2(blurred(*a, colour_of), target[a])
                    for n in nbrs4[c]:
                        if label[n] != i:
                            e += lam
                        pn, mn = pal_lab[label[n]], mean_lab[n]
                        e += w_con * _lab_d2((pi[0] - pn[0], pi[1] - pn[1], pi[2] - pn[2]),
                                             (mc[0] - mn[0], mc[1] - mn[1], mc[2] - mn[2]))
                    if best_e is None or e < best_e:
                        best, best_e = i, e
                label[c] = best
                changed |= best != before
            if not changed:  # converged: no pixel wants a different colour
                break

        # Refit: each palette colour becomes the average source colour of the
        # pixels now using it (a k-means step with the optimised assignment).
        refit = []
        for i, p in enumerate(palette):
            members = [means[c][:3] for c in cells if label[c] == i]
            refit.append(tuple(sum(m[j] for m in members) // len(members) for j in range(3)) if members else p)
        out = art.copy()
        o = out.load()
        for c in cells:
            o[c] = (*refit[label[c]], 255)
        art, apx = out, out.load()
    return art


def _plain_pipeline(img: Image.Image, region, grid: int, colors: int, reserve: int = 0) -> Image.Image:
    """Crop to the region, downscale, quantize. `reserve` palette slots are
    kept free for colours added later (the line colour). By default the
    region is the centred square; past the image's edges (scaled down)
    Pillow's crop fills in transparent pixels."""
    img = img.crop(region)

    # ---- STEP 1: DOWNSCALE with BILINEAR ---------------------------------
    # Shrinking e.g. 1024x1024 -> 16x16 means each output pixel has to
    # represent a 64x64 block of the source. Bilinear resampling blends the
    # source pixels under each output pixel (Pillow widens the filter when
    # downscaling, so the whole block contributes). The result is a smooth
    # average colour per cell, which keeps the general shapes and colour
    # regions of the original. NEAREST here would instead pick one arbitrary
    # source pixel per cell and give noisy, speckled results.
    small = img.resize((grid, grid), resample=Image.Resampling.BILINEAR)

    # Split off the alpha channel; colour quantisation works on RGB only.
    rgb = small.convert("RGB")
    alpha = small.getchannel("A")

    # ---- STEP 2: QUANTIZE to an ADAPTIVE palette ---------------------------
    # An adaptive palette is built from the image itself: median-cut
    # repeatedly splits the image's colour space into boxes until there are
    # `colors` boxes, then uses each box's average as a palette entry. So a
    # mostly-blue image gets mostly-blue palette entries. Every pixel is
    # then snapped to its closest palette colour.
    # dither=NONE matters: dithering scatters checkerboard noise to fake
    # in-between shades, which looks wrong at 16x16. We want flat blocks.
    colors = max(1, min(colors, grid * grid) - reserve)  # can't have more colours than pixels
    # The alpha is thresholded to fully on/off because real pixel art has
    # hard edges, not half-transparent ones.
    hard_alpha = alpha.point(lambda a: 255 if a >= 128 else 0)
    if hard_alpha.getextrema()[0] == 0:
        # Some pixels are transparent: build the palette from the rest.
        return _quantize_opaque(small, hard_alpha, colors)
    quantized = rgb.quantize(
        colors=colors,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )

    # Back to RGBA and re-attach alpha.
    art = quantized.convert("RGBA")
    art.putalpha(hard_alpha)
    return art


# --------------------------------------------------------------------------
# Subject mode
# --------------------------------------------------------------------------

class Subject(NamedTuple):
    mask: Image.Image                          # "L", same size as the image: 255 = subject
    bg_color: tuple[int, int, int] | None      # None when the image was already transparent


# Detection results for the most recent image object, per method, so
# dragging a slider doesn't re-detect the background (AI takes seconds).
# Holding a reference to the image means `is` can't match a different image
# that happens to reuse a freed object's id.
_subject_cache: dict = {"image": None, "results": {}}


def find_subject(img: Image.Image, background: str = "plain") -> Subject | None:
    """detect_subject ("plain") or ai_subject ("ai"), cached per image."""
    if _subject_cache["image"] is not img:
        _subject_cache["image"], _subject_cache["results"] = img, {}
    results = _subject_cache["results"]
    if background not in results:
        results[background] = ai_subject(img) if background == "ai" else detect_subject(img)
    return results[background]


def subject_is_cached(img: Image.Image, background: str) -> bool:
    """True when find_subject(img, background) will return instantly - the
    desktop app runs slow (AI) detection on a worker thread otherwise."""
    return _subject_cache["image"] is img and background in _subject_cache["results"]


# ---- AI background removal (optional) --------------------------------------

_ai_session = None


def ai_model_loaded() -> bool:
    """The AI model is loaded already (the first AI run also loads it: slower)."""
    return _ai_session is not None


def ai_status() -> str | None:
    """None when AI removal is ready to use, otherwise why it isn't."""
    if getattr(sys, "frozen", False) and importlib.util.find_spec("rembg") is None:
        return "AI background removal isn't part of this build of Pixel Forge. Plain removal works as usual."
    how = ("Run install-ai.bat once (needs internet)." if sys.platform == "win32" else
           "Install it once with: pip install -r requirements-ai.txt (needs internet).")
    if importlib.util.find_spec("rembg") is None:
        return f"AI removal isn't installed. {how}"
    if not AI_MODEL_FILE.exists():
        return f"The AI model is missing. {how}"
    return None


def ai_subject(img: Image.Image) -> Subject | None:
    """Separate the subject with a neural network (rembg + ISNet), for
    photos where there is no plain background to flood-fill.

    Runs fully offline: the model is a local file, and this refuses to run
    rather than let rembg download it.
    """
    problem = ai_status()
    if problem:
        raise RuntimeError(problem)
    global _ai_session
    if _ai_session is None:
        os.environ["U2NET_HOME"] = str(APP_DIR)  # where rembg looks for models
        from rembg import new_session  # heavy import: only when AI is used
        _ai_session = new_session(AI_MODEL)
    from rembg import remove

    img = img.convert("RGBA")
    # The network works at 1024px internally; feeding it more is just slower.
    work = _to_work_size(img, 1024)
    mask = remove(work.convert("RGB"), session=_ai_session, only_mask=True).convert("L")
    mask = mask.resize(img.size, Image.Resampling.BILINEAR)
    # Keep any transparency the image already had.
    mask = ImageChops.darker(mask, img.getchannel("A"))
    if mask.getextrema()[1] < 128:
        return None  # the network found nothing it considers a subject

    # One clean colour to flatten the background to (when not transparent):
    # the average of what the network called background.
    small = _to_work_size(img, 128).convert("RGB")
    small_mask = mask.resize(small.size, Image.Resampling.BILINEAR)
    spx, mpx = small.load(), small_mask.load()
    bg_px = [spx[x, y] for y in range(small.height) for x in range(small.width) if mpx[x, y] < 64]
    bg = tuple(sum(c[i] for c in bg_px) // len(bg_px) for i in range(3)) if bg_px else (0, 0, 0)
    return Subject(mask, bg)


def _to_work_size(img: Image.Image, limit: int) -> Image.Image:
    scale = limit / max(img.size)
    if scale >= 1:
        return img
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(size, Image.Resampling.BOX)  # BOX = plain area average, true colours


def detect_subject(img: Image.Image) -> Subject | None:
    """Separate the subject from a plain background.

    1. If the image already has transparency, that *is* the mask.
    2. Otherwise: find the dominant colour around the border (the
       background), then flood-fill inward from the border through every
       pixel close to that colour. Whatever the flood can't reach is the
       subject - so background-coloured areas *inside* the subject (e.g.
       the hole in a handle loop) are correctly kept as background only if
       they connect to the outside.

    Returns None when there's no believable plain background (busy photos,
    landscapes, close-ups that fill the frame).
    """
    img = img.convert("RGBA")
    alpha = img.getchannel("A")
    if alpha.getextrema()[0] < 128:
        return Subject(alpha.point(lambda a: 255 if a >= 128 else 0), None)

    det = _to_work_size(img, _DETECT_SIZE).convert("RGB")
    w, h = det.size
    px = det.load()
    border = [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(1, h - 1) for x in (0, w - 1)]

    # Dominant border colour: bucket colours coarsely (JPEG noise makes
    # exact matches rare), take the biggest bucket, average its pixels.
    buckets = Counter((r // 24, g // 24, b // 24) for r, g, b in (px[p] for p in border))
    top_bucket, count = buckets.most_common(1)[0]
    if count < len(border) * 0.4:
        return None  # border is busy/varied: no plain background
    members = [px[p] for p in border if tuple(c // 24 for c in px[p]) == top_bucket]
    bg = tuple(sum(c[i] for c in members) // len(members) for i in range(3))

    # Tolerance adapts to how noisy the background is: a clean digital
    # background gets a tight tolerance, so pale parts of the subject that
    # are *close* to the background colour (bone, highlights) survive.
    noise = sorted(max(abs(c[i] - bg[i]) for i in range(3)) for c in members)
    tol = max(8, min(40, 3 * noise[int(len(noise) * 0.9)]))

    # "How far is each pixel from the background?" = largest channel difference.
    diff = ImageChops.difference(det, Image.new("RGB", det.size, bg))
    r, g, b = diff.split()
    far = ImageChops.lighter(ImageChops.lighter(r, g), b).tobytes()

    is_bg = bytearray(w * h)
    queue = deque()
    for x, y in border:
        i = y * w + x
        if far[i] <= tol and not is_bg[i]:
            is_bg[i] = 1
            queue.append(i)
    while queue:  # breadth-first flood fill, 4-connected
        i = queue.popleft()
        x, y = i % w, i // w
        for j in (i - 1 if x > 0 else -1, i + 1 if x < w - 1 else -1,
                  i - w if y > 0 else -1, i + w if y < h - 1 else -1):
            if j >= 0 and not is_bg[j] and far[j] <= tol:
                is_bg[j] = 1
                queue.append(j)

    _drop_specks(is_bg, w, h)
    share = sum(is_bg) / (w * h)
    if not 0.05 <= share <= 0.95:
        return None

    small_mask = Image.frombytes("L", (w, h), bytes(0 if v else 255 for v in is_bg))
    # Scale the mask back up; BILINEAR gives soft edges, which later become
    # partial coverage when the subject is shrunk to the grid.
    return Subject(small_mask.resize(img.size, Image.Resampling.BILINEAR), bg)


def _drop_specks(is_bg: bytearray, w: int, h: int) -> None:
    """Turn small isolated 'subject' blobs into background, in place.

    JPEG artefacts, dust or a watermark in a corner would otherwise count
    as subject - and stretch the fit-to-subject box. Anything under 2% of
    the largest blob goes.
    """
    label = [0] * (w * h)
    sizes = [0]
    for start in range(w * h):
        if is_bg[start] or label[start]:
            continue
        sizes.append(0)
        n = len(sizes) - 1
        label[start] = n
        queue = deque([start])
        while queue:
            i = queue.popleft()
            sizes[n] += 1
            x, y = i % w, i // w
            for j in (i - 1 if x > 0 else -1, i + 1 if x < w - 1 else -1,
                      i - w if y > 0 else -1, i + w if y < h - 1 else -1):
                if j >= 0 and not is_bg[j] and not label[j]:
                    label[j] = n
                    queue.append(j)
    if len(sizes) <= 2:
        return  # zero or one blob: nothing to drop
    keep = max(sizes) * 0.02
    for i, n in enumerate(label):
        if n and sizes[n] < keep:
            is_bg[i] = 1


def _subject_crop_box(mask: Image.Image, fit: bool) -> tuple[int, int, int, int]:
    """The square region of the image that becomes the pixel art: a tight
    square around the subject (fit) or the centred square."""
    w, h = mask.size
    bbox = mask.point(lambda a: 255 if a >= 128 else 0).getbbox() if fit else None
    if not bbox:
        side = min(w, h)
        return ((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side)
    x0, y0, x1, y1 = bbox
    side = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return (round(cx - side / 2), round(cy - side / 2), round(cx + side / 2), round(cy + side / 2))


def _subject_pipeline(img, subject, region, grid, colors, outline, detail, line_color,
                      transparent_bg, enhance=False, match_source=False) -> Image.Image:
    # Cut the subject out: background pixels become fully transparent.
    cut = img.copy()
    cut.putalpha(ImageChops.darker(img.getchannel("A"), subject.mask))

    # The region may extend past the image (fit mode with a subject near an
    # edge, or scaled down); Pillow fills that area with transparent
    # pixels, which is exactly the "background" we want there.
    cut = cut.crop(region)
    cut = _to_work_size(cut, _WORK_SIZE)

    lines_on = outline != "off" or detail > 0
    flat_bg = subject.bg_color is not None and not transparent_bg
    budget = max(1, min(colors, grid * grid) - lines_on - flat_bg)

    if enhance:
        art = _enhanced_downscale(cut, grid, budget)
    else:
        # ---- STEP 1 (subject mode): premultiplied BILINEAR downscale -----
        # In "RGBa" mode each colour is multiplied by its alpha before
        # averaging, so transparent background pixels contribute nothing.
        # Each cell becomes the average of the *subject's* pixels only: no
        # pale halo from background colour bleeding into the edges.
        small = cut.convert("RGBa").resize((grid, grid), Image.Resampling.BILINEAR).convert("RGBA")
        alpha = small.getchannel("A").point(lambda a: 255 if a >= _COVERAGE else 0)
        # ---- STEP 2 (subject mode): quantize the subject's colours only --
        art = _quantize_opaque(small, alpha, budget)
    if match_source:
        art = _match_source(art, cut)

    # ---- STEP 2b: LINES ---------------------------------------------------
    if lines_on:
        line = tuple(line_color or auto_line_color(art))[:3]
        subject_alpha = art.getchannel("A")
        art = add_lines(art, outline, detail, line)
        if enhance and outline != "off":
            art = _pixel_perfect(art, line, subject_alpha)

    # Background: leave transparent, or flatten to one clean colour.
    if flat_bg:
        base = Image.new("RGBA", art.size, (*subject.bg_color, 255))
        base.alpha_composite(art)
        art = base
    return art


# --------------------------------------------------------------------------
# Lines: silhouette outline + inner detail lines
# --------------------------------------------------------------------------
# All of this runs on the tiny grid x grid image (at most 32x32 = 1024
# pixels), so plain Python loops are fast enough and keep it readable.

def _luma(rgb) -> float:
    """Perceived brightness (ITU-R BT.601 weights)."""
    r, g, b = rgb[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b


def _dist2(a, b) -> int:
    return sum((x - y) ** 2 for x, y in zip(a[:3], b[:3]))


def _neighbours4(x, y, w, h):
    """Up/down/left/right neighbours that are inside the image. Pixel-art
    lines use 4-connectivity; diagonals would give chunky 'stair' lines."""
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < w and 0 <= ny < h:
            yield nx, ny


def auto_line_color(art: Image.Image) -> tuple[int, int, int]:
    """A dark, hue-matched outline colour: the subject's darkest colour at
    40% brightness. Artists rarely outline in pure black - a deep shade of
    the sprite's own colour looks far more natural."""
    px = art.load()
    colors = {px[x, y][:3] for y in range(art.height) for x in range(art.width) if px[x, y][3]}
    if not colors:
        return (24, 16, 32)
    darkest = min(colors, key=_luma)
    return tuple(int(c * 0.4) for c in darkest)


def add_lines(art: Image.Image, outline: str, detail: int, line_color=None) -> Image.Image:
    """Draw an outline and/or inner detail lines onto small pixel art.

    The subject is every non-transparent pixel, so the outline needs a
    transparent background (subject mode provides one). On a fully opaque
    image only the detail lines can be drawn.
    """
    w, h = art.size
    px = art.load()
    out = art.copy()
    o = out.load()
    line = (*(line_color or auto_line_color(art))[:3], 255)

    def solid(x, y):
        return px[x, y][3] > 0

    # -- Inner detail lines ---------------------------------------------------
    # Wherever two neighbouring pixels differ a lot in brightness, the
    # darker of the two becomes a line pixel. Marking only the darker side
    # makes the lines hug shadows, like a hand-drawn "selective outline".
    if detail > 0:
        threshold = 80 - 0.7 * detail  # detail 1 -> only big jumps, 100 -> subtle ones
        marked = set()
        for y in range(h):
            for x in range(w):
                if not solid(x, y):
                    continue
                for nx, ny in ((x + 1, y), (x, y + 1)):
                    if nx < w and ny < h and solid(nx, ny):
                        a, b = _luma(px[x, y]), _luma(px[nx, ny])
                        if abs(a - b) >= threshold:
                            marked.add((x, y) if a < b else (nx, ny))

        # Colour each line pixel with a darker colour that is already in the
        # palette (so the colour limit holds), aiming for ~55% brightness.
        # If nothing darker exists, use the line colour itself.
        palette = {px[x, y][:3] for y in range(h) for x in range(w) if solid(x, y)}
        palette.add(line[:3])
        for x, y in marked:
            own = px[x, y]
            target = tuple(int(c * 0.55) for c in own[:3])
            darker = [c for c in palette if _luma(c) < _luma(own) - 8]
            best = min(darker, key=lambda c: _dist2(c, target)) if darker else line[:3]
            o[x, y] = (*best, 255)

    # -- Silhouette outline ---------------------------------------------------
    # Drawn last so it always wins over detail lines.
    if outline != "off":
        for y in range(h):
            for x in range(w):
                here = solid(x, y)
                if not any(solid(nx, ny) != here for nx, ny in _neighbours4(x, y, w, h)):
                    continue
                # "outside": transparent pixels hugging the subject become
                #            line, so the subject keeps every pixel.
                # "inside":  the subject's own edge pixels become line, so
                #            its silhouette doesn't grow.
                if (outline == "outside" and not here) or (outline == "inside" and here):
                    o[x, y] = line

    return out


def to_png_bytes(img: Image.Image) -> bytes:
    """Encode an image as PNG bytes for st.download_button."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
