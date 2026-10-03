"""
Layers for editing a sprite: blend modes, compositing, merging, painting
helpers and undo history. Pure Pillow + Python (sprites are at most 32x32,
so per-pixel loops are fast enough and keep the maths readable).

Compositing follows the W3C "Compositing and Blending" spec, the same model
image editors use: each layer's colour is first mixed with what's below it
by its blend mode, then laid over it by its alpha x opacity ("source-over").
A *clipped* layer is laid only onto the pixels below it ("source-atop"):
that's how a gradient overlay stays on the sprite and off the background.
A layer with a *fade* (a gradient blend) is shown fully at the fade's start
and see-through at its end, blending gradually into the layers below.
"""

from collections import deque
from dataclasses import dataclass, field, replace
from functools import lru_cache
from math import hypot

from PIL import Image, ImageChops

MAX_LAYERS = 8
BASE_NAME = "Base"


# --------------------------------------------------------------------------
# Blend modes: f(backdrop, source) per colour channel, both 0..1
# --------------------------------------------------------------------------

def _hard_light(b, s):
    return 2 * b * s if s <= 0.5 else 1 - 2 * (1 - b) * (1 - s)


def _soft_light(b, s):
    if s <= 0.5:
        return b - (1 - 2 * s) * b * (1 - b)
    d = ((16 * b - 12) * b + 4) * b if b <= 0.25 else b ** 0.5
    return b + (2 * s - 1) * (d - b)


BLEND_MODES = {
    "Normal": lambda b, s: s,
    "Multiply": lambda b, s: b * s,                          # darkens: shading
    "Screen": lambda b, s: b + s - b * s,                    # lightens: glows
    "Overlay": lambda b, s: _hard_light(s, b),               # contrast, keeps backdrop's lights/darks
    "Darken": min,
    "Lighten": max,
    "Add": lambda b, s: min(1.0, b + s),
    "Subtract": lambda b, s: max(0.0, b - s),
    "Difference": lambda b, s: abs(b - s),
    "Hard Light": _hard_light,
    "Soft Light": _soft_light,
}


def _grey(r, g, b):
    """The grey with a colour's brightness (W3C luminosity), each 0..1."""
    y = 0.3 * r + 0.59 * g + 0.11 * b
    return y, y, y


# Adjustments: layer modes that change what's *below* the layer, wherever the
# layer has pixels - its own colours don't matter, its alpha x opacity says
# how strongly. Like a clip, they never add anything over transparency.
ADJUSTMENTS = {"Grayscale": _grey}
LAYER_MODES = list(BLEND_MODES) + list(ADJUSTMENTS)  # everything a layer's Blend can be


@dataclass(frozen=True)
class Gradient:
    """A gradient overlay's settings. A gradient layer's pixels are drawn
    from these (render_gradient), so it can be re-aimed or re-coloured at
    any time. Positions are fractions of the sprite (0..1, and may lie
    outside it), so the gradient keeps its place when the grid changes."""
    start: tuple = (0.5, 0.0)
    end: tuple = (0.5, 1.0)
    colours: tuple = ((24, 16, 32, 255), (24, 16, 32, 0))  # RGBA at the start and at the end
    shape: str = "linear"   # "linear", or "radial" (start = centre, end = edge)
    steps: int = 4          # how many colours: a few = pixel-art bands
    dither: bool = False    # ordered (Bayer) dither between the bands


@dataclass(frozen=True, eq=False)  # (eq=False: compared and cached by identity - it holds an image)
class Projection:
    """A texture projected onto a layer: it fills whatever is drawn on the
    layer - the drawing gives the shape (alpha), and its own colours show
    through as `mode` and `strength` say. Size and offset are fractions of
    the sprite, so it keeps its place when the grid changes."""
    texture: Image.Image         # RGBA, as opened (never modified)
    name: str = ""               # its file name, for the UI
    scale: float = 1.0           # the texture's width across the sprite: 1 = once, 0.5 = tiled twice
    offset: tuple = (0.0, 0.0)   # moves the texture right / down
    mode: str = "Normal"         # how it mixes with the drawn colours (a BLEND_MODES name)
    strength: int = 100          # 0-100


