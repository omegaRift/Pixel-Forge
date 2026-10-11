"""Gradient layers in layers.py: rendering, clipping, merging, resizing, undo."""
import sys, time
from dataclasses import replace
from PIL import Image, ImageDraw
from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
import layers as L

red, blue, grey = (255, 0, 0, 255), (0, 0, 255, 255), (128, 128, 128, 255)
S = 16
colours = lambda im: {c for _, c in im.getcolors(1 << 16)}
pixels = lambda im: [im.getpixel((x, y)) for y in range(im.height) for x in range(im.width)]


def row(img, y=0):
    return [img.getpixel((x, y)) for x in range(img.width)]


# 1. Linear, 4 steps, no dither: 4 equal bands with exact colours
g = L.Gradient(start=(0.5 / S, 0.5), end=(15.5 / S, 0.5), colours=(red, blue), steps=4)
img = L.render_gradient(g, S)
ramp = L.gradient_ramp(g)
assert ramp == [red, (170, 0, 85, 255), (85, 0, 170, 255), blue], ramp
assert row(img) == [ramp[0]] * 4 + [ramp[1]] * 4 + [ramp[2]] * 4 + [ramp[3]] * 4, row(img)
assert all(row(img, y) == row(img) for y in range(S)), "horizontal gradient: every row the same"
print("linear 4 steps: bands", [x for x in range(1, S) if row(img)[x] != row(img)[x - 1]], "colours exact")

# 2. Fading to transparent keeps the colour (premultiplied mix), even if the end's RGB differs
for end in ((200, 100, 50, 0), (0, 0, 0, 0)):
    ramp = L.gradient_ramp(L.Gradient(colours=((200, 100, 50, 255), end), steps=4))
    assert ramp[:3] == [(200, 100, 50, 255), (200, 100, 50, 170), (200, 100, 50, 85)] and ramp[3][3] == 0, ramp
print("fade: alpha 255/170/85/0, colour kept")

# 3. Dither, 2 colours: first column all start, last all end, end share rises across
g2 = L.Gradient(start=(0.5 / S, 0.5), end=(15.5 / S, 0.5), colours=(red, blue), steps=2, dither=True)
d = L.render_gradient(g2, S)
share = [sum(d.getpixel((x, y)) == blue for y in range(S)) / S for x in range(S)]
assert share[0] == 0 and share[-1] == 1, share
groups = [sum(share[i:i + 4]) for i in range(0, S, 4)]
assert groups == sorted(groups) and len(set(groups)) == 4, groups
assert colours(d) == {red, blue}, "dither only uses the ramp colours"
assert not all(row(d, y) == row(d) for y in range(S)), "a pattern, not bands"
print("dither: end-colour share per column", [round(s, 2) for s in share])

# 4. Radial: centre = start colour, corners = end colour; degenerate = all start
r = L.render_gradient(L.Gradient(start=(0.5, 0.5), end=(1.0, 0.5), colours=(red, blue), shape="radial"), S)
assert r.getpixel((7, 7)) == red and r.getpixel((8, 8)) == red and r.getpixel((0, 0)) == blue
assert r.getpixel((7, 7)) == r.getpixel((8, 7)) == r.getpixel((7, 8)), "symmetric around the centre"
flat = L.render_gradient(L.Gradient(start=(0.3, 0.3), end=(0.3, 0.3), colours=(red, blue)), S)
assert colours(flat) == {red}
print("radial + zero-length OK")

# 5. Positions are fractions: the same gradient at 32 has 8-px bands
gf = L.Gradient(start=(0.0, 0.5), end=(1.0, 0.5), colours=(red, blue), steps=4)
b16, b32 = L.render_gradient(gf, 16), L.render_gradient(gf, 32)
edges = lambda im: [x for x in range(1, im.width) if im.getpixel((x, 0)) != im.getpixel((x - 1, 0))]
assert edges(b16) == [4, 8, 12] and edges(b32) == [8, 16, 24], (edges(b16), edges(b32))
print("grid-independent: band edges", edges(b16), "at 16,", edges(b32), "at 32")

