import sys, time
from pathlib import Path
from PIL import Image

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
import pixel_core as pc
from fidelity import fidelity_error
from PIL import ImageChops

files = sorted(IMAGES.glob("*.jpg"))


def cut_of(img, res, subject):
    img = img.convert("RGBA")
    cut = img.copy()
    if subject is not None:
        cut.putalpha(ImageChops.darker(img.getchannel("A"), subject.mask))
    return pc._to_work_size(cut.crop(res.region), 512)


cases = [
    ("16 default", dict(grid=16, colors=10, enhance=True)),
    ("32 default", dict(grid=32, colors=16, enhance=True)),
    ("16 scaled/moved", dict(grid=16, colors=10, enhance=True, scale=0.7, offset=(2, -1))),
    ("16 no clean-up", dict(grid=16, colors=10, enhance=False)),
    ("16 transparent", dict(grid=16, colors=10, enhance=True, transparent_bg=True)),
]
worse = 0
for f in files:
    img = Image.open(f); img.load()
    subject = pc.find_subject(img, "plain")
    for name, o in cases:
        g, c = o.pop("grid"), o.pop("colors")
        common = dict(outline="outside", detail=30, fit_subject=True, **o)
        a = pc.pixelate_detailed(img, g, c, **common)
        t = time.perf_counter()
        b = pc.pixelate_detailed(img, g, c, match_source=True, **common)
        dt = time.perf_counter() - t
        o.update(grid=g, colors=c)
        # colour limit held, region unchanged (silhouette checked on the fill below)
        assert len([x for x in b.small.getcolors(4096) if x[1][3]]) <= c
        assert a.region == b.region
        cut = cut_of(img, a, subject)
        # Fidelity is measured on the fill only: same settings but no lines
        # and a transparent background, so only the subject's pixels count.
        fill = {**common, "outline": "off", "detail": 0, "transparent_bg": True}
        fa = pc.pixelate_detailed(img, g, c, **fill).small
        fb = pc.pixelate_detailed(img, g, c, match_source=True, **fill).small
        assert fa.getchannel("A").tobytes() == fb.getchannel("A").tobytes(), (f.name, name, "silhouette")
        ea, eb = fidelity_error(fa, cut, g), fidelity_error(fb, cut, g)
        # Regression: lines (+ pixel-perfect clean-up) never remove subject pixels
        for mode in ("outside", "inside"):
            lined = pc.pixelate_detailed(img, g, c, **{**fill, "outline": mode, "detail": 60}).small
            fa_px, l_px = fa.getchannel("A").load(), lined.getchannel("A").load()
            holes = [(x, y) for y in range(g) for x in range(g) if fa_px[x, y] and not l_px[x, y]]
            assert not holes, (f.name, name, mode, holes)
        worse += eb > ea
        print(f"{f.name[:10]} {name:16s} error {ea:5.2f} -> {eb:5.2f} ({(eb - ea) / ea * 100:+4.0f}%)  {dt * 1000:4.0f} ms")

# No plain background (busy noise): falls back to the plain branch
busy = Image.effect_noise((300, 300), 80).convert("RGB")
r = pc.pixelate_detailed(busy, 16, 8, detail=30, fit_subject=True, enhance=True, match_source=True)
assert r.subject_found is False and len(r.small.getcolors(4096)) <= 8
print("no-subject fallback OK")
# AI subject too
if pc.ai_status() is None:
    r = pc.pixelate_detailed(Image.open(files[0]), 16, 10, background="ai", outline="outside", detail=30,
                             fit_subject=True, enhance=True, match_source=True)
    assert r.subject_found
    print("AI + match OK")
print("worse cases:", worse)