GRADIENT_SHAPES = ("linear", "radial")
MIN_STEPS, MAX_STEPS = 2, 8
BAYER_4X4 = (0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5)  # ordered-dither thresholds


@dataclass
class Layer:
    name: str
    image: Image.Image               # RGBA, grid x grid
    visible: bool = True
    opacity: int = 100               # 0-100
    mode: str = "Normal"
    live: bool = False               # the generated Base, still following the settings
    generated: bool = False          # started life as the generated Base (can be regenerated)
    gradient: Gradient | None = None  # a gradient layer: `image` is rendered from this
    clip: bool = False               # shown only where the layers below have pixels
    fade: Gradient | None = None     # a gradient blend: its alpha ramp fades this layer out
    projection: Projection | None = None  # a texture filling what's drawn on this layer

    def copy(self) -> "Layer":
        return replace(self, image=self.image.copy())


# A gradient blend's fade: fully shown -> see-through (only the colours' alpha counts).
FADE = Gradient(colours=((255, 255, 255, 255), (255, 255, 255, 0)))


def blank(size: int) -> Image.Image:
    return Image.new("RGBA", (size, size), (0, 0, 0, 0))


# --------------------------------------------------------------------------
# Gradients
# --------------------------------------------------------------------------

def gradient_ramp(g: Gradient) -> list[tuple]:
    """The gradient's `steps` colours, start to end. Mixed premultiplied,
    so fading to transparent keeps the colour instead of greying it."""
    (r0, g0, b0, a0), (r1, g1, b1, a1) = g.colours
    ramp = []
    for i in range(g.steps):
        u = i / (g.steps - 1)
        a = a0 + (a1 - a0) * u
        if a <= 0:
            ramp.append((0, 0, 0, 0))
            continue
        rgb = tuple(round((c0 * a0 * (1 - u) + c1 * a1 * u) / a) for c0, c1 in ((r0, r1), (g0, g1), (b0, b1)))
        ramp.append(rgb + (round(a),))
    return ramp


def render_gradient(g: Gradient, size: int) -> Image.Image:
    """The gradient as a size x size RGBA image, sampled at pixel centres.
    Without dither it's `steps` equal bands; with dither, neighbouring
    bands mix in a 4x4 Bayer pattern (the classic pixel-art way)."""
    ramp = gradient_ramp(g)
    n = len(ramp)
    (sx, sy), (ex, ey) = g.start, g.end
    dx, dy = ex - sx, ey - sy
    length2 = dx * dx + dy * dy
    radial = g.shape == "radial"
    radius = length2 ** 0.5
    data = bytearray(4 * size * size)
    for y in range(size):
        fy = (y + 0.5) / size - sy
        for x in range(size):
            fx = (x + 0.5) / size - sx
            if not length2:
                t = 0.0
            elif radial:
                t = hypot(fx, fy) / radius
            else:
                t = (fx * dx + fy * dy) / length2  # position along start -> end
            t = 0.0 if t < 0 else 1.0 if t > 1 else t
            if g.dither:
                v = t * (n - 1)
                i = int(v)
                if i < n - 1 and v - i > (BAYER_4X4[(y % 4) * 4 + x % 4] + 0.5) / 16:
                    i += 1
            else:
                i = min(n - 1, int(t * n))
            j = 4 * (y * size + x)
            data[j:j + 4] = bytes(ramp[i])
    return Image.frombytes("RGBA", (size, size), bytes(data))


def with_alpha(img: Image.Image, alpha: Image.Image) -> Image.Image:
    """img with a new alpha channel; pixels that end up fully transparent
    are cleared to (0, 0, 0, 0), so no hidden colour is left in them."""
    out = img.copy()
    out.putalpha(alpha)
    return Image.composite(out, blank(img.width), alpha.point(lambda a: 255 if a else 0))


