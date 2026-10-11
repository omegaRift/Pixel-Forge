"""Texture projection in layers.py."""
import sys
from dataclasses import replace
from PIL import Image, ImageDraw
from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
import layers as L

same = lambda a, b: a.tobytes() == b.tobytes()
S = 16
# A 4x4 checker texture (red / blue), and a drawing: a filled circle, grey, on transparency
tex = Image.new("RGBA", (4, 4))
for y in range(4):
    for x in range(4):
        tex.putpixel((x, y), (255, 0, 0, 255) if (x // 2 + y // 2) % 2 == 0 else (0, 0, 255, 255))
draw = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(draw).ellipse((2, 2, 13, 13), fill=(128, 128, 128, 255))
draw.putpixel((2, 8), (128, 128, 128, 100))  # a half-see-through edge pixel

# 1. Default: pixel for pixel (4 px texture on 16 px -> scale 0.25, tiled 4 times)
p = L.default_projection(tex, S, "checker.png")
assert p.scale == 0.25 and p.name == "checker.png"
tile = L.projection_tile(p, S)
assert all(tile.getpixel((x, y)) == tex.getpixel((x % 4, y % 4)) for y in range(S) for x in range(S))
out = L.projected(draw, p)
assert out.getchannel("A").tobytes() == draw.getchannel("A").tobytes(), "the drawing's shape, exactly"
assert out.getpixel((8, 8)) == tex.getpixel((0, 0)) and out.getpixel((0, 0)) == (0, 0, 0, 0)
assert out.getpixel((2, 8))[:3] == tex.getpixel((2, 0))[:3] and out.getpixel((2, 8))[3] == 100
print("tiles pixel for pixel, fills only the drawn pixels (alpha kept)")

# 2. Scale 1.0 = stretched once across (NEAREST: each texture pixel = 4x4 art pixels); big textures shrink
big = replace(p, scale=1.0)
t1 = L.projection_tile(big, S)
assert t1.getpixel((3, 3)) == tex.getpixel((0, 0)) and t1.getpixel((4, 0)) == tex.getpixel((1, 0))
photo = Image.effect_noise((200, 100), 50).convert("RGBA")
pp = L.default_projection(photo, S)
pt = L.projection_tile(pp, S)
assert pp.scale == 1.0 and all(pt.getpixel((x, y)) == pt.getpixel((x, y + 8)) for y in range(8) for x in range(S)), \
    "aspect kept: a 2:1 picture is 16x8 across, repeating down"

# 3. Offset wraps; positions are fractions (same place at 32)
off = replace(p, offset=(1 / S, 0))
assert L.projection_tile(off, S).getpixel((1, 0)) == tex.getpixel((0, 0))
assert L.projection_tile(off, S).getpixel((0, 0)) == tex.getpixel((3, 0))
assert L.projection_tile(off, 32).getpixel((2, 0)) == tex.getpixel((0, 0)), "2 px at 32 = 1 px at 16"
print("scale 1 stretches (aspect kept), offset wraps and scales with the grid")

# 4. Mix modes and strength keep the drawing's shading
shade = draw.copy(); shade.putpixel((8, 8), (64, 64, 64, 255))
m = L.projected(shade, replace(p, mode="Multiply"))
assert m.getpixel((8, 8))[:3] == (64, 0, 0) and m.getpixel((6, 6))[:3] == (128, 0, 0)
half = L.projected(shade, replace(p, strength=50))
assert half.getpixel((6, 6))[:3] == (192, 64, 64), half.getpixel((6, 6))
see = tex.copy(); see.putpixel((0, 0), (0, 0, 0, 0))
assert L.projected(draw, replace(p, texture=see)).getpixel((8, 8))[:3] == (128, 128, 128), "see-through texture: drawing shows"
print("Multiply keeps shading, strength 50% mixes, see-through texture pixels show the drawing")

# 5. As a layer: composite, fade on top, bake, merge, resize, undo copy
lay = L.Layer("Stone", draw, projection=p)
assert same(L.shown_pixels(lay), out) and L.faded is L.shown_pixels
base = L.Layer("Base", Image.new("RGBA", (S, S), (20, 120, 40, 255)))
stack = [base, lay]
pic = L.composite(stack, S)
assert pic.getpixel((8, 8)) == tex.getpixel((0, 0)) and pic.getpixel((0, 0)) == (20, 120, 40, 255)
both = L.shown_pixels(replace(lay, fade=replace(L.FADE, start=(0.5, 0), end=(0.5, 1))))
assert both.getpixel((8, 3))[:3] == tex.getpixel((0, 3))[:3] and both.getpixel((8, 12))[3] < 255
b = L.bake(lay, L.blank(S))
assert b.projection is None and same(b.image, out)
m1 = L.merge_down(stack, 1); assert same(L.composite(m1, S), pic) and m1[0].projection is None
dot = Image.new("RGBA", (S, S), (0, 0, 0, 0)); dot.putpixel((1, 1), (255, 255, 0, 255))
m2 = L.merge_down([base, lay, L.Layer("Dot", dot)], 2)
assert same(L.composite(m2, S), L.composite([base, lay, L.Layer("Dot", dot)], S)) and m2[1].projection is None
r = L.resize_layers([lay], 32)[0]
assert r.projection is p and L.shown_pixels(r).getpixel((17, 17)) == tex.getpixel((0, 0))
h = L.History(); h.push([lay], 0); back, _ = h.undo([replace(lay, projection=None)], 0)
assert back[0].projection is p
assert L.projection_tile(p, S) is L.projection_tile(p, S), "cached"
print("layer: composites, fade applies after it, bake/merge keep the picture, resize and undo keep it")
print("ALL OK")
