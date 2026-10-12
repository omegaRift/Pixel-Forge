"""The Erase Fill tool: clears the connected area of one colour on the active layer
(invisible window)."""
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
import editor_ui

pf.messagebox.askyesno = lambda *a, **k: True
pf.messagebox.showinfo = pf.messagebox.showerror = lambda *a, **k: None
CLEAR = (0, 0, 0, 0)
RED, BLUE = (200, 30, 30, 255), (30, 60, 200, 255)


def click(p, right=False):
    if right:
        app._edit_press(at(*p), erase=True); app._edit_release(at(*p))
    else:
        app._on_drag_start(at(*p)); app._on_drag_end(at(*p))
    pump(0.15)


def count(img, colour):
    return sum(1 for x in range(img.width) for y in range(img.height) if img.getpixel((x, y)) == colour)


axe = sorted(IMAGES.glob("Gemini*"))[1]
app.load_image(axe); app.transparent_var.set(True); app._settings_changed(); pump()

# 1. The tool: in the strip under Fill, with its own icon, tooltip and key (Shift+E)
names = [value for _, value, _, _ in editor_ui.TOOLS]
assert names.index("erase_fill") == names.index("fill") + 1 and "erase_fill" in editor_ui.PAINT_TOOLS
assert "erase_fill" in app._tool_buttons and app._tool_buttons["erase_fill"].winfo_ismapped() is not None
assert editor_ui.ICONS["erase_fill"] != editor_ui.ICONS["fill"] and len(editor_ui.ICONS["erase_fill"]) == 10
assert all(len(row) == 10 for row in editor_ui.ICONS["erase_fill"])
assert editor_ui.TOOL_TIPS["erase_fill"].startswith("Erase Fill (Shift+E)")
app._tool_key(Ev(widget=root), "erase_fill"); pump()
assert app.tool_var.get() == "erase_fill" and app.view_var.get() == "edit", "picking it opens the Edit view"
assert str(app.art_canvas.cget("cursor")) == "X_cursor"
app._tool_key(Ev(widget=tk.Entry(root)), "pen"); assert app.tool_var.get() == "erase_fill", "ignored while typing"
assert root.bind("<KeyPress-E>"), "Shift+E is bound"
pump()
assert app._tool_buttons["erase_fill"].winfo_ismapped()
print("Erase Fill: in the tool strip after Fill, key Shift+E, opens the Edit view")

# 2. On a paint layer: a red block with a blue square inside it. Erase Fill on the red clears
#    all of the red that is connected, and nothing else
app.add_layer(); pump()
layer = app.layers[app.active_layer]
img = layer.image
for x in range(2, 12):
    for y in range(2, 12):
        img.putpixel((x, y), BLUE if 5 <= x <= 7 and 5 <= y <= 7 else RED)
img.putpixel((14, 14), RED)                     # the same colour, but not connected
app._layers_changed(); pump()
base_before = app.layers[0].image.copy()
undo_before = len(app.history.undo_stack)
click((3, 3))
img = app.layers[app.active_layer].image
assert count(img, RED) == 1 and img.getpixel((14, 14)) == RED, "only the connected red goes"
assert count(img, BLUE) == 9, "another colour inside the area stays"
assert img.getpixel((3, 3)) == CLEAR and img.getpixel((11, 11)) == CLEAR
assert app.layers[0].image.tobytes() == base_before.tobytes(), "other layers are untouched"
assert len(app.history.undo_stack) == undo_before + 1
assert app.display_art.getpixel((3, 3)) == app.layers[0].image.getpixel((3, 3)), "the layer below shows through"
print("Erase Fill clears the connected area of one colour: 91 red pixels gone, the blue square and a stray red kept")

# 3. Undo brings it back; redo erases again
app.undo(); pump()
assert count(app.layers[app.active_layer].image, RED) == 92
app.redo(); pump()
assert count(app.layers[app.active_layer].image, RED) == 1
print("undo / redo")

# 4. Where the layer has nothing: says so, changes nothing, and adds no undo step
n = len(app.history.undo_stack)
before = app.layers[app.active_layer].image.copy()
shown = app.display_art.getpixel((3, 3))[3] > 0
click((3, 3))
assert app.layers[app.active_layer].image.tobytes() == before.tobytes() and len(app.history.undo_stack) == n
name = app.layers[app.active_layer].name
want = f"Nothing to erase there on '{name}'" + (": what you see is on another layer." if shown else ".")
assert app.status_full == want, (app.status_full, want)
print(f"an empty spot: '{app.status_full}' (no change, no undo step)")

# 5. Right click: with Fill or Erase Fill it erases the area; with the Pen, one pixel as before
app.select_tool("fill"); app.set_paint_colour(RED); pump()
click((6, 6), right=True)
img = app.layers[app.active_layer].image
assert count(img, BLUE) == 0, "right click with Fill erased the whole blue square"
click((6, 6))                                    # left click with Fill fills the hole it left... and all it connects to
img = app.layers[app.active_layer].image
assert img.getpixel((6, 6)) == RED
app.undo(); pump()
img = app.layers[app.active_layer].image
for x in range(8, 11):
    img.putpixel((x, 8), BLUE)
app._layers_changed(); pump()
app.select_tool("pen"); pump()
click((8, 8), right=True)
img = app.layers[app.active_layer].image
assert img.getpixel((8, 8)) == CLEAR and img.getpixel((9, 8)) == BLUE, "the Pen's right click still erases one pixel"
app.select_tool("erase_fill"); pump()
click((9, 8), right=True)
assert count(app.layers[app.active_layer].image, BLUE) == 0
print("right click: Fill and Erase Fill erase the area, the Pen one pixel")

# 6. On the live Base: it erases the generated sprite's area (and the Base stops regenerating, as with any edit)
app.select_layer(0); pump()
base = app.layers[0]
spot = next((x, y) for y in range(16) for x in range(16) if base.image.getpixel((x, y))[3] == 255)
colour = base.image.getpixel(spot)
had = count(base.image, colour)
click(spot)
base = app.layers[0]
assert base.image.getpixel(spot) == CLEAR and count(base.image, colour) < had and not base.live
print("on the Base layer it erases the sprite's own area too")

# 7. A hidden layer: nothing is erased
app.set_visible(0, False); pump()
before = app.layers[0].image.copy()
spot2 = next((x, y) for y in range(16) for x in range(16) if before.getpixel((x, y))[3] == 255)
click(spot2)
assert app.layers[0].image.tobytes() == before.tobytes() and "hidden" in app.status_full
app.set_visible(0, True); pump()
print("a hidden layer isn't erased")

# 8. The strip still fits at the smallest window and on a Steam Deck
for size in ("900x720", "1140x720", "1280x800"):
    root.geometry(f"{size}+40+40"); pump(0.4)
    assert not squashed(), (size, squashed())
    strip_bottom = max(b.winfo_rooty() + b.winfo_height() for b in app.toolbar.winfo_children() if b.winfo_ismapped())
    assert strip_bottom <= app.toolbar.winfo_rooty() + app.toolbar.winfo_height(), size
capture("erase_fill.png")
print("the tool strip fits at 900x720, 1140x720 and 1280x800")
print("ALL OK")
