import sys, time
from PIL import Image
from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
import layers as L

S = 4


def solid(rgba):
    return Image.new("RGBA", (S, S), rgba)


def px(img):
    return img.getpixel((0, 0))


def comp(*specs):
    return px(L.composite([L.Layer(f"l{i}", solid(c), **kw) for i, (c, kw) in enumerate(specs)], S))


grey, red, white, black = (128, 128, 128, 255), (255, 0, 0, 255), (255, 255, 255, 255), (0, 0, 0, 255)
# Known results for opaque layers (backdrop grey 128 = 0.502)
cases = {
    "Normal": (255, 0, 0, 255),
    "Multiply": (128, 0, 0, 255),        # 0.502*1, 0.502*0
    "Screen": (255, 128, 128, 255),      # b + s - bs
    "Darken": (128, 0, 0, 255),
    "Lighten": (255, 128, 128, 255),
    "Add": (255, 128, 128, 255),
    "Subtract": (0, 128, 128, 255),
    "Difference": (127, 128, 128, 255),  # |0.502 - 1| = 0.498
}
for mode, want in cases.items():
    got = comp((grey, {}), (red, {"mode": mode}))
    assert got == want, (mode, got, want)
# Overlay / hard light / soft light against hand-computed formulas
b, s = 128 / 255, 1.0
ov = 1 - 2 * (1 - b) * (1 - s) if b > 0.5 else 2 * b * s          # overlay: hard_light(s=b)
assert comp((grey, {}), (red, {"mode": "Overlay"}))[0] == round(ov * 255)
assert comp((grey, {}), (red, {"mode": "Hard Light"}))[0] == 255   # s=1 > .5: screen(b, 1) = 1
assert comp((grey, {}), (red, {"mode": "Soft Light"}))[1] == round((b - b * (1 - b)) * 255)  # s=0 channel
print("blend modes match their formulas")

# Opacity: 50% white over black -> mid grey; over transparency a blend mode acts like Normal
assert comp((black, {}), (white, {"opacity": 50}))[:3] == (128, 128, 128)
assert comp(((0, 0, 0, 0), {}), (red, {"mode": "Multiply"})) == red
half = comp(((0, 0, 0, 0), {}), (red, {"opacity": 50}))
assert half == (255, 0, 0, 128), half
assert comp((grey, {"visible": False}), (red, {"mode": "Multiply"})) == red, "hidden layers ignored"
print("opacity, transparency and visibility OK")

# A lone normal layer is returned exactly (including RGB of transparent pixels)
img = Image.new("RGBA", (S, S)); img.putpixel((1, 1), (10, 20, 30, 0)); img.putpixel((0, 0), (1, 2, 3, 255))
assert L.composite([L.Layer("a", img)], S).tobytes() == img.tobytes()

# Merge down bakes the upper layer's mode/opacity; keeps the lower's properties
base = L.Layer("Base", solid(grey), live=True, generated=True)
top = L.Layer("Shade", solid(red), mode="Multiply", opacity=100)
merged = L.merge_down([base, top], 1)
assert len(merged) == 1 and px(merged[0].image) == (128, 0, 0, 255)
assert merged[0].name == "Base" and merged[0].live is False and merged[0].generated is True
before = L.composite([base, top], S)
assert L.composite(merged, S).tobytes() == before.tobytes(), "merge doesn't change the picture"
# Merge visible keeps hidden layers and the picture
hidden = L.Layer("Hidden", solid(white), visible=False)
stack = [base, hidden, top, L.Layer("Glow", solid((0, 0, 255, 255)), mode="Screen", opacity=40)]
mv = L.merge_visible(stack)
assert [l.name for l in mv] == ["Merged", "Hidden"] and not mv[1].visible
assert L.composite(mv, S).tobytes() == L.composite(stack, S).tobytes()
print("merge down / merge visible preserve the picture")

# Flood fill, line, resize, history
f = Image.new("RGBA", (5, 5), (0, 0, 0, 0))
for y in range(5): f.putpixel((2, y), black)  # wall
assert L.flood_fill(f, 0, 0, red) == 10 and f.getpixel((4, 4)) == (0, 0, 0, 0) and f.getpixel((1, 3)) == red
assert list(L.line_pixels(0, 0, 3, 1)) == [(0, 0), (1, 0), (2, 1), (3, 1)]
assert all(abs(a - c) <= 1 and abs(b2 - d) <= 1 for (a, b2), (c, d) in
           zip(L.line_pixels(0, 0, 9, 4), list(L.line_pixels(0, 0, 9, 4))[1:]))
big = L.resize_layers([L.Layer("x", Image.new("RGBA", (16, 16), red))], 32)[0]
assert big.image.size == (32, 32) and big.image.getcolors() == [(1024, red)]
h = L.History()
s0 = [L.Layer("a", solid(red))]
h.push(s0, 0); s1 = [L.Layer("a", solid(black))]
back, act = h.undo(s1, 0); assert px(back[0].image) == red
fwd, act = h.redo(back, 0); assert px(fwd[0].image) == black
print("fill, line, resize, undo/redo OK")

# Speed: 32x32, 8 layers with blend modes
stack = [L.Layer(f"l{i}", Image.effect_noise((32, 32), 60).convert("RGBA"), mode=m, opacity=70)
         for i, m in enumerate(list(L.BLEND_MODES)[:8])]
t = time.perf_counter(); L.composite(stack, 32); print(f"composite 32x32 x 8 layers: {(time.perf_counter() - t) * 1000:.0f} ms")
print("ALL OK")
