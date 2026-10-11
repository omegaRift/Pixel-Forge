"""The Gradient tool and gradient layers in the real app (hidden window)."""
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...

same = lambda a, b: a.tobytes() == b.tobytes()
near = lambda v, px: abs(v - (px + 0.5) / 16) <= 1 / (16 * app._art_origin[2]) + 1e-9  # within one screen pixel of the centre
undo_n = lambda: len(app.history.undo_stack)
alpha = lambda im: im.getchannel("A").tobytes()

axe = sorted(IMAGES.glob("Gemini*"))[1]
app.load_image(axe); app.transparent_var.set(True); app._settings_changed(); pump()
bg = next((x, y) for y in range(16) for x in range(16) if app.small_art.getpixel((x, y))[3] == 0)
opaque = [(x, y) for y in range(16) for x in range(16) if app.small_art.getpixel((x, y))[3] == 255]

# 1. The tool: strip button, Shift+G, Edit mode, panel at the top of the Adjustments area
assert "gradient" in app._tool_buttons and "G" in root.bind()
app._tool_key(Ev(widget=root), "gradient"); pump()
assert app.tool_var.get() == "gradient" and app.view_var.get() == "edit"
assert app.gradient_panel.winfo_ismapped() and app.adjust_area.inner.pack_slaves()[0] is app.gradient_panel
assert "Gradient" in app.status_full and "add a gradient layer" in app.grad_hint.cget("text")
assert app.grad_target.cget("text") == "new layer" and app.grad_fade.get() and app.grad_clip.get()
print("Gradient tool: Shift+G, Edit mode, GRADIENT panel shown at the top, hint in the status bar")

# 2. A click without dragging does nothing
n = undo_n()
app._on_drag_start(at(2, 8)); app._on_drag_end(at(2, 8)); pump()
assert len(app.layers) == 1 and undo_n() == n and "drag across" in app.status_full
print("a click alone adds nothing (and says to drag)")

# 3. Drag left -> right: a new clipped gradient layer, on the sprite only
base_pic = app.display_art.copy()
drag((0, 8), (15, 8))
assert [l.name for l in app.layers] == ["Base", "Gradient 1"] and app.active_layer == 1 and undo_n() == n + 1
g = app.layers[1].gradient
assert g is not None and app.layers[1].clip and near(g.start[0], 0) and near(g.end[0], 15)
assert alpha(app.display_art) == alpha(app.small_art), "clipped: the sprite's shape, exactly"
assert app.display_art.getpixel(bg)[3] == 0 and not same(app.display_art, base_pic)
assert app.layers[0].live, "the Base stays live under a gradient"
assert app.art_canvas.find_withtag("guide"), "direction guide drawn"
assert app.grad_target.cget("text") == "Gradient 1" and "re-aim" in app.grad_hint.cget("text")
capture("1_new_gradient.png")
print(f"drag added 'Gradient 1' (clipped, alpha == sprite alpha, background pixel {bg} still clear), guide shown")

# 4. Dragging again re-aims it (no new layer); undo/redo
drag((8, 0), (8, 15))
g2 = app.layers[1].gradient
assert len(app.layers) == 2 and near(g2.start[1], 0) and near(g2.end[1], 15)
app.undo(); pump(); assert app.layers[1].gradient == g
app.undo(); pump(); assert len(app.layers) == 1
app.redo(); app.redo(); pump(); assert app.layers[1].gradient == g2 and app.active_layer == 1
print("re-aimed vertically; undo -> horizontal -> no layer; redo x2 back")

# 5. Panel settings: each change is one undo step, applied to the layer
def step(action, check, label):
    before = undo_n(); action(); pump(0.1)
    assert undo_n() == before + 1, (label, undo_n() - before)
    assert check(app.layers[1]), label
    assert same(app.layers[1].image, L.render_gradient(app.layers[1].gradient, 16)), label
    assert same(app.display_art, L.composite(app.layers, 16)), label

panel = app.gradient_panel
step(lambda: find(panel, ttk.Radiobutton, "Radial").invoke(), lambda l: l.gradient.shape == "radial", "shape")
def steps_drag():
    app._grad_sliders["steps"].update(down=True, saved=False)
    app._on_grad_steps(5); app._on_grad_steps(6.4); app._on_grad_steps(7)
    app._grad_sliders["steps"].update(down=False)
