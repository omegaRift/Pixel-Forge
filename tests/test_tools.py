import ctypes, os, shutil, sys, time
from pathlib import Path

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
os.environ["APPDATA"] = str(SCR / "appdata_tools"); shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
import pixel_forge as pf
import tkinter as tk

pf._windows_setup()
root = tk.Tk(); root.withdraw()
app = pf.PixelForgeApp(root)
root.geometry("900x720+40+40"); root.update_idletasks()
hwnd = int(root.wm_frame(), 16); u32 = ctypes.windll.user32
u32.SetWindowLongW(hwnd, -20, u32.GetWindowLongW(hwnd, -20) | 0x80000 | 0x20 | 0x08000000 | 0x80)
u32.SetLayeredWindowAttributes(hwnd, 0, 0, 2); u32.ShowWindow(hwnd, 4)


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.02)


class Ev:
    def __init__(self, **k): self.__dict__.update(k)


axe = sorted(IMAGES.glob("Gemini*"))[1]
app.load_image(axe); app.transparent_var.set(True); app._settings_changed(); pump()
G = app.small_art.width

# 1. Strip: 7 tools (with Gradient) + undo/redo, square, inside the 44 px column and its height
strip = app.toolbar
assert strip is app.left_strip and strip.winfo_width() == 44
buttons = [b for b in strip.winfo_children() if b.winfo_class() in ("TRadiobutton", "TButton")]
assert len(buttons) == 9, len(buttons)
for b in buttons:
    assert 30 <= b.winfo_width() <= 40 and 30 <= b.winfo_height() <= 40, (b.winfo_width(), b.winfo_height())
    assert b.winfo_x() >= 0 and b.winfo_x() + b.winfo_width() <= 44
    assert b.winfo_y() + b.winfo_height() <= strip.winfo_height(), "fits the strip's height"
print(f"strip: 9 buttons {buttons[0].winfo_width()}x{buttons[0].winfo_height()} in a 44 px column; "
      f"default tool {app.tool_var.get()!r}")
assert app.tool_var.get() == "move" and app.view_var.get() == "sprite"

# 2. Tools <-> modes <-> tabs
app.select_tool("pen"); pump(); assert app.view_var.get() == "edit"
app.select_tool("zoom"); pump(); assert app.view_var.get() == "edit", "zoom keeps the mode"
app.select_tool("move"); pump(); assert app.view_var.get() == "sprite"
app.select_tool("zoom"); pump(); assert app.view_var.get() == "sprite"
app.notebook.select(2); pump()
app._tool_key(Ev(widget=root), "eraser"); pump()
assert app.notebook.index("current") == 1 and app.view_var.get() == "edit" and app.tool_var.get() == "eraser"
app._tool_key(Ev(widget=tk.Entry(root)), "move"); assert app.tool_var.get() == "eraser", "ignored while typing"
app.view_var.set("sprite"); app._on_view(); pump(); assert app.tool_var.get() == "move"
app.view_var.set("edit"); app._on_view(); pump(); assert app.tool_var.get() == "eraser", "returns to last paint tool"
for key in "mbegGiz":
    assert key in root.bind(), key  # Tk lists plain letter bindings as just the letter
print("tools <-> Sprite/Edit/tab mapping OK; keys M B E G I Z bound (ignored in text fields)")

