"""Grid Resolution 16, 32, 64 and 128: the converter at the big sizes, the sidebar choice, the editor
drawing only what's on screen, the Minecraft tab fitting, saving and Batch (invisible window)."""
import os
import random
import shutil
import time

os.environ["PIXEL_FORGE_HIDDEN"] = "1"  # dialogs are created withdrawn
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
import editor_ui
import mc_preview
import pixel_core

errors = []
root.report_callback_exception = lambda *a: errors.append(a[1])
pictures = sorted(IMAGES.glob("*.jpg"))
work = SCR / "grid_sizes"
shutil.rmtree(work, ignore_errors=True)
work.mkdir()


def until(cond, limit=60.0):
    end = time.time() + limit
    while time.time() < end:
        root.update(); time.sleep(0.02)
        if cond():
            return
    raise AssertionError("timed out")


# 1. The four sizes, in order (16 and 32 as before)
assert list(pixel_core.GRID_OPTIONS.items()) == [("16 x 16", 16), ("32 x 32", 32), ("64 x 64", 64),
                                                 ("128 x 128", 128)], pixel_core.GRID_OPTIONS
print("grid sizes: 16, 32, 64, 128")

# 2. The converter at 64 and 128: the right size, the colour limit kept, every feature
img = Image.open(pictures[0]); img.load()
for g in (64, 128):
    for opts in ({}, {"enhance": True}, {"enhance": True, "outline": "outside", "detail": 40, "transparent_bg": True},
                 {"outline": "inside", "fit_subject": True, "scale": 0.6, "offset": (5, -3)}):
        r = pixel_core.pixelate_detailed(img, g, 12, **opts)
        assert r.small.size == (g, g) and r.large.size == (pixel_core.PREVIEW_SIZE,) * 2, (g, opts)
        colours = [c for c in r.small.getcolors(g * g) if c[1][3]]
        assert 2 <= len(colours) <= 12, (g, opts, len(colours))
        # the 512 px art is the sprite enlarged with whole blocks (512 / 128 = 4 px each)
        assert r.large.resize((g, g), Image.Resampling.NEAREST).tobytes() == r.small.tobytes(), (g, opts)
t = time.perf_counter()
m = pixel_core.pixelate_detailed(img, 64, 12, enhance=True, transparent_bg=True, match_source=True)
assert m.small.size == (64, 64) and len([c for c in m.small.getcolors(4096) if c[1][3]]) <= 12
print(f"converter at 64 and 128: right sizes, colour limit kept, 512 art = whole blocks; "
      f"Match Original at 64 took {time.perf_counter() - t:.1f}s")

# 3. The editor enlarges only what's on screen, pixel for pixel as enlarging the whole sprite
random.seed(7)


