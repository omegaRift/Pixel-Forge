import sys
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
from pixel_core import pixelate, pixelate_detailed, center_crop_to_square

OUT = SCR / "scale_shots"; OUT.mkdir(exist_ok=True)
files = sorted(IMAGES.glob("*.jpg"))


def reference(img, grid, colors):
    """The original spec pipeline, verbatim."""
    img = center_crop_to_square(img.convert("RGBA"))
    small = img.resize((grid, grid), resample=Image.Resampling.BILINEAR)
    q = small.convert("RGB").quantize(colors=min(colors, grid * grid), method=Image.Quantize.MEDIANCUT,
                                      dither=Image.Dither.NONE).convert("RGBA")
    q.putalpha(small.getchannel("A").point(lambda a: 255 if a >= 128 else 0))
    return q


def bbox(art):
    return art.getchannel("A").point(lambda a: 255 if a else 0).getbbox()


for f in files:
    img = Image.open(f); img.load()
    wide = img.crop((0, 0, img.width, img.height * 2 // 3))  # non-square too
    for src in (img, wide):
        for g, c in ((16, 8), (32, 16)):
            assert pixelate(src, g, c)[0].tobytes() == reference(src, g, c).tobytes()
    for g in (16, 32):
        # 100%: margins clean (transparent, no outline)
        r = pixelate_detailed(img, g, 16, fit_subject=True, transparent_bg=True)
        a = r.small.getchannel("A").load()
        border = [a[x, y] for x in range(g) for y in (0, g - 1)] + [a[x, y] for y in range(g) for x in (0, g - 1)]
        assert not any(border), (f.name, g, "margin")
        b100 = bbox(r.small); s100 = max(b100[2] - b100[0], b100[3] - b100[1])
        # 50%: subject about half the size, centred
        b50 = bbox(pixelate_detailed(img, g, 16, fit_subject=True, transparent_bg=True, scale=0.5).small)
        s50 = max(b50[2] - b50[0], b50[3] - b50[1])
        assert abs(s50 - s100 / 2) <= 1.5, (f.name, g, s100, s50)
        # 150%: zoomed in, crops at the frame
        b150 = bbox(pixelate_detailed(img, g, 16, fit_subject=True, transparent_bg=True, scale=1.5).small)
        assert b150[0] == 0 or b150[1] == 0 or b150[2] == g or b150[3] == g
        # offset: moves the subject exactly by (dx, dy) at 50% (room to move)
        bo = bbox(pixelate_detailed(img, g, 16, fit_subject=True, transparent_bg=True, scale=0.5, offset=(3, -2)).small)
        assert (bo[0] - b50[0], bo[1] - b50[1]) == (3, -2), (f.name, g, b50, bo)
        # colour limit with outline + flat bg while zoomed out
        rr = pixelate_detailed(img, g, 6, outline="outside", detail=50, fit_subject=True, scale=0.6)
        assert len(rr.small.getcolors(4096)) <= 6
    # plain mode (no subject features) also scales: zoomed-out busy photo
    p = pixelate_detailed(wide, 32, 8, scale=0.5)
    assert p.small.getchannel("A").getextrema() == (0, 255) and len([c for c in p.small.getcolors(4096) if c[1][3]]) <= 8
    print(f"{f.name[:14]}: default == spec, 100% margins clean, 50% size {s50}/{s100}, 150% crops, offset exact")

# Visual sheet: one image at several scales, 32x32
img = Image.open(files[3])
scales = [0.5, 0.75, 1.0, 1.25, 1.5]
cell = 192
sheet = Image.new("RGB", (len(scales) * (cell + 8) + 8, 2 * (cell + 22) + 8), (18, 18, 28))
d = ImageDraw.Draw(sheet)
for row, off in enumerate([(0, 0), (4, 3)]):
    for i, s in enumerate(scales):
        r = pixelate_detailed(img, 32, 16, outline="outside", detail=50, fit_subject=True, scale=s, offset=off)
        x, y = 8 + i * (cell + 8), 8 + row * (cell + 22)
        sheet.paste(r.small.convert("RGB").resize((cell, cell), Image.NEAREST), (x, y + 16))
        d.text((x, y + 2), f"scale {int(s * 100)}%  offset {off}", fill="white")
sheet.save(OUT / "scale_sheet.png")
print("ALL OK")