step(steps_drag, lambda l: l.gradient.steps == 7 and app.grad_steps_label.cget("text") == "7", "steps (one drag)")
step(lambda: find(panel, ttk.Checkbutton, "Dither").invoke(), lambda l: l.gradient.dither, "dither")
step(lambda: find(panel, ttk.Checkbutton, "Fade to transparent").invoke(),
     lambda l: l.gradient.colours[1][3] == 255 and not app.grad_fade.get(), "fade off")
pf.colorchooser.askcolor = lambda **k: ((200, 40, 40), "#c82828")
step(lambda: app.pick_gradient_colour(1), lambda l: l.gradient.colours[1] == (200, 40, 40, 255), "end colour")
assert app.grad_swatches[1].cget("bg") == "#c82828"
start_before = app.layers[1].gradient.colours[0]
step(lambda: find(panel, ttk.Button, "Swap").invoke(),
     lambda l: l.gradient.colours == ((200, 40, 40, 255), start_before), "swap")
step(lambda: find(panel, ttk.Checkbutton, "Only on the sprite").invoke(),
     lambda l: not l.clip and app.display_art.getpixel(bg)[3] > 0, "clip off")
step(lambda: find(panel, ttk.Checkbutton, "Only on the sprite").invoke(),
     lambda l: l.clip and app.display_art.getpixel(bg)[3] == 0, "clip on")
assert app._grad_template.shape == "radial" and app._grad_template.steps == 7, "the next gradient starts like this one"
capture("2_radial_dither.png")
print("shape, steps (1 undo step per drag), dither, fade, colour, swap, clip: each 1 undo step, rendered + composited")

# 6. Selecting layers shows / hides the panel
app.select_layer(0); pump()
assert app.gradient_panel.winfo_ismapped() and app.grad_target.cget("text") == "new layer"
app.select_tool("pen"); pump()
assert not app.gradient_panel.winfo_ismapped()
app.select_layer(1); pump()
assert app.gradient_panel.winfo_ismapped() and app.grad_shape.get() == "radial" and app.grad_steps.get() == 7
assert "Painting on it" in app.grad_hint.cget("text")
print("panel: shown for the tool or a selected gradient layer, hidden otherwise, filled from the layer")

# 7. Palette clicks with the Gradient tool set its colours (and keep the tool)
app.select_tool("gradient"); pump()
x0, y0, x1, y1, rgba = app._swatches[0]
app._on_palette_click(Ev(x=x0 + 2, y=y0 + 2))
assert app.tool_var.get() == "gradient" and app.layers[1].gradient.colours[0] == rgba[:3] + (255,)
x0, y0, x1, y1, rgba2 = app._swatches[1]
app._on_palette_right_click(Ev(x=x0 + 2, y=y0 + 2))
assert app.layers[1].gradient.colours[1] == rgba2[:3] + (255,)
print("palette: click = start colour, right-click = end colour, tool stays Gradient")

# 8. Right-click with the Gradient tool doesn't erase; X swaps
n, pic = undo_n(), app.display_art.copy()
app._on_right_press(at(8, 8)); app._edit_release(at(8, 8)); pump()
assert undo_n() == n and same(app.display_art, pic)
assert "x" in root.bind()
c0, c1 = app.layers[1].gradient.colours
root.event_generate  # (the binding calls this:)
app.swap_gradient_colours(); pump(); assert app.layers[1].gradient.colours == (c1, c0)
print("right-click with Gradient: nothing; X swaps")

# 9. Shift snaps to 45 degrees
app._on_drag_start(at(2, 2)); app._on_drag(at(12, 5, state=1)); pump(0.1); app._on_drag_end(at(12, 5, state=1)); pump()
g = app.layers[1].gradient
assert abs(g.end[1] - g.start[1]) < 1e-9 and g.end[0] > g.start[0], g
print(f"Shift: (2,2)->(12,5) snapped to horizontal, end {tuple(round(v, 3) for v in g.end)}")