# 6. Clipping: only on the sprite, alpha untouched (also for a half-transparent pixel)
sprite = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sprite).ellipse((3, 3, 12, 12), fill=grey)
sprite.putpixel((3, 8), (255, 0, 0, 128))
base = L.Layer("Base", sprite)
over = L.Layer("Gradient 1", L.render_gradient(g, S), gradient=g, clip=True)
out = L.composite([base, over], S)
assert out.getchannel("A").tobytes() == sprite.getchannel("A").tobytes(), "clip keeps the sprite's alpha exactly"
assert out.getpixel((0, 0)) == (0, 0, 0, 0) and out.getpixel((8, 8)) == img.getpixel((8, 8))
assert out.getpixel((3, 8)) == (255, 0, 0, 128), out.getpixel((3, 8))  # red gradient band onto half-alpha red
unclipped = L.composite([base, replace(over, clip=False)], S)
assert unclipped.getpixel((0, 0)) == red, "without the clip it covers the background too"
assert L.composite([over], S).getchannel("A").getextrema() == (0, 0), "clipped with nothing below: nothing"
mult = L.composite([base, replace(over, mode="Multiply")], S)
band = img.getpixel((8, 8))
assert mult.getpixel((8, 8)) == tuple(round(128 * c / 255) for c in band[:3]) + (255,), (band, mult.getpixel((8, 8)))
print("clip: alpha exact, background untouched, blend modes apply, bottom clip shows nothing")

# 7. Merging keeps the picture and gives plain pixels
same = lambda a, b: a.tobytes() == b.tobytes()
before = L.composite([base, over], S)
m = L.merge_down([base, over], 1)
assert len(m) == 1 and m[0].gradient is None and not m[0].clip and same(L.composite(m, S), before)
# A glass texture (alpha 90 everywhere) + a clipped gradient: merging must keep it see-through
glass = L.Layer("Texture", Image.new("RGBA", (S, S), (120, 200, 255, 90)))
mg = L.merge_down([glass, over], 1)
assert mg[0].image.getchannel("A").getextrema() == (90, 90) and same(mg[0].image, L.composite([glass, over], S))
# The rest uses a hard-edged sprite: half-transparent pixels under a clip can't always merge exactly
hard = sprite.copy(); hard.putpixel((3, 8), grey)
base = L.Layer("Base", hard)
paint = Image.new("RGBA", (S, S), (0, 0, 0, 0)); paint.putpixel((0, 0), blue); paint.putpixel((8, 8), (0, 255, 0, 255))
stack = [base, over, L.Layer("Paint", paint)]
m2 = L.merge_down(stack, 2)                       # paint into the gradient layer
assert m2[1].gradient is None and not m2[1].clip and same(L.composite(m2, S), L.composite(stack, S))
fade = L.Gradient(start=(0, 0), end=(1, 1), colours=((255, 255, 255, 255), (255, 255, 255, 0)), steps=4)
stack = [base, L.Layer("Paint", paint), L.Layer("Glow", L.render_gradient(fade, S), gradient=fade, clip=True)]
m3 = L.merge_down(stack, 2)                       # a clipped fade into a sparse paint layer
diff = max(max(abs(a - b) for a, b in zip(p, q)) for p, q in zip(pixels(L.composite(m3, S)), pixels(L.composite(stack, S))))
assert diff <= 1, diff
assert m3[1].image.getpixel((1, 1))[3] == 0, "the clip was baked: nothing on the background"
assert same(L.composite(L.merge_visible(stack), S), L.composite(stack, S))
print(f"merge down/visible keep the picture (max difference {diff}), results are plain layers")

# 8. Resize redraws gradients; copies/undo keep the settings; bake
big = L.resize_layers([over], 32)[0]
assert big.image.size == (32, 32) and same(big.image, L.render_gradient(g, 32)) and big.gradient == g and big.clip
h = L.History()
h.push([over], 0)
changed = replace(over, gradient=replace(g, steps=2))
back, _ = h.undo([changed], 0)
assert back[0].gradient == g and back[0].clip
baked = L.bake(over, sprite)
assert baked.gradient is None and not baked.clip and baked.image.getpixel((0, 0))[3] == 0
assert baked.image.getpixel((8, 8)) == over.image.getpixel((8, 8))
print("resize redraws, undo restores gradient settings, bake clips to the sprite")

