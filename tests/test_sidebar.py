import ctypes, os, shutil, sys, time
from pathlib import Path

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
os.environ["APPDATA"] = str(SCR / "appdata_sidebar"); shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
import pixel_forge as pf
import layers as L
import tkinter as tk

pf._windows_setup()
root = tk.Tk(); root.withdraw()
app = pf.PixelForgeApp(root)
root.geometry("900x720+40+40"); root.update_idletasks()
hwnd = int(root.wm_frame(), 16); u32 = ctypes.windll.user32
u32.SetWindowLongW(hwnd, -20, u32.GetWindowLongW(hwnd, -20) | 0x80000 | 0x20 | 0x08000000 | 0x80)
u32.SetLayeredWindowAttributes(hwnd, 0, 0, 2); u32.ShowWindow(hwnd, 4)


def pump(sec=0.4):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.02)


class Ev:
    def __init__(self, **k): self.__dict__.update(k)


def wheel_over(widget, delta):
    """Fake a wheel event with the pointer over `widget` (like the real one)."""
    x, y = widget.winfo_rootx() + 5, widget.winfo_rooty() + 5
    real = root.winfo_containing
    root.winfo_containing = lambda *a: widget   # the hidden window can't be hit-tested reliably
    try:
        app._on_global_wheel(Ev(x_root=x, y_root=y, delta=delta))
    finally:
        root.winfo_containing = real


axe = sorted(IMAGES.glob("Gemini*"))[1]
app.load_image(axe); app.transparent_var.set(True); app._settings_changed(); pump()

# 1. Stack order and everything inside the 300 px sidebar
side = app.right_sidebar
y = lambda w: w.winfo_rooty() - side.winfo_rooty()
assert y(app.palette_canvas) < y(app.adjust_area) < y(app.layer_panel), "palette / adjustments / layers"
assert side.winfo_width() == 300
bottom = y(app.layer_panel) + app.layer_panel.winfo_height()
assert bottom <= side.winfo_height(), ("layers fully visible", bottom, side.winfo_height())
assert app.layer_panel.winfo_ismapped() and app.view_var.get() == "sprite", "layers visible in Sprite view too"
print(f"stack OK at 900x720: palette y={y(app.palette_canvas)}, adjustments y={y(app.adjust_area)} "
      f"(h={app.adjust_area.winfo_height()}), layers y={y(app.layer_panel)}..{bottom} of {side.winfo_height()}")

# 2. Adjustments scroll at the minimum height; the wheel scrolls them only when hovered
area = app.adjust_area
assert area.scrollable, "content taller than the space at 720 px -> scrollbar"
first = area.canvas.yview()
wheel_over(app.size_scale, -120); pump(0.1)            # wheel down over the Scale slider (inside)
after = area.canvas.yview()
assert after[0] > first[0], (first, after)
wheel_over(app.art_canvas, -120); pump(0.1)            # over the sprite: not the sidebar's business
assert area.canvas.yview() == after
for _ in range(40): wheel_over(app.size_scale, -120)
pump(0.1); assert abs(area.canvas.yview()[1] - 1.0) < 1e-6, "scrolls to the very end (Move row reachable)"
for _ in range(40): wheel_over(app.size_scale, 120)
pump(0.1); assert area.canvas.yview()[0] == 0.0
print(f"adjustments scroll: view {first} -> {after}, reaches the end and back; sprite wheel untouched")

# 3. At the default size nothing needs to scroll... or less of it
root.geometry("1140x800+40+40"); pump()
print(f"at 1140x800: adjustments height {area.winfo_height()}, content {area.inner.winfo_reqheight()}, "
      f"scrollbar {'shown' if area.scrollable else 'hidden'}")
root.geometry("900x720+40+40"); pump()

# 4. Layers list: up to 5 rows visible, the rest scroll; the selected row is shown
while len(app.layers) < L.MAX_LAYERS:
    app.add_layer()
pump()
rows = app.layer_rows.winfo_children()
assert len(rows) == 8 and app.layer_area.scrollable
visible_h = app.layer_area.canvas.winfo_height()
five = sum(r.winfo_height() + 2 for r in rows[:5])
assert abs(visible_h - five) <= 2, (visible_h, five)
app.select_layer(0); pump()                             # Base: the last row, below the fold
base_row = app.layer_rows.winfo_children()[-1]
view_top = app.layer_area.canvas.canvasy(0)
assert view_top <= base_row.winfo_y() and base_row.winfo_y() + base_row.winfo_height() <= view_top + visible_h + 1
bottom = y(app.layer_panel) + app.layer_panel.winfo_height()
assert bottom <= side.winfo_height() and area.winfo_height() >= 100, (bottom, area.winfo_height())
print(f"8 layers: {visible_h}px list (5 rows), scrolls; selected Base scrolled into view; adjustments keep "
      f"{area.winfo_height()}px")

# 5. Palette swatch click from Sprite view -> paint with it (Edit, Pen)
for _ in range(7): app.select_layer(len(app.layers) - 1); app.delete_layer()
app.view_var.set("sprite"); app._on_view(); pump()
x0, y0, x1, y1, rgba = app._swatches[0]
app._on_palette_click(Ev(x=(x0 + x1) // 2, y=(y0 + y1) // 2)); pump()
assert app.paint_colour[:3] == rgba[:3] and app.tool_var.get() == "pen" and app.view_var.get() == "edit"
assert app.notebook.index("current") == 1
print("palette click from Sprite view -> Edit + Pen with that colour")
root.destroy()
print("ALL OK")
