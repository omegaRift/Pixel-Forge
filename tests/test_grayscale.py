"""The Grayscale layer mode: model checks, then the real app (hidden window)."""
import os
from dataclasses import replace
from pathlib import Path
from PIL import Image, ImageDraw

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
os.environ["PIXEL_FORGE_HIDDEN"] = "1"
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
same = lambda a, b: a.tobytes() == b.tobytes()
lum = lambda c: round(0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2])
S = 16

# ---- model ------------------------------------------------------------------
pic = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(pic); d.rectangle((2, 2, 7, 13), fill=(220, 40, 40, 255)); d.rectangle((8, 2, 13, 13), fill=(40, 90, 230, 255))
pic.putpixel((2, 2), (220, 40, 40, 128))
base = L.Layer("Base", pic)
cover = L.Layer("Grey", Image.new("RGBA", (S, S), (255, 0, 255, 255)), mode="Grayscale")  # its colour doesn't count
out = L.composite([base, cover], S)
for p in ((4, 5), (10, 5)):
    c = pic.getpixel(p); g = lum(c)
    assert out.getpixel(p) == (g, g, g, 255), (p, out.getpixel(p), g)
assert out.getpixel((0, 0)) == (0, 0, 0, 0), "nothing added over transparency"
assert out.getpixel((2, 2))[3] == 128 and len(set(out.getpixel((2, 2))[:3])) == 1, "half-see-through: stays so, grey"
half = L.composite([base, replace(cover, opacity=50)], S).getpixel((4, 5))
assert abs(half[0] - round((220 + lum((220, 40, 40))) / 2)) <= 1 and half[0] != half[1], "50%: half grey"
part = Image.new("RGBA", (S, S), (0, 0, 0, 0)); ImageDraw.Draw(part).rectangle((0, 0, 7, 15), fill=(9, 9, 9, 255))
o2 = L.composite([base, replace(cover, image=part)], S)
assert len(set(o2.getpixel((4, 5))[:3])) == 1 and o2.getpixel((10, 5)) == pic.getpixel((10, 5)), "only under its pixels"
fade = replace(L.FADE, start=(0.5, 0), end=(0.5, 1))
o3 = L.composite([base, replace(cover, fade=fade)], S)
assert len(set(o3.getpixel((4, 2))[:3])) == 1 and o3.getpixel((4, 13)) == pic.getpixel((4, 13)), "gradient blend: fades out"
assert L.composite([cover], S).getbbox() is None, "at the bottom: nothing"
over = L.composite([base, cover, L.Layer("Dot", Image.new("RGBA", (S, S), (0, 0, 0, 0)))], S)
assert same(over, out)
print("model: grey = luminosity, alpha kept, nothing over transparency, opacity / only-its-pixels / fade work")
# merge down: onto the Base (exact), and through a sparse layer (the greyed layers under it are kept)
m = L.merge_down([base, cover], 1)
assert same(L.composite(m, S), out) and m[0].mode == "Normal"
dot = Image.new("RGBA", (S, S), (0, 0, 0, 0)); dot.putpixel((10, 10), (0, 255, 0, 255))
hard = pic.copy(); hard.putpixel((2, 2), (220, 40, 40, 255))
stack = [L.Layer("Base", hard), L.Layer("Dot", dot), replace(cover, opacity=70)]
m2 = L.merge_down(stack, 2)
diff = max(abs(a - b) for y in range(S) for x in range(S)
           for a, b in zip(L.composite(m2, S).getpixel((x, y)), L.composite(stack, S).getpixel((x, y))))
assert diff <= 1, diff
print(f"merge down keeps the picture (max difference {diff})")

# ---- the app ----------------------------------------------------------------
axe = sorted(IMAGES.glob("Gemini*"))[1]
app.load_image(axe); app.transparent_var.set(True); app._settings_changed(); pump()
assert "Grayscale" in app.blend_box.cget("values")

# 1. Not on the bottom layer (it would hide everything): refused, with what to do instead
app.select_layer(0); n = len(app.history.undo_stack)
app.blend_box.set("Grayscale"); app.blend_box.event_generate("<<ComboboxSelected>>"); pump()
assert app.layers[0].mode == "Normal" and app.blend_box.get() == "Normal" and len(app.history.undo_stack) == n
assert "add a layer above it" in app.status_full
print("Grayscale on the Base: refused ('add a layer above it')")