# 9. Gradient blend (fade): the layer keeps its pixels; how much of it shows follows the fade
paint = Image.new("RGBA", (S, S), (200, 60, 40, 255))
fade = replace(L.FADE, start=(0.5, 0.5 / S), end=(0.5, 15.5 / S))  # top (shown) -> bottom (clear), 4 steps
glow = L.Layer("Glow", paint, fade=fade)
shown_img = L.faded(glow)
assert [shown_img.getpixel((0, y))[3] for y in range(S)] == [255] * 4 + [170] * 4 + [85] * 4 + [0] * 4
assert shown_img.getpixel((0, 0))[:3] == (200, 60, 40) and shown_img.getpixel((0, 15)) == (0, 0, 0, 0)
assert glow.image.getpixel((0, 15)) == (200, 60, 40, 255), "the layer's own pixels are untouched"
assert same(L.composite([glow], S), shown_img), "a lone faded layer"
backdrop = L.Layer("Base", Image.new("RGBA", (S, S), (20, 40, 200, 255)))
out = L.composite([backdrop, glow], S)
assert out.getpixel((0, 0)) == (200, 60, 40, 255) and out.getpixel((0, 15)) == (20, 40, 200, 255)
mid = out.getpixel((0, 5))  # 170/255 of the layer over the backdrop
want = tuple(round(p * 170 / 255 + b * 85 / 255) for p, b in zip((200, 60, 40), (20, 40, 200)))
assert all(abs(m - w) <= 1 for m, w in zip(mid, want)) and mid[3] == 255, (mid, want)
mult = L.composite([backdrop, replace(glow, mode="Multiply")], S)
assert mult.getpixel((0, 0)) == (round(20 * 200 / 255), round(40 * 60 / 255), round(200 * 40 / 255), 255)
assert mult.getpixel((0, 15)) == (20, 40, 200, 255), "blend mode applies, and fades out with the layer"
cutout = L.faded(replace(glow, fade=replace(fade, steps=2, dither=True)))
assert {a for _, (r, g, b, a) in cutout.getcolors()} == {0, 255}, "2 steps + dither: no half-transparent pixels"
half = Image.new("RGBA", (S, S), (10, 20, 30, 128))
assert L.faded(L.Layer("h", half, fade=fade)).getpixel((0, 5))[3] == 128 * 170 // 255, "fade x the layer's alpha"
print("gradient blend: pixels kept, alpha follows the fade (255/170/85/0), blend modes apply, 2-step dither is cutout-safe")

dot = Image.new("RGBA", (S, S), (0, 0, 0, 0)); dot.putpixel((3, 12), (0, 255, 0, 255))
for stack, i, label in (([backdrop, glow], 1, "faded layer merged down"),
                        ([backdrop, glow, L.Layer("Dot", dot)], 2, "merged into a faded layer")):
    merged = L.merge_down(stack, i)
    assert same(L.composite(merged, S), L.composite(stack, S)), label
    assert all(l.fade is None for l in merged[i - 1:i]), label
assert same(L.composite(L.merge_visible([backdrop, glow]), S), L.composite([backdrop, glow], S))
baked = L.bake(glow, L.blank(S))
assert baked.fade is None and same(baked.image, shown_img)
big = L.resize_layers([glow], 32)[0]
assert big.fade == fade and [L.faded(big).getpixel((0, y))[3] for y in (0, 7, 8, 31)] == [255, 255, 170, 0]
h = L.History(); h.push([glow], 0)
back, _ = h.undo([replace(glow, fade=None)], 0)
assert back[0].fade == fade
assert L.fade_mask(fade, S) is L.fade_mask(replace(fade), S), "masks are cached per fade + size"
print("gradient blend: merge down / visible keep the picture, bake applies it, resize + undo keep it")

# 10. Speed
for size in (16, 32, 64, 256):
    t = time.perf_counter(); gi = L.render_gradient(replace(g, dither=True), size); tr = time.perf_counter() - t
    base_s = L.Layer("b", Image.effect_noise((size, size), 60).convert("RGBA"))
    t = time.perf_counter(); L.composite([base_s, L.Layer("g", gi, gradient=g, clip=True)], size); tc = time.perf_counter() - t
    print(f"  {size}x{size}: render {tr * 1000:.1f} ms, composite with clip {tc * 1000:.1f} ms")
print("ALL OK")