def whole(art, k, pixel_grid):
    """How it was drawn before: the whole sprite enlarged."""
    g = art.width
    big = art.resize((g * k, g * k), Image.Resampling.NEAREST)
    view = editor_ui.checkerboard(big.width, big.height, max(4, k // 2)).convert("RGBA")
    view.alpha_composite(big)
    if pixel_grid:
        lines = Image.new("RGBA", view.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(lines)
        for i in range(1, g):
            d.line([(i * k, 0), (i * k, view.height)], fill=(255, 255, 255, 34))
            d.line([(0, i * k), (view.width, i * k)], fill=(255, 255, 255, 34))
        view.alpha_composite(lines)
    return view


for trial in range(60):
    g = random.choice((16, 32, 64))
    k = random.choice((1, 2, 3, 5, 6, 7, 8, 9, 12, 16, 24))
    art = Image.new("RGBA", (g, g))
    art.putdata([(random.randrange(256), random.randrange(256), random.randrange(256), random.choice((0, 128, 255)))
                 for _ in range(g * g)])
    w, h = random.randrange(40, 400), random.randrange(40, 400)
    size = g * k
    ox = random.randrange(w - size + 1, 2) if size > w else (w - size) // 2 + 1
    oy = random.randrange(h - size + 1, 2) if size > h else (h - size) // 2 + 1
    grid_on = random.random() < 0.5
    view, vx, vy = editor_ui.enlarged_view(art, k, ox, oy, w, h, pixel_grid=grid_on)
    ref = whole(art, k, grid_on).crop((vx - ox, vy - oy, vx - ox + view.width, vy - oy + view.height))
    assert view.tobytes() == ref.tobytes(), (trial, g, k, ox, oy, w, h)
    # it covers every bit of the sprite that's on the canvas
    assert vx <= max(ox, 0) and vy <= max(oy, 0), (trial, vx, vy, ox, oy)
    assert vx + view.width >= min(ox + size, w) and vy + view.height >= min(oy + size, h), (trial,)
    assert view.width <= min(size, w + 2 * k) and view.height <= min(size, h + 2 * k), (trial, view.size)
print("the editor's view: only what's on screen, pixel for pixel the same as enlarging the whole sprite (60 cases)")

# 4. The Minecraft mock-up: 16 and 32 as before, big textures at a density that fits
for t in (16, 32):
    k, c, r = mc_preview.best_fit(620, 520, t)
    sprite = Image.new("RGBA", (t, t), (200, 30, 30, 255))
    assert mc_preview.fit_density(620, 520, t) == t // 16
    assert mc_preview.render_inventory(sprite, "X", cols=c, rows=r).tobytes() == \
        mc_preview.render_inventory(sprite, "X", cols=c, rows=r, density=t // 16).tobytes()
for t in (64, 128, 256):
    for room in ((620, 520), (400, 300), (1200, 900)):
        d = mc_preview.fit_density(*room, t)
        k, c, r = mc_preview.best_fit(*room, 16 * d)
        mock = mc_preview.render_inventory(Image.new("RGBA", (t, t), (200, 30, 30, 255)), "X", cols=c, rows=r,
                                           density=d)
        assert mock.width * k <= room[0] and mock.height * k <= room[1], (t, room, d, mock.size, k)
        assert 1 <= d <= t // 16
assert mc_preview.fit_density(1200, 900, 64) == 4, "with room, 64x64 shows at its own density"
print("Minecraft mock-up: 16/32 unchanged, 64/128/256 drawn at a density that fits the room")

# 5. The sidebar: four choices on one row, nothing squashed
radios = [c for c in app.grid_row.winfo_children() if isinstance(c, ttk.Radiobutton)]
assert [r.cget("text") for r in radios] == list(pixel_core.GRID_OPTIONS), [r.cget("text") for r in radios]
assert app.load_image(pictures[1])
until(lambda: not app.busy())
side_w = app.adjust_area.winfo_width()
for size in ("900x720", "1140x800", "1280x800"):
    root.geometry(f"{size}+40+40"); pump(0.3)
    for r in radios:  # each whole, inside the sidebar, two to a line
        right = r.winfo_rootx() + r.winfo_width() - app.grid_row.winfo_rootx()
        assert r.winfo_ismapped() and r.winfo_width() >= r.winfo_reqwidth() and right <= app.grid_row.winfo_width() + 1,             (size, r.cget("text"), right, app.grid_row.winfo_width())
    assert radios[0].winfo_rooty() == radios[1].winfo_rooty() < radios[2].winfo_rooty() == radios[3].winfo_rooty()
    assert radios[0].winfo_rootx() == radios[2].winfo_rootx() and radios[1].winfo_rootx() == radios[3].winfo_rootx()
    assert not squashed(), (size, squashed())
root.geometry("1140x800+40+40"); pump(0.3)
capture("grid_row.png")
print("the sidebar shows 16 x 16, 32 x 32 / 64 x 64, 128 x 128 in two lines, whole at 900, 1140 and 1280 wide")

# 6. Choosing 128: a 128x128 sprite, painted layers follow, and the editor zooms all the way quickly
app.select_tool("pen")
app.view_var.set("edit"); app._on_view(); pump(0.2)
for g in (64, 128):
    find(app.grid_row, ttk.Radiobutton, f"{g} x {g}").invoke()
    until(lambda: app.small_art.size == (g, g) and not app.busy())
    pump(0.2)
    assert app.small_art.size == (g, g) and app.display_art.size == (g, g), (g, app.small_art.size)
    assert app.art_title.cget("text").startswith(f"{g}x{g} sprite"), app.art_title.cget("text")
    assert all(l.image.size == (g, g) for l in app.layers), [l.image.size for l in app.layers]
capture("edit_128_fit.png")
app.add_layer(); pump(0.1)
app.paint_colour = (255, 0, 255, 255)
app._edit_press(at(100, 20)); app._edit_release(at(100, 20)); pump(0.2)
assert app.layers[app.active_layer].image.getpixel((100, 20)) == (255, 0, 255, 255)
assert app.display_art.getpixel((100, 20)) == (255, 0, 255, 255)
cw, ch = app._canvas_size(app.art_canvas)
for _ in range(12):
    app.zoom_at(cw // 2, ch // 2, 1)
assert app.zoom == 128, app.zoom
t = time.perf_counter()
app._draw_art(); root.update()
took = time.perf_counter() - t
photo = app._photos["art"]
assert photo.width() <= cw + 2 * 128 and photo.height() <= ch + 2 * 128, (photo.width(), photo.height(), cw, ch)
assert took < 1.0, f"drawing at 128x zoom took {took:.2f}s"
# painting at full zoom lands on the pixel under the pointer
p = app._pixel_at(cw // 2, ch // 2)
app._edit_press(Ev(x=cw // 2, y=ch // 2, widget=root, state=0)); app._edit_release(Ev(x=cw // 2, y=ch // 2, widget=root, state=0))
pump(0.1)
assert app.layers[app.active_layer].image.getpixel(p) == (255, 0, 255, 255), p
capture("edit_128_zoomed.png")
app.zoom_fit(); pump(0.1)
print(f"128 x 128: a 128x128 sprite and layers; painting works; 128x zoom draws in {took * 1000:.0f} ms "
      f"({photo.width()}x{photo.height()} px, not 16384 px square)")

# 7. The Minecraft tab fits the 128x128 item
app.view_var.set("game"); app._on_view(); pump(0.3)
gw, gh = app._canvas_size(app.game_canvas)
game = app._photos["game"]
assert game.width() <= gw and game.height() <= gh, (game.width(), game.height(), gw, gh)
capture("game_128.png")
app.view_var.set("sprite"); app._on_view(); pump(0.2)
print(f"Minecraft tab: the 128x128 item's mock-up ({game.width()}x{game.height()}) fits the tab ({gw}x{gh})")

# 8. Saving: the sprite at 128x128, the art at 512
assert app.save(work / "big.png", raw=True) and app.save(work / "big_512.png", raw=False)
with Image.open(work / "big.png") as s, Image.open(work / "big_512.png") as a:
    assert s.size == (128, 128) and a.size == (512, 512), (s.size, a.size)
print("Save Sprite writes 128x128, Save Art 512x512")

# 9. Batch converts at the chosen size
app.open_batch(); pump(0.2)
assert app.batch_sprite_check.cget("text") == "Sprite (128x128)", app.batch_sprite_check.cget("text")
app.add_batch_pictures(pictures[:2])
app._batch_dir = work / "batch"
app._batch_dir.mkdir()
app.batch_remove_var.set(False); app._update_batch_controls()
app.start_batch(); until(lambda: not app.busy(), 120)
made = sorted((work / "batch").glob("*.png"))
assert len(made) == 2 and all(Image.open(f).size == (128, 128) for f in made), made
app.close_batch(); pump(0.1)
print("Batch: Sprite (128x128), and the files are 128x128")

# 10. Back to 16: as before
find(app.grid_row, ttk.Radiobutton, "16 x 16").invoke()
until(lambda: app.small_art.size == (16, 16) and not app.busy())
assert app.small_art.size == (16, 16) and all(l.image.size == (16, 16) for l in app.layers)
assert not errors, errors
print("ALL OK")