def clip_to(img: Image.Image, backdrop: Image.Image) -> Image.Image:
    """img, keeping only what lies on backdrop's pixels (alpha x alpha)."""
    return with_alpha(img, ImageChops.multiply(img.getchannel("A"), backdrop.getchannel("A")))


@lru_cache(maxsize=64)
def fade_mask(fade: Gradient, size: int) -> Image.Image:
    """A fade as an 'L' mask (255 = fully shown). Cached: it's the same for
    every redraw until the fade changes. Callers must not modify it."""
    return render_gradient(fade, size).getchannel("A")


def default_projection(texture: Image.Image, grid: int, name: str = "") -> Projection:
    """A texture's projection to start with: pixel for pixel if it's no
    wider than the sprite (so a 16 px texture on a 16 px sprite fits once,
    an 8 px one tiles twice), else shrunk to fit once."""
    texture = texture.convert("RGBA")
    return Projection(texture=texture, name=name, scale=min(1.0, texture.width / grid))


@lru_cache(maxsize=16)
def projection_tile(p: Projection, size: int) -> Image.Image:
    """The projection's texture, sized and tiled across a size x size sprite.
    Cached per projection + size. Callers must not modify it."""
    tex = p.texture
    tw = max(1, round(p.scale * size))
    th = max(1, round(tw * tex.height / tex.width))
    small = tex.resize((tw, th), Image.Resampling.NEAREST if tw >= tex.width else Image.Resampling.BOX)
    ox, oy = round(p.offset[0] * size) % tw, round(p.offset[1] * size) % th
    out = blank(size)
    for y in range(oy - th if oy else 0, size, th):
        for x in range(ox - tw if ox else 0, size, tw):
            out.paste(small, (x, y))
    return out


def projected(image: Image.Image, p: Projection) -> Image.Image:
    """The drawing with the texture projected onto it: same alpha (the
    drawing's shape), colours mixed with the texture's by p.mode and
    p.strength (where the texture is see-through, the drawing shows)."""
    tile = projection_tile(p, image.width).tobytes()
    data = bytearray(image.tobytes())
    blend, strength = BLEND_MODES[p.mode], p.strength / 100
    for j in range(0, len(data), 4):
        if not data[j + 3]:
            continue
        a = tile[j + 3] / 255 * strength
        if a <= 0:
            continue
        for c in range(j, j + 3):
            b, s = data[c] / 255, tile[c] / 255
            data[c] = round(255 * ((1 - a) * b + a * blend(b, s)))
    return Image.frombytes("RGBA", image.size, bytes(data))


def shown_pixels(layer: Layer) -> Image.Image:
    """The layer's pixels as they're shown: its projected texture, then its
    fade (gradient blend), if any. (With neither, this is layer.image
    itself - don't modify it.)"""
    image = layer.image
    if layer.projection is not None:
        image = projected(image, layer.projection)
    if layer.fade is not None:
        mask = fade_mask(layer.fade, image.width)
        image = with_alpha(image, ImageChops.multiply(image.getchannel("A"), mask))
    return image


faded = shown_pixels  # (its first name, from when a fade was all there was)


def bake(layer: Layer, backdrop: Image.Image) -> Layer:
    """The layer as ordinary pixels: a gradient stops being one, a
    projection and a fade are applied to its pixels, and so is a clip
    (against `backdrop`, the layers below it)."""
    image = shown_pixels(layer)
    image = clip_to(image, backdrop) if layer.clip else image.copy()
    return replace(layer, image=image, gradient=None, clip=False, fade=None, projection=None)


# --------------------------------------------------------------------------
# Compositing
# --------------------------------------------------------------------------

