"""Turning a layer into a gradient blending overlay (a fade), in the real app (hidden window)."""
import os, shutil, sys, time
from dataclasses import replace
from pathlib import Path
from PIL import Image, ImageDraw

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
same = lambda a, b: a.tobytes() == b.tobytes()
undo_n = lambda: len(app.history.undo_stack)
alphas = lambda im: {a for _, (r, g, b, a) in im.getcolors(1 << 16)}

axe = sorted(IMAGES.glob("Gemini*"))[1]
app.load_image(axe); app.transparent_var.set(True); app._settings_changed(); pump()
panel = app.gradient_panel
shown_rows = lambda: [n for n in L_ROWS if app._grad_rows[n].winfo_ismapped()]
L_ROWS = ("head", "mode", "shape", "colours", "fade_colour", "fade_to", "steps", "options", "hint", "rule")

# A "Glow" layer: a solid colour over the whole square
app.add_layer(); app.select_tool("fill"); glow_rgb = (250, 200, 60, 255); app.set_paint_colour(glow_rgb)
app._on_drag_start(at(0, 0)); app._on_drag_end(at(0, 0)); pump()
app.rename_layer if False else None
app.layers[1].name = "Glow"; app._layers_changed(); pump()
raw = app.layers[1].image.copy()
assert raw.getcolors() == [(256, glow_rgb)]

# 1. The Gradient toggle next to Blend turns it into a gradient blending overlay
n = undo_n()
assert not app.grad_blend_var.get() and str(app.blend_toggle.cget("text")) == "Gradient"
app.blend_toggle.invoke(); pump()
glow = app.layers[1]
assert glow.fade == L.FADE and app.grad_blend_var.get() and undo_n() == n + 1
assert app.tool_var.get() == "gradient" and app.grad_mode.get() == "blend" and app.view_var.get() == "edit"
assert app.grad_title.cget("text") == "GRADIENT BLEND" and app.grad_target.cget("text") == "Glow"
assert shown_rows() == ["head", "mode", "shape", "fade_to", "steps", "options", "hint", "rule"], shown_rows()
assert app.grad_remove_btn.winfo_ismapped() and not app.grad_clip_check.winfo_ismapped()
assert "fades into the layers below" in app.status_full
assert same(glow.image, raw), "its own pixels are untouched"
assert same(app.display_art, L.composite(app.layers, 16))
top, bottom = app.display_art.getpixel((0, 0)), app.display_art.getpixel((0, 15))
assert top == glow_rgb and bottom == app.small_art.getpixel((0, 15)), (top, bottom)
assert "fade" in [w for w in app.layer_rows.winfo_children()][0].winfo_children()[-1].cget("text")
assert app.art_canvas.find_withtag("guide"), "the fade's direction is shown"
capture("1_blend_on.png")
print("toggle: 'Glow' fades top -> bottom into the Base (pixels untouched), Gradient tool in Blend mode, panel shows it")

# 2. Drag re-aims the fade; undo / redo
drag((0, 8), (15, 8))
f = app.layers[1].fade
assert abs(f.start[1] - f.end[1]) < 1e-9 and f.end[0] > f.start[0] and len(app.layers) == 2
assert app.display_art.getpixel((0, 8)) == glow_rgb and app.display_art.getpixel((15, 8)) == app.small_art.getpixel((15, 8))
app.undo(); pump(); assert app.layers[1].fade == L.FADE
app.redo(); pump(); assert app.layers[1].fade == f
print("drag: fade re-aimed left -> right (no new layer); undo/redo")

# 3. Panel settings, one undo step each
def step(action, check, label):
    before = undo_n(); action(); pump(0.1)
    assert undo_n() == before + 1, (label, undo_n() - before)
    assert check(app.layers[1]), label
    assert same(app.display_art, L.composite(app.layers, 16)), label

def fade_to_drag():
    app._grad_sliders["fade_to"].update(down=True, saved=False)
    app._on_grad_fade_to(20); app._on_grad_fade_to(35.2); app._on_grad_fade_to(40)
    app._grad_sliders["fade_to"].update(down=False)
step(fade_to_drag, lambda l: l.fade.colours[1][3] == 102 and app.grad_fade_to_label.cget("text") == "40%", "fade to 40%")
right = L.faded(app.layers[1]).getpixel((15, 8))[3]
assert right == 102, right
step(lambda: app._on_grad_steps(2), lambda l: l.fade.steps == 2, "steps 2")
step(lambda: find(panel, ttk.Checkbutton, "Dither").invoke(), lambda l: l.fade.dither, "dither")
assert alphas(L.faded(app.layers[1])) == {102, 255}, alphas(L.faded(app.layers[1]))
step(lambda: app._on_grad_fade_to(0), lambda l: l.fade.colours[1][3] == 0, "fade to 0%")
assert alphas(L.faded(app.layers[1])) == {0, 255}, "2 steps + dither + 0%: no half-see-through pixels"
step(lambda: find(panel, ttk.Radiobutton, "Radial").invoke(), lambda l: l.fade.shape == "radial", "radial")
assert app._fade_template.steps == 2 and app._fade_template.dither, "the next blend starts like this one"
assert app._grad_template.steps == 4, "the colour gradient settings are separate"
capture("2_blend_dither.png")
print("fade to (1 undo step per drag), steps, dither (2 steps + dither = only 0/255 alpha), shape: each 1 undo step")