# 10. Painting on it: becomes normal pixels (clip baked), Undo brings the gradient back
app.select_tool("pen"); app.set_paint_colour((10, 200, 90, 255))
pic = app.display_art.copy()
px_on = opaque[len(opaque) // 2]
app._on_drag_start(at(*px_on)); app._on_drag_end(at(*px_on)); pump()
lay = app.layers[1]
assert lay.gradient is None and not lay.clip and lay.image.getpixel(bg)[3] == 0 and "normal layer" in app.status_full
diff = [(x, y) for y in range(16) for x in range(16) if app.display_art.getpixel((x, y)) != pic.getpixel((x, y))]
assert diff == [px_on], diff
app.undo(); pump(); assert app.layers[1].gradient is not None and app.layers[1].clip and same(app.display_art, pic)
print(f"painting turned it into pixels (only the painted pixel changed), undo restored the gradient")

# 11. Grid 16 -> 32: the gradient is redrawn and still follows the (live) sprite
app.grid_var.set(32); app._settings_changed(); pump()
lay = app.layers[1]
assert lay.image.size == (32, 32) and same(lay.image, L.render_gradient(lay.gradient, 32))
assert alpha(app.display_art) == alpha(app.small_art)
app.grid_var.set(16); app._settings_changed(); pump()
print("grid 32: gradient redrawn at 32 and clipped to the new sprite")

# 12. Merge Down bakes it into the Base
pic = app.display_art.copy()
app.merge_layer_down(); pump()
assert len(app.layers) == 1 and app.layers[0].gradient is None and same(app.display_art, pic) and app.base_frozen()
app.undo(); pump(); assert len(app.layers) == 2 and app.layers[1].gradient is not None
print("merge down: same picture, plain pixels in the Base")

# 13. The 8-layer limit
app.select_layer(0)
while len(app.layers) < L.MAX_LAYERS:
    app.add_layer()
app.select_layer(0); app.select_tool("gradient"); pump()
n = len(app.layers)
drag((0, 0), (15, 15))
assert len(app.layers) == n and "8 layers" in app.status_full
for _ in range(L.MAX_LAYERS - 2): app.undo()
pump(); assert len(app.layers) == 2
print("8 layers: no new gradient layer, and it says why")

# 14. Screenshots + nothing squashed, at both sizes, with the panel showing
app.select_layer(1); app.select_tool("gradient"); pump()
report = []
for size in ("1140x800", "900x720"):
    root.geometry(f"{size}+40+40"); pump(0.6)
    capture(f"3_panel_{size}.png")
    report.append(f"{size}: {squashed() or 'nothing squashed'}")
print("\n".join(report))
assert all("nothing squashed" in r for r in report)
root.geometry("1140x800+40+40"); pump()

# 15. Palette is capped at PALETTE_ROWS rows; the rest are counted
many = Image.effect_noise((32, 32), 90).convert("RGBA")
app.layers[1] = L.Layer("Noise", many); app._layers_changed(); pump()
rows = {y0 for _, y0, _, _, _ in app._swatches}
assert len(rows) <= app.PALETTE_ROWS and app.palette_more.cget("text").startswith("+"), (len(rows), app.palette_more.cget("text"))
app.undo(); pump()
print(f"palette capped at {len(rows)} rows ('{app.palette_more.cget('text') or 'nothing'}' now)")

# 16. In a Grass Block edit session: works on the texture, Save & Return writes the composite
tex = SCR / "gradient_session.png"
t = Image.new("RGBA", (16, 16), (0, 0, 0, 0)); ImageDraw.Draw(t).rectangle((3, 3, 12, 12), fill=(90, 140, 60, 255)); t.save(tex)
assert app.start_session({"path": str(tex), "name": "Test", "result": None, "caller": "Grass Block"})
pump()
app.select_tool("gradient"); pump()
assert app.adjust_area.inner.pack_slaves()[0] is app.gradient_panel, "above the TEXTURE note"
drag((3, 3), (12, 12))
assert [l.name for l in app.layers] == ["Texture", "Gradient 1"]
shown = app.display_art.copy()
capture("4_session.png")
app.session_save()
saved = Image.open(tex).convert("RGBA")
assert same(saved, shown) and saved.getpixel((0, 0))[3] == 0 and app.exit_code == 0
print("edit session: gradient on the texture, Save & Return wrote exactly what was shown")
try:
    pump(0.3)
except tk.TclError:
    pass
print("ALL OK")
