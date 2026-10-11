import ctypes, ctypes.wintypes as wt, os, shutil, sys, time
from pathlib import Path
from PIL import Image

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
os.environ["APPDATA"] = str(SCR / "appdata_editor")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
import pixel_forge as pf
import layers as L
import tkinter as tk

pf._windows_setup()
root = tk.Tk(); root.withdraw()
app = pf.PixelForgeApp(root)
root.geometry("1140x800+40+40"); root.update_idletasks()
hwnd = int(root.wm_frame(), 16); u32 = ctypes.windll.user32
u32.SetWindowLongW(hwnd, -20, u32.GetWindowLongW(hwnd, -20) | 0x80000 | 0x20 | 0x08000000 | 0x80)
u32.SetLayeredWindowAttributes(hwnd, 0, 0, 2); u32.ShowWindow(hwnd, 4)


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.02)


def capture(name):
    root.update()
    r = wt.RECT(); u32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    g = ctypes.windll.gdi32
    hdc = u32.GetWindowDC(hwnd); mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h); g.SelectObject(mdc, bmp); u32.PrintWindow(hwnd, mdc, 2)
    class BMI(ctypes.Structure):
        _fields_ = [("a", wt.DWORD), ("w", wt.LONG), ("h", wt.LONG), ("p", wt.WORD), ("b", wt.WORD), ("c", wt.DWORD),
                    ("s", wt.DWORD), ("x", wt.LONG), ("y", wt.LONG), ("u", wt.DWORD), ("i", wt.DWORD)]
    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)), 0)
    g.DeleteObject(bmp); g.DeleteDC(mdc); u32.ReleaseDC(hwnd, hdc)
    Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB").save(SCR / name)


class Ev:
    def __init__(self, **k): self.__dict__.update(k)