def composite(layers: list[Layer], size: int) -> Image.Image:
    """Flatten the visible layers (bottom first) into one RGBA image."""
    shown = [l for l in layers if l.visible and l.opacity > 0]
    if not shown:
        return blank(size)
    if len(shown) == 1 and shown[0].mode == "Normal" and shown[0].opacity == 100 and not shown[0].clip:
        return faded(shown[0]).copy()  # exact: a lone plain layer is the result

    n = size * size
    # Colour + alpha, 0..1, not premultiplied. The bottom layer lies on
    # nothing, so it's just its own pixels (unless clipped: then nothing).
    first = shown[0]
    empty = (0.0, 0.0, 0.0, 0.0)
    if first.clip or first.mode in ADJUSTMENTS:  # (nothing below it to clip to / adjust)
        out = [empty] * n
    else:
        d, opacity = faded(first).tobytes(), first.opacity / 100
        out = [(d[j] / 255, d[j + 1] / 255, d[j + 2] / 255, d[j + 3] / 255 * opacity) if d[j + 3] else empty
               for j in range(0, 4 * n, 4)]
    for layer in shown[1:]:
        adjust = ADJUSTMENTS.get(layer.mode)
        blend = None if adjust else BLEND_MODES[layer.mode]
        opacity = layer.opacity / 100
        clip = layer.clip or adjust is not None
        data = faded(layer).tobytes()  # RGBA bytes
        for i in range(n):
            a_s = data[4 * i + 3] / 255 * opacity
            if a_s <= 0:
                continue
            rb, gb, bb, a_b = out[i]
            if clip and a_b <= 0:
                continue  # clipped, and nothing below here
            cs = (data[4 * i] / 255, data[4 * i + 1] / 255, data[4 * i + 2] / 255)
            cb = (rb, gb, bb)
            # Mix the source with the backdrop by the blend mode, only as far
            # as there *is* a backdrop (over transparency a layer looks normal).
            if adjust:  # an adjustment: what's below, changed (the layer's colour doesn't count)
                mixed = adjust(*cb)
            else:
                mixed = [(1 - a_b) * cs[c] + a_b * blend(cb[c], cs[c]) for c in range(3)]
            if clip:
                # Source-atop: only onto the pixels below, which keep their alpha.
                out[i] = tuple(a_s * mixed[c] + (1 - a_s) * cb[c] for c in range(3)) + (a_b,)
                continue
            # Source-over.
            a_o = a_s + a_b * (1 - a_s)
            out[i] = tuple((a_s * mixed[c] + a_b * cb[c] * (1 - a_s)) / a_o for c in range(3)) + (a_o,)

    result = bytearray(4 * n)
    for i, (r, g, b, a) in enumerate(out):
        result[4 * i: 4 * i + 4] = bytes((round(r * 255), round(g * 255), round(b * 255), round(a * 255)))
    return Image.frombytes("RGBA", (size, size), bytes(result))


def merge_down(layers: list[Layer], index: int) -> list[Layer]:
    """Merge layers[index] into the layer below it. The result keeps the
    lower layer's name, mode and opacity (like GIMP); the upper layer's
    blend mode and opacity are baked into the pixels (even if it's
    hidden - merging is an explicit request). Gradients and clips are
    baked too: the result is always plain pixels. (Only half-transparent
    pixels under a clip can't always be reproduced exactly.)"""
    if index <= 0:
        raise ValueError("nothing below to merge into")
    lower, upper = layers[index - 1], layers[index]
    if lower.mode in ADJUSTMENTS:  # no one layer can be "change what's below, plus these pixels"
        raise ValueError(f"can't merge into a {lower.mode} layer")
    size = lower.image.width
    adjust = ADJUSTMENTS.get(upper.mode)
    atop = upper.clip or adjust is not None
    below = composite(layers[:index - 1], size) if (atop or lower.clip) else None
    if lower.gradient is not None or lower.clip or lower.fade is not None or lower.projection is not None:
        lower = bake(lower, below if below is not None else composite(layers[:index - 1], size))
    as_plain = replace(lower, visible=True, opacity=100, mode="Normal")
    # A clipped upper (or an adjustment) goes "atop" lower's pixels here - exact, alpha kept...
    merged_img = composite([as_plain, replace(upper, visible=True)], size)
    if atop:
        # ...and where lower is empty it showed on the layers under it: keep that part too.
        if adjust:  # what it made of those layers, laid over them at the layer's strength
            up, bd, strength = shown_pixels(upper).tobytes(), below.tobytes(), upper.opacity / 100
            data = bytearray(4 * size * size)
            for j in range(0, len(data), 4):
                if bd[j + 3] and up[j + 3]:
                    rgb = adjust(bd[j] / 255, bd[j + 1] / 255, bd[j + 2] / 255)
                    data[j:j + 4] = bytes([round(c * 255) for c in rgb] + [round(up[j + 3] * strength)])
            spill = Image.frombytes("RGBA", (size, size), bytes(data))
        else:
            spill = clip_to(composite([replace(upper, visible=True, clip=False, mode="Normal")], size), below)
        merged_img.paste(spill, (0, 0), lower.image.getchannel("A").point(lambda a: 255 if a == 0 else 0))
    merged = replace(lower, image=merged_img, live=False)
    return layers[: index - 1] + [merged] + layers[index + 1:]