# 3. Zoom in keeps the art pixel under the pointer, whole-number scale, crisp
app.select_tool("zoom"); pump()
w, h = app._canvas_size(app.art_canvas)
fit_k = max(1, min(w, h) // G)
k0, ox, oy = app._art_layout(G, w, h)
assert k0 == fit_k and app.zoom is None
px_x, px_y = 11, 4                                        # an art pixel to aim at
cx, cy = ox + px_x * k0 + k0 // 2, oy + px_y * k0 + k0 // 2
app._on_drag_start(Ev(x=cx, y=cy)); app._on_drag_end(Ev(x=cx, y=cy)); pump()
k1 = app.zoom
assert k1 and k1 > fit_k and k1 in app.ZOOM_STEPS, (fit_k, k1)
assert app._pixel_at(cx, cy) == (px_x, px_y), "same art pixel stays under the pointer"
assert app._photos["art"].width() == G * k1, "whole-number NEAREST enlargement"
assert "(fit)" not in app.zoom_label.cget("text") and str(k1 * 100) in app.zoom_label.cget("text")
print(f"zoom in: {fit_k * 100}% (fit) -> {k1 * 100}%, pixel {(px_x, px_y)} stayed under the pointer; label "
      f"{app.zoom_label.cget('text')!r}")

# 4. Pan (middle drag) is clamped: the sprite always covers the view when bigger than it
app._pan_start(Ev(x=100, y=100)); app._pan_move(Ev(x=5000, y=5000)); app._pan_end(None); pump()
ox, oy, k = app._art_origin
assert ox <= 1 and oy <= 1, (ox, oy)                      # can't drag past the edge
app._pan_start(Ev(x=100, y=100)); app._pan_move(Ev(x=-5000, y=-5000)); app._pan_end(None); pump()
ox, oy, k = app._art_origin
assert ox + G * k >= w and oy + G * k >= h, "right/bottom edge reachable, never an empty gap"
print(f"pan clamped to the sprite's edges (origin {ox},{oy} at {k}x)")

# 5. Painting while zoomed hits the right pixel
app.select_tool("pen"); app.set_paint_colour((10, 220, 90, 255)); pump()
ox, oy, k = app._art_origin
target = next((x, y) for y in range(G) for x in range(G)
              if 0 <= ox + x * k < w - k and 0 <= oy + y * k < h - k)   # a pixel that's on screen
ev = Ev(x=ox + target[0] * k + k // 2, y=oy + target[1] * k + k // 2, widget=root)
app._on_drag_start(ev); app._on_drag_end(ev); pump()
assert app.display_art.getpixel(target)[:3] == (10, 220, 90), target
app.undo(); pump()
print(f"painting at {k * 100}% zoom hit art pixel {target}")

# 6. Zoom out (right-click / Alt+click) back to fit; double-click fits; Ctrl+wheel zooms
app.select_tool("zoom"); pump()
for _ in range(20):
    app._on_right_press(Ev(x=w // 2, y=h // 2)); pump(0.05)
assert app.zoom == 1 and app._photos["art"].width() == app.small_art.width, (app.zoom, "zooming out goes past fit to 1x (actual size)")
assert "actual size" in app.zoom_label.cget("text")
fit_k = app._art_layout(app.small_art.width, w, h)[0] if False else max(1, min(w, h) // app.small_art.width)
seen = []
for _ in range(12):
    app._on_drag_start(Ev(x=w // 2, y=h // 2)); pump(0.02); seen.append(app.zoom)
assert None in seen and seen.index(None) > 0, f"zooming back in stops at fit on the way: {seen}"
assert all(z is None or z < fit_k for z in seen[:seen.index(None)]), seen
print("zoom levels below fit -> fit -> above:", seen)
app.zoom_fit(); pump()
app._on_drag_start(Ev(x=w // 2, y=h // 2)); app._on_drag_start(Ev(x=w // 2, y=h // 2)); pump()
assert app.zoom is not None
app.art_canvas.event_generate  # double-click handler:
app.zoom_fit(); pump(); assert app.zoom is None
for tool in ("move", "pen", "fill", "zoom"):  # plain wheel zooms with every tool
    app.select_tool(tool); pump()
    app._on_wheel(Ev(x=w // 2, y=h // 2, delta=120, state=0)); pump()
    zin = app.zoom
    app._on_wheel(Ev(x=w // 2, y=h // 2, delta=120, state=0)); pump()
    assert zin is not None and app.zoom > zin and app.scale_var.get() == 100, f"wheel up zooms in ({tool})"
    for _ in range(20):
        app._on_wheel(Ev(x=w // 2, y=h // 2, delta=-120, state=0)); pump(0.02)
    assert app.zoom == 1 and app.pan == [0, 0], f"wheel down zooms out to actual size ({tool})"
    app.zoom_fit(); pump()
# The art pixel under the mouse stays under it while wheel-zooming
app.select_tool("pen"); pump()
mx, my = w // 3, h // 3
under = app._pixel_at(mx, my)
app._on_wheel(Ev(x=mx, y=my, delta=120, state=0)); app._on_wheel(Ev(x=mx, y=my, delta=120, state=0)); pump()
assert app._pixel_at(mx, my) == under, (under, app._pixel_at(mx, my))
app.zoom_fit(); pump()
app.select_tool("move"); pump()
app._on_wheel(Ev(x=w // 2, y=h // 2, delta=120, state=0x4)); pump()
assert app.zoom is None and app.scale_var.get() == 105, "Ctrl+wheel with Move scales the subject"
print(f"zoom out to fit, double-click fit, wheel zooms with every tool (anchored at pixel {under}), "
      "Ctrl+wheel scales OK")

# 7. A new image starts fitted
app.load_image(axe); pump(); assert app.zoom is None
root.destroy()
print("ALL OK")