def at(px, py):
    ox, oy, k = app._art_origin
    return Ev(x=ox + px * k + k // 2, y=oy + py * k + k // 2, widget=root)


def same(a, b):
    return a.tobytes() == b.tobytes()


asks = []
pf.messagebox.askyesno = lambda *a, **k: asks.append(a) or ANSWER[0]
ANSWER = [True]

axe = sorted(IMAGES.glob("Gemini*"))[1]
app.load_image(axe); app.transparent_var.set(True); app._settings_changed(); pump()

# 1. Untouched: one live Base, output identical to the generated sprite
assert len(app.layers) == 1 and app.layers[0].live and same(app.display_art, app.small_art)
print("start: 1 live Base layer, output == generated sprite")

# 2. Edit view shows toolbar + layers
app.view_var.set("edit"); app._on_view(); pump()
assert app.toolbar.winfo_ismapped() and app.layer_panel.winfo_ismapped()
assert len(app.layer_rows.winfo_children()) == 1
capture("edit_start.png")

# 3. Paint on the Base -> it freezes; settings changes no longer overwrite it
red = (220, 30, 40, 255)
app.set_paint_colour(red); app.tool_var.set("pen")
app._on_drag_start(at(0, 0)); app._on_drag_end(at(0, 0)); pump()
assert app.display_art.getpixel((0, 0)) == red and not app.layers[0].live and app.base_frozen()
frozen = app.display_art.copy()
app.scale.set(6); pump()          # change the colour limit
assert same(app.display_art, frozen) and not same(app.small_art, frozen), "frozen Base kept"
assert "Base layer is edited" in app.status_full
print("painting the Base freezes it; settings changes don't overwrite edits")

# 4. Undo -> live again (and it follows the *current* settings)
app.undo(); pump()
assert app.layers[0].live and same(app.display_art, app.small_art)
app.redo(); pump(); assert not app.layers[0].live
app.undo(); pump()
print("undo/redo OK; undoing back to a live Base shows the current settings")

# 5. New layer + a dragged stroke (no gaps), Base stays live
app.add_layer(); pump()
assert len(app.layers) == 2 and app.active_layer == 1 and app.layers[1].name == "Layer 1"
blue = (40, 60, 230, 255); app.set_paint_colour(blue)
app._on_drag_start(at(2, 2)); app._on_drag(at(9, 2)); app._on_drag(at(9, 5)); app._on_drag_end(at(9, 5)); pump()
top = app.layers[1].image
assert all(top.getpixel((x, 2)) == blue for x in range(2, 10)) and all(top.getpixel((9, y)) == blue for y in range(2, 6))
assert app.layers[0].live
print("new layer: stroke painted continuously on Layer 1; Base still live")

# 6. Blend mode + opacity
app.set_blend_mode("Multiply"); pump()
assert app.layers[1].mode == "Multiply" and same(app.display_art, L.composite(app.layers, 16))
app.opacity_scale.event_generate("<ButtonPress-1>") if False else app._snapshot()
app._on_opacity(40); pump()
assert app.layers[1].opacity == 40 and same(app.display_art, L.composite(app.layers, 16))
print("Multiply at 40% opacity composited correctly")

# 7. Settings change with a live Base + paint layer on top
before_base = app.small_art.copy()
app.scale.set(10); pump()
assert not same(app.small_art, before_base) and same(app.layers[0].image, app.small_art)
assert same(app.display_art, L.composite(app.layers, 16))
print("live Base re-generated under the paint layer")

# 8. Fill, picker, eraser (right-click)
app.set_blend_mode("Normal"); app._on_opacity(100); pump()
app.tool_var.set("fill"); app.set_paint_colour((10, 200, 90, 255))
app._on_drag_start(at(15, 15)); app._on_drag_end(at(15, 15)); pump()
filled = sum(1 for x in range(16) for y in range(16) if app.layers[1].image.getpixel((x, y)) == (10, 200, 90, 255))
assert filled > 100, filled
app.tool_var.set("picker"); app._on_drag_start(at(2, 2)); app._on_drag_end(at(2, 2))
assert app.paint_colour == blue
app.tool_var.set("pen")
app.art_canvas.event_generate  # right-click erase goes through the same handler:
app._edit_press(at(2, 2), erase=True); app._edit_release(at(2, 2)); pump()
assert app.layers[1].image.getpixel((2, 2))[3] == 0
print(f"fill ({filled} px), picker and right-click eraser OK")

# 9. Hidden layer: painting blocked
app.set_visible(1, False); pump()
before = app.layers[1].image.copy()
app._on_drag_start(at(4, 4)); app._on_drag_end(at(4, 4)); pump()
assert same(app.layers[1].image, before) and "hidden" in app.status_full
app.set_visible(1, True); pump()

# 10. Merge down keeps the picture, freezes the Base; Regenerate restores live
pic = app.display_art.copy()
app.merge_layer_down(); pump()
assert len(app.layers) == 1 and same(app.display_art, pic) and app.base_frozen()
assert str(app._layer_buttons["regen"].cget("state")) == "normal"
app.regenerate_base(); pump()
assert app.layers[0].live and same(app.display_art, app.small_art)
print("merge down preserves the picture and freezes Base; Regenerate brings it back live")

# 11. Merge visible (hidden layer kept), reorder, duplicate, delete, rename, limit
app.add_layer(); app.set_paint_colour(red); app.tool_var.set("pen")
app._on_drag_start(at(1, 1)); app._on_drag_end(at(1, 1))
app.add_layer(); app.set_visible(2, False)
app.add_layer(); app._on_drag_start(at(3, 3)); app._on_drag_end(at(3, 3)); pump()
pic = app.display_art.copy()
app.merge_visible_layers(); pump()
assert [l.name for l in app.layers] == ["Merged", "Layer 2"] and same(app.display_art, pic)
app.select_layer(1); app.move_layer_down(); pump(); assert app.layers[0].name == "Layer 2"
app.duplicate_layer(); pump(); assert app.layers[1].name == "Layer 2 copy"
app.delete_layer(); pump(); assert len(app.layers) == 2
pf.simpledialog if False else None
import editor_ui; editor_ui.simpledialog.askstring = lambda *a, **k: "Shading"
app.rename_layer(0); pump(); assert app.layers[0].name == "Shading"
while len(app.layers) < L.MAX_LAYERS: app.add_layer()
app.add_layer(); assert len(app.layers) == L.MAX_LAYERS
assert str(app._layer_buttons["add"].cget("state")) == "disabled"
print("merge visible, reorder, duplicate, delete, rename and the 8-layer limit OK")
for _ in range(20): app.undo()
pump()

# 12. Grid 16 -> 32 rescales painted layers
app.add_layer(); app._on_drag_start(at(5, 5)); app._on_drag_end(at(5, 5)); pump()
app.grid_var.set(32); app._settings_changed(); pump()
assert all(l.image.size == (32, 32) for l in app.layers) and app.layers[-1].image.getpixel((11, 11))[3]
print("grid change rescales painted layers")

# 13. Saving and the in-game preview use the composite
out = SCR / "edit_export"; shutil.rmtree(out, ignore_errors=True); out.mkdir()
app.set_export_dir(out); app.item_name.set("Edited Axe"); pump()
app.save_dialog(raw=True)
saved = Image.open(out / "edited_axe.png").convert("RGBA")
assert same(saved, app.display_art) and not same(saved, app.small_art)
print("Save Sprite writes the combined layers")
app.clear_export_dir()

# 14. Keyboard tool keys ignore text fields
app._tool_key(Ev(widget=root), "fill"); assert app.tool_var.get() == "fill"
app._tool_key(Ev(widget=tk.Entry(root)), "pen"); assert app.tool_var.get() == "fill"
assert "<Control-Key-z>" in root.bind() and "<Control-Key-y>" in root.bind()
print("tool keys work, but not while typing a name")

app.grid_var.set(16); app._settings_changed(); pump()
app.set_blend_mode("Overlay"); pump()
capture("edit_layers.png")

# 15. Opening another image with edits asks first
ANSWER[0] = False; n = len(asks)
assert app.load_image(axe) is False and len(asks) == n + 1 and len(app.layers) > 1
ANSWER[0] = True
assert app.load_image(axe) and len(app.layers) == 1 and app.layers[0].live and not app.history.undo_stack
print("opening another image asks before discarding layers")
root.destroy()
print("ALL OK")
