"""Projecting a texture onto a drawn layer, in the real app (hidden window)."""
import os
from pathlib import Path
from PIL import Image, ImageDraw

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
os.environ["PIXEL_FORGE_HIDDEN"] = "1"
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
import projection_ui
same = lambda a, b: a.tobytes() == b.tobytes()
undo_n = lambda: len(app.history.undo_stack)

# Two texture files: "cobble" (16x16 two-tone noise) and "planks" (8x8 stripes)
cobble = Image.new("RGBA", (16, 16))
for y in range(16):
    for x in range(16):
        cobble.putpixel((x, y), (110, 110, 118, 255) if (x * 7 + y * 13) % 5 else (70, 70, 78, 255))
cobble_path = SCR / "cobble.png"; cobble.save(cobble_path)
planks = Image.new("RGBA", (8, 8), (160, 110, 60, 255)); ImageDraw.Draw(planks).line((0, 3, 7, 3), fill=(100, 70, 40, 255))
planks_path = SCR / "planks.png"; planks.save(planks_path)
pick = {"path": str(cobble_path)}
projection_ui.filedialog.askopenfilename = lambda **k: pick["path"]

axe = sorted(IMAGES.glob("Gemini*"))[1]
app.load_image(axe); app.transparent_var.set(True); app._settings_changed(); pump()

# A drawn layer: a filled blob (Pen strokes)
app.add_layer(); app.select_tool("pen"); app.set_paint_colour((200, 60, 60, 255))
for y in range(3, 9):
    app._on_drag_start(at(3, y)); app._on_drag(at(10, y)); app._on_drag_end(at(10, y))
pump()
drawn = app.layers[1].image.copy()
assert app.project_btn.winfo_ismapped() and str(app.project_btn.cget("state")) == "normal"

# 1. Project a texture onto it
n = undo_n()
app.project_texture(); pump()
lay = app.layers[1]
assert lay.projection is not None and lay.projection.name == "cobble.png" and lay.projection.scale == 1.0 and undo_n() == n + 1
assert same(lay.image, drawn), "the drawing itself is untouched"
assert app.display_art.getpixel((5, 5)) == cobble.getpixel((5, 5)), "the texture fills the drawn pixels"
assert app.display_art.getpixel((12, 12)) == app.small_art.getpixel((12, 12)), "outside the drawing: unchanged"
assert same(app.display_art, L.composite(app.layers, 16))
assert app.projection_panel.winfo_ismapped() and app.proj_name.cget("text") == "cobble.png"
assert app.proj_size_label.cget("text") == "16 px" and app.proj_layer_label.cget("text") == "cobble.png"
assert "tex" in app.layer_rows.winfo_children()[0].winfo_children()[-1].cget("text")
assert "Projected 'cobble.png' onto 'Layer 1'" in app.status_full
capture("1_projected.png")
print("projected cobble.png onto the drawn 'Layer 1': fills just the drawing, pixels untouched, panel shown")

# 2. Keep drawing: the texture fills the new pixels too
app._on_drag_start(at(3, 12)); app._on_drag(at(8, 12)); app._on_drag_end(at(8, 12)); pump()
assert app.display_art.getpixel((6, 12)) == cobble.getpixel((6, 12)), "new drawing is textured"
assert app.layers[1].projection is not None
print("drawing more on the layer: textured too")

# 3. Settings, one undo step each
def step(action, check, label):
    before = undo_n(); action(); pump(0.1)
    assert undo_n() == before + 1, (label, undo_n() - before)
    assert check(app.layers[1].projection), label
    assert same(app.display_art, L.composite(app.layers, 16)), label

def size_drag():
    app._proj_slider["size"].update(down=True, saved=False)
    app._on_proj_size(12); app._on_proj_size(8.3); app._on_proj_size(8)
    app._proj_slider["size"].update(down=False)
step(size_drag, lambda p: p.scale == 0.5 and app.proj_size_label.cget("text") == "8 px", "size 8 (tiles)")
assert app.display_art.getpixel((5, 5)) == cobble.resize((8, 8), Image.Resampling.BOX).getpixel((5, 5))
step(lambda: app.nudge_projection(1, 0), lambda p: abs(p.offset[0] - 1 / 16) < 1e-9, "move right")
step(lambda: app.nudge_projection(0, -1), lambda p: abs(p.offset[1] + 1 / 16) < 1e-9, "move up")
def mix():
    app.proj_mode_box.set("Multiply"); app.proj_mode_box.event_generate("<<ComboboxSelected>>")