# 4. Painting on a blended layer keeps the blend
app.select_tool("pen"); app.set_paint_colour((20, 220, 120, 255))
app._on_drag_start(at(8, 8)); app._on_drag_end(at(8, 8)); pump()
assert app.layers[1].fade is not None and app.layers[1].image.getpixel((8, 8)) == (20, 220, 120, 255)
assert "normal layer" not in app.status_full and same(app.display_art, L.composite(app.layers, 16))
assert app.gradient_panel.winfo_ismapped() and "still paint" in app.grad_hint.cget("text")
app.undo(); pump()
print("painting on it keeps the blend (the panel stays, the hint says so)")

# 5. Type: Colours adds a gradient layer above instead; selecting a blended layer switches back to Blend
app.select_tool("gradient"); pump()
find(panel, ttk.Radiobutton, "Colours").invoke(); pump()
assert app.grad_title.cget("text") == "GRADIENT" and app._grad_rows["colours"].winfo_ismapped()
drag((0, 0), (15, 15))
assert [l.name for l in app.layers] == ["Base", "Glow", "Gradient 1"] and app.active_layer == 2
assert str(app.blend_toggle.cget("state")) == "disabled" or "disabled" in app.blend_toggle.state()
before = undo_n(); app.blend_toggle.invoke(); pump()
assert undo_n() == before and app.layers[2].fade is None, "no blend on a colour gradient layer"
app.select_layer(1); pump()
assert app.grad_mode.get() == "blend" and app.grad_title.cget("text") == "GRADIENT BLEND" and app.grad_blend_var.get()
app.undo(); pump(); app.select_layer(1); pump()
print("Colours adds a gradient layer; its toggle is off-limits; selecting 'Glow' puts the tool back on Blend")

# 6. In Blend mode the palette and X don't touch the fade
fade_before = app.layers[1].fade
x0, y0, x1, y1, rgba = app._swatches[0]
app._on_palette_click(Ev(x=x0 + 2, y=y0 + 2)); app._on_palette_right_click(Ev(x=x0 + 2, y=y0 + 2))
app.swap_gradient_colours(); app.set_gradient_colour(1, (1, 2, 3)); pump()
assert app.layers[1].fade == fade_before and app.tool_var.get() == "gradient" and app.paint_colour == rgba[:3] + (255,)
print("Blend mode: palette click only sets the paint colour; X / colour changes leave the fade alone")

# 7. Remove (button and toggle), undo
n = undo_n()
app.grad_remove_btn.invoke(); pump()
assert app.layers[1].fade is None and not app.grad_blend_var.get() and undo_n() == n + 1
assert "blend" in app.grad_title.cget("text").lower() and not app.grad_remove_btn.winfo_ismapped()
app.undo(); pump(); assert app.layers[1].fade is not None and app.grad_blend_var.get()
app.blend_toggle.invoke(); pump(); assert app.layers[1].fade is None
app.undo(); pump(); assert app.layers[1].fade is not None
print("Remove button and toggling off both remove the blend; undo brings it back")

# 8. Merge Down keeps the picture and bakes the fade into plain pixels
pic = app.display_art.copy()
app.merge_layer_down(); pump()
assert len(app.layers) == 1 and app.layers[0].fade is None and same(app.display_art, pic)
app.undo(); pump(); assert app.layers[1].fade is not None
print("merge down: same picture, fade baked")

# 9. An empty layer + Colours drag: the gradient goes into that layer (no extra layer)
app.select_layer(1); app.add_layer(); pump()
empty_name = app.layers[app.active_layer].name
app.select_tool("gradient"); app.grad_mode.set("colour"); app._on_grad_mode(); pump()
assert f"fill '{empty_name}'" in app.grad_hint.cget("text")
n_layers = len(app.layers)
drag((0, 0), (0, 15))
assert len(app.layers) == n_layers and app.layers[app.active_layer].name == empty_name
assert app.layers[app.active_layer].gradient is not None
app.undo(); app.undo(); pump(); app.select_layer(1); pump()
print(f"an empty '{empty_name}' is filled with the gradient in place")

# 10. Grid 16 -> 32: the fade is resolution-free
app.grid_var.set(32); app._settings_changed(); pump()
assert app.layers[1].fade is not None and same(app.display_art, L.composite(app.layers, 32))
app.grid_var.set(16); app._settings_changed(); pump()
print("grid 32: the blend follows")

# 11. Screenshots, nothing squashed (Blend panel + the toggle in the layers panel)
app.select_layer(1); app.select_tool("gradient"); pump()
report = []
for size in ("1140x800", "900x720"):
    root.geometry(f"{size}+40+40"); pump(0.6)
    capture(f"3_blend_panel_{size}.png")
    report.append(f"{size}: {squashed() or 'nothing squashed'}")
print("\n".join(report))
assert all("nothing squashed" in r for r in report)
root.geometry("1140x800+40+40"); pump()

# 12. Edit session: blend the texture itself (2 steps + dither = cutout-safe), Save & Return
tex = SCR / "blend_session.png"
t = Image.new("RGBA", (16, 16), (0, 0, 0, 0)); ImageDraw.Draw(t).rectangle((2, 2, 13, 13), fill=(90, 140, 60, 255)); t.save(tex)
assert app.start_session({"path": str(tex), "name": "Test", "result": None, "caller": "Grass Block"})
pump()
app.blend_toggle.invoke(); pump()
assert app.layers[0].name == "Texture" and app.layers[0].fade is not None
assert app.adjust_area.inner.pack_slaves()[0] is app.gradient_panel
drag((7, 2), (7, 13))
shown_img = app.display_art.copy()
capture("4_session_blend.png")
app.session_save()
saved = Image.open(tex).convert("RGBA")
assert same(saved, shown_img) and alphas(saved) == {0, 255}, alphas(saved)
print("edit session: the texture fades out (only fully shown / clear pixels), Save & Return wrote it")
try:
    pump(0.3)
except tk.TclError:
    pass
print("ALL OK")