def merge_visible(layers: list[Layer]) -> list[Layer]:
    """All visible layers become one plain layer where the lowest visible
    one was; hidden layers are kept as they are."""
    visible = [i for i, l in enumerate(layers) if l.visible]
    if len(visible) < 2:
        return layers
    size = layers[visible[0]].image.width
    merged = Layer("Merged", composite(layers, size))
    out = [l for i, l in enumerate(layers) if i not in visible]
    out.insert(visible[0], merged)  # everything below the lowest visible layer is hidden and kept
    return out


def resize_layers(layers: list[Layer], size: int) -> list[Layer]:
    """Grid size changed (16 <-> 32): scale painted layers with NEAREST so
    every pixel stays a hard-edged block; gradients are simply redrawn."""
    out = []
    for l in layers:
        if l.image.width == size:
            out.append(l)
        elif l.gradient is not None:
            out.append(replace(l, image=render_gradient(l.gradient, size)))
        else:
            out.append(replace(l, image=l.image.resize((size, size), Image.Resampling.NEAREST)))
    return out


# --------------------------------------------------------------------------
# Painting helpers
# --------------------------------------------------------------------------

def line_pixels(x0: int, y0: int, x1: int, y1: int):
    """Every pixel on the line between two points (Bresenham), so a fast
    mouse drag paints a continuous stroke with no gaps."""
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def flood_fill(img: Image.Image, x: int, y: int, colour: tuple) -> int:
    """Fill the 4-connected area of exactly matching pixels at (x, y) with
    `colour` (RGBA), in place. Returns how many pixels changed."""
    px = img.load()
    w, h = img.size
    target = px[x, y]
    if target == colour:
        return 0
    queue, seen = deque([(x, y)]), {(x, y)}
    changed = 0
    while queue:
        cx, cy = queue.popleft()
        px[cx, cy] = colour
        changed += 1
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen and px[nx, ny] == target:
                seen.add((nx, ny))
                queue.append((nx, ny))
    return changed


# --------------------------------------------------------------------------
# Undo / redo
# --------------------------------------------------------------------------

@dataclass
class History:
    """Snapshots of (layers, active index). Push *before* each change."""
    limit: int = 60
    undo_stack: list = field(default_factory=list)
    redo_stack: list = field(default_factory=list)

    def push(self, layers: list[Layer], active: int) -> None:
        self.undo_stack.append(([l.copy() for l in layers], active))
        del self.undo_stack[: -self.limit]
        self.redo_stack.clear()

    def undo(self, layers, active):
        if not self.undo_stack:
            return None
        self.redo_stack.append(([l.copy() for l in layers], active))
        return self.undo_stack.pop()

    def redo(self, layers, active):
        if not self.redo_stack:
            return None
        self.undo_stack.append(([l.copy() for l in layers], active))
        return self.redo_stack.pop()

    def clear(self) -> None:
        self.undo_stack.clear()
        self.redo_stack.clear()