step(mix, lambda p: p.mode == "Multiply", "mix Multiply")
step(lambda: app._on_proj_strength(60), lambda p: p.strength == 60 and app.proj_strength_label.cget("text") == "60%",
     "strength 60")
step(lambda: find(app.projection_panel, ttk.Button, "Reset").invoke(), lambda p: p.offset == (0.0, 0.0), "reset")
capture("2_multiply.png")
print("size (tiles, 1 undo per drag), move, reset, mix, strength: each 1 undo step")

# 4. Change the texture: keeps position, mix, strength
pick["path"] = str(planks_path)
app.nudge_projection(2, 0)
find(app.projection_panel, ttk.Button, "Change...").invoke(); pump()
p = app.layers[1].projection
assert p.name == "planks.png" and p.scale == 0.5 and p.mode == "Multiply" and p.strength == 60
assert abs(p.offset[0] - 2 / 16) < 1e-9
print("Change... swapped in planks.png (8 px -> tiles twice) and kept move / mix / strength")

# 5. Remove (the small x in the layers panel), undo
app.proj_remove_small.invoke(); pump()
assert app.layers[1].projection is None and not app.projection_panel.winfo_ismapped()
app.undo(); pump(); assert app.layers[1].projection is not None and app.projection_panel.winfo_ismapped()
print("remove + undo")

# 6. An empty layer: projecting says to draw; drawing shows the texture
app.add_layer(); pump()
pick["path"] = str(cobble_path); app.project_texture(); pump()
assert "draw on it" in app.status_full and "Draw on" in app.proj_hint.cget("text")
app.select_tool("pen"); app._on_drag_start(at(13, 13)); app._on_drag_end(at(13, 13)); pump()
assert app.display_art.getpixel((13, 13)) == cobble.getpixel((13, 13))
app.undo(); app.undo(); app.undo(); pump()
print("empty layer: told to draw; the drawn pixel is textured")

# 7. Not on gradient layers; merge down keeps the picture; grid 32 follows
app.select_tool("gradient"); drag((0, 0), (15, 15)); pump()
assert app.layers[app.active_layer].gradient is not None and str(app.project_btn.cget("state")) == "disabled"
app.undo(); pump(); app.select_layer(1); pump()
pic = app.display_art.copy()
app.merge_layer_down(); pump()
assert same(app.display_art, pic) and all(l.projection is None for l in app.layers)
app.undo(); pump(); app.select_layer(1)
app.grid_var.set(32); app._settings_changed(); pump()
assert same(app.display_art, L.composite(app.layers, 32)) and app.layers[1].projection is not None
app.grid_var.set(16); app._settings_changed(); pump()
print("gradient layers can't take one; merge down bakes it (same picture); grid 32 follows")

# 8. Screenshots + nothing squashed
app.select_layer(1); app.select_tool("pen"); pump()
report = []
for size in ("1140x800", "900x720"):
    root.geometry(f"{size}+40+40"); pump(0.6)
    capture(f"3_panel_{size}.png")
    report.append(f"{size}: {squashed() or 'nothing squashed'}")
print("\n".join(report)); assert all("nothing squashed" in r for r in report)
root.geometry("1140x800+40+40"); pump()

# 9. Grass Block edit session: project onto the texture itself, Save & Return
tex = SCR / "proj_session.png"
t = Image.new("RGBA", (16, 16), (0, 0, 0, 0)); ImageDraw.Draw(t).ellipse((2, 2, 13, 13), fill=(120, 120, 120, 255)); t.save(tex)
assert app.start_session({"path": str(tex), "name": "Rock", "result": None, "caller": "Grass Block"})
pump()
app.project_texture(); pump()
assert app.layers[0].projection is not None
shown = app.display_art.copy()
capture("4_session.png")
app.session_save()
saved = Image.open(tex).convert("RGBA")
assert same(saved, shown) and saved.getpixel((0, 0))[3] == 0 and saved.getpixel((7, 7)) == cobble.getpixel((7, 7))
print("edit session: cobble projected onto the texture's shape, Save & Return wrote it")
try:
    pump(0.3)
except tk.TclError:
    pass
print("ALL OK")