# 2. A new empty layer set to Grayscale: filled, so everything beneath turns grey (one undo step)
app.add_layer(); pump(); n = len(app.history.undo_stack)
app.blend_box.set("Grayscale"); app.blend_box.event_generate("<<ComboboxSelected>>"); pump()
lay = app.layers[1]
assert lay.mode == "Grayscale" and len(app.history.undo_stack) == n + 1 and lay.image.getbbox() == (0, 0, 16, 16)
art = app.display_art
greys = [(x, y) for y in range(S) for x in range(S) if art.getpixel((x, y))[3]]
assert greys and all(len(set(art.getpixel(p)[:3])) == 1 for p in greys), "every visible pixel is grey"
assert art.getchannel("A").tobytes() == app.small_art.getchannel("A").tobytes(), "the sprite's shape unchanged"
assert all(art.getpixel(p)[0] == lum(app.small_art.getpixel(p)) for p in greys), "brightness kept"
assert "turns everything beneath it grayscale" in app.status_full and "Grayscale" in \
    app.layer_rows.winfo_children()[0].winfo_children()[-1].cget("text")
capture("1_all_grey.png")
print(f"empty layer -> Grayscale: filled; all {len(greys)} visible pixels grey, brightness and shape kept")

# 3. Erase part of it: that part keeps its colour; opacity greys partly; undo
app.select_tool("eraser")
for y in range(S):
    app._on_drag_start(at(0, y)); app._on_drag(at(7, y)); app._on_drag_end(at(7, y))
pump()
art = app.display_art
left = [p for p in greys if p[0] <= 7]; right = [p for p in greys if p[0] >= 8]
assert all(art.getpixel(p) == app.small_art.getpixel(p) for p in left) and all(len(set(art.getpixel(p)[:3])) == 1 for p in right)
app._on_opacity(50); pump()
assert any(len(set(app.display_art.getpixel(p)[:3])) > 1 for p in right), "50%: partly grey"
capture("2_half.png")
print("erased left half keeps its colour; right half grey; 50% opacity greys partly")

# 4. With a gradient layer in Grayscale mode: a gradual fade to grey; layers above aren't touched
app._on_opacity(100); pump()
app.select_tool("gradient"); app.select_layer(0); pump()
drag((0, 0), (15, 0))
g = app.layers[app.active_layer]
app.set_blend_mode("Grayscale"); pump()
assert g.mode == "Grayscale" and g.gradient is not None, "a gradient layer isn't filled over"
app.select_tool("pen"); app.set_paint_colour((0, 200, 0, 255))
app.select_layer(1); app.add_layer(); pump()  # just above the Gradient (under 'Layer 1', still Grayscale)
app._on_drag_start(at(10, 10)); app._on_drag_end(at(10, 10)); pump()
assert len(set(app.display_art.getpixel((10, 10))[:3])) == 1, "under a Grayscale layer: greyed"
app.undo(); app.undo()
app.select_layer(len(app.layers) - 1); app.add_layer(); pump()  # at the very top
app._on_drag_start(at(10, 10)); app._on_drag_end(at(10, 10)); pump()
top = len(app.layers) - 1
assert app.display_art.getpixel((10, 10)) == (0, 200, 0, 255), "a layer above a Grayscale layer keeps its colour"
print("gradient layer in Grayscale mode works; paint on layers above stays coloured")

# 5. Merge Down / Save keep the picture; screenshots, nothing squashed
pic = app.display_art.copy(); n = len(app.history.undo_stack)
app.select_layer(top); app.merge_layer_down(); pump()
assert len(app.layers) == top + 1 and len(app.history.undo_stack) == n and "can merge into it" in app.status_full
try:
    L.merge_down(app.layers, top); raise AssertionError("merged into an adjustment")
except ValueError:
    pass
app.merge_visible_layers(); pump()
assert same(app.display_art, pic) and [l.name for l in app.layers] == ["Merged"], "Merge All keeps the picture"
app.undo(); pump(); assert same(app.display_art, pic) and len(app.layers) == top + 1
app.select_layer(top); app.move_layer_down(); app.move_layer_down(); pump()  # paint under both Grayscale layers
app.select_layer(top); app.merge_layer_down(); pump()  # 'Layer 1' (Grayscale) into the Gradient (Grayscale): refused
assert "can merge into it" in app.status_full
app.select_layer(top - 1); before = app.display_art.copy(); app.merge_layer_down(); pump()  # Gradient into the paint
assert same(app.display_art, before), "merging a Grayscale layer down onto paint keeps the picture"
for _ in range(3): app.undo()
pump()
print("merge down INTO a Grayscale layer refused (with why); merging it down / Merge All keep the picture")
report = []
for size in ("1140x800", "900x720"):
    root.geometry(f"{size}+40+40"); pump(0.6)
    capture(f"3_{size}.png"); report.append(f"{size}: {squashed() or 'nothing squashed'}")
print("\n".join(report)); assert all("nothing squashed" in r for r in report)
print("ALL OK")
