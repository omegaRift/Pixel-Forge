"""Save Palette / the palette library in the real app (hidden windows)."""
import os
from pathlib import Path
from PIL import Image, ImageDraw

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
os.environ["PIXEL_FORGE_HIDDEN"] = "1"  # dialogs are created withdrawn
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
import palette_ui, palette_store as PS
same = lambda a, b: a.tobytes() == b.tobytes()
rgbset = lambda im: {c[:3] for _, c in im.getcolors(1 << 16) if c[3]}

ask = {"name": "Axe Reds", "yes": True}
palette_ui.simpledialog.askstring = lambda *a, **k: ask["name"]
asked = []
palette_ui.messagebox.askyesno = lambda *a, **k: asked.append(a[1]) or ask["yes"]
errors = []
palette_ui.messagebox.showerror = lambda *a, **k: errors.append(a[1])
db = Path(os.environ["APPDATA"]) / "PixelForge" / "palettes.db"
assert app.palette_store.path == db

# 0. Nothing open: nothing to save
app.save_palette(); assert "no colours" in app.status_full and not db.exists()

# 1. Save the axe's colours
test = IMAGES
axe = sorted(test.glob("Gemini*"))[1]
app.load_image(axe); app.transparent_var.set(True); app._settings_changed(); pump()
app.save_palette(); pump()
saved = app.palette_store.all()
assert [p.name for p in saved] == ["Axe Reds"] and list(saved[0].colours) == PS.colours_of(app.display_art)
assert saved[0].source == axe.name and "Saved palette 'Axe Reds'" in app.status_full
n_axe = len(saved[0].colours)
print(f"Save Palette: 'Axe Reds' with {n_axe} colours in {db.name}")

# 2. Same name again: asks; No keeps it, Yes replaces
app.layers[0].image.putpixel((0, 0), (1, 2, 3, 255)); app._freeze(app.layers[0]); app._layers_changed(); pump()
ask["yes"] = False; app.save_palette(); assert "Replace" in asked[-1] and len(app.palette_store.all()[0].colours) == n_axe
ask["yes"] = True; app.save_palette(); assert (1, 2, 3, 255) in app.palette_store.all()[0].colours
app.undo(); pump()
print("same name: asks first; No keeps the old colours, Yes replaces them")

# 3. "Another project": a different picture; open the library
other = next(p for p in test.glob("*.jpg") if not p.name.startswith("Gemini"))
app.load_image(other); pump()
app.open_palette_library(); pump()
dlg = app._lib_dialog
assert dlg.winfo_exists() and app.lib_count.cget("text") == "1 saved" and app._lib_selected == saved[0].id
assert len(app._lib_area.inner.winfo_children()) == 1
app._lib_use(); pump()
assert app.lib_strip.winfo_ismapped() and app.lib_name.cget("text") == "Axe Reds" and app._lib_swatches
assert "is open under PALETTE" in app.status_full
print(f"another project ({other.name}): the library lists it; Use shows it under PALETTE")

# 4. Paint with it; with the Gradient tool it sets the gradient colours
x0, y0, x1, y1, rgba = app._lib_swatches[1]
app._on_library_swatch(Ev(x=x0 + 2, y=y0 + 2), 0); pump()
assert app.paint_colour == rgba[:3] + (255,) and app.tool_var.get() == "pen"
app.select_tool("gradient"); pump()
x0, y0, x1, y1, rgba2 = app._lib_swatches[2]
app._on_library_swatch(Ev(x=x0 + 2, y=y0 + 2), 1); pump()
assert app._grad_template.colours[1] == rgba2[:3] + (255,)
print("library swatches: click paints (Pen), with Gradient: right-click = end colour")

# 5. Recolour the layer to it (one undo step; the live Base is frozen, then undone back to live)
n = len(app.history.undo_stack)
app._lib_recolour(); pump()
pal_rgb = {c[:3] for c in app.palette_store.all()[0].colours}
assert len(app.history.undo_stack) == n + 1 and not app.layers[0].live
assert rgbset(app.layers[0].image) <= pal_rgb, rgbset(app.layers[0].image) - pal_rgb
assert "recoloured to palette 'Axe Reds'" in app.status_full
capture("1_recoloured.png")
app.undo(); pump(); assert app.layers[0].live
print(f"Recolour Layer: every colour now from 'Axe Reds' ({len(rgbset(app.display_art))} used), undo -> live again")

# 6. Screenshots of the sidebar (strip open) and nothing squashed
report = []
for size in ("1140x800", "900x720"):
    root.geometry(f"{size}+40+40"); pump(0.6)
    capture(f"2_sidebar_{size}.png")
    report.append(f"{size}: {squashed() or 'nothing squashed'}")
print("\n".join(report)); assert all("nothing squashed" in r for r in report)
root.geometry("1140x800+40+40"); pump()

# 7. The library window itself (shown invisibly, captured, then hidden again)
dlg.update_idletasks()
dh = int(dlg.wm_frame(), 16)
u32.SetWindowLongW(dh, -20, u32.GetWindowLongW(dh, -20) | 0x80000 | 0x20 | 0x08000000 | 0x80)
u32.SetLayeredWindowAttributes(dh, 0, 0, 2); u32.ShowWindow(dh, 4); pump(0.5)
r = wt.RECT(); u32.GetWindowRect(dh, ctypes.byref(r)); w, h = r.right - r.left, r.bottom - r.top
g = ctypes.windll.gdi32; hdc = u32.GetWindowDC(dh); mdc = g.CreateCompatibleDC(hdc)
bmp = g.CreateCompatibleBitmap(hdc, w, h); g.SelectObject(mdc, bmp); u32.PrintWindow(dh, mdc, 2)
class BMI(ctypes.Structure):
    _fields_ = [("a", wt.DWORD), ("w", wt.LONG), ("h", wt.LONG), ("p", wt.WORD), ("b", wt.WORD), ("c", wt.DWORD),
                ("s", wt.DWORD), ("x", wt.LONG), ("y", wt.LONG), ("u", wt.DWORD), ("i", wt.DWORD)]
buf = ctypes.create_string_buffer(w * h * 4)
g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)), 0)
g.DeleteObject(bmp); g.DeleteDC(mdc); u32.ReleaseDC(dh, hdc)
Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB").save(OUT / "3_library.png")
squashed_dlg = [f"{c.winfo_class()} '{c.cget('text')}' {c.winfo_width()} < {c.winfo_reqwidth()}"
                for c in [b for b in app._lib_buttons.values()] if c.winfo_reqwidth() - c.winfo_width() > 2]
assert not squashed_dlg, squashed_dlg
dlg.withdraw()
print("library window captured, buttons not squashed")

# 8. Rename and delete (from the library window)
ask["name"] = "Crimson Axe"; app._lib_rename(); pump()
assert app.palette_store.all()[0].name == "Crimson Axe" and app.lib_name.cget("text") == "Crimson Axe"
ask["name"] = "Taken"; app.palette_store.save("Taken", [(5, 5, 5, 255)]); app._fill_library()
app._lib_select(next(p.id for p in app.palette_store.all() if p.name == "Crimson Axe"))
app._lib_rename(); assert errors and "already" in errors[-1]
ask["yes"] = True; app._lib_delete(); pump()
assert [p.name for p in app.palette_store.all()] == ["Taken"] and not app.lib_strip.winfo_ismapped()
app.close_palette_library(); assert app._lib_dialog is None
print("rename (taken names refused), delete (the open strip closes with it)")

# 9. In a Grass Block edit session: save the texture's palette, use the library
tex = SCR / "palette_session.png"
t = Image.new("RGBA", (16, 16), (0, 0, 0, 0)); ImageDraw.Draw(t).rectangle((3, 3, 12, 12), fill=(90, 140, 60, 255))
t.putpixel((5, 5), (200, 200, 40, 255)); t.save(tex)
assert app.start_session({"path": str(tex), "name": "Moss Block", "result": None, "caller": "Grass Block"})
pump()
ask["name"] = "Moss"; app.save_palette()
moss = next(p for p in app.palette_store.all() if p.name == "Moss")
assert moss.source == tex.name and set(moss.colours) == {(90, 140, 60, 255), (200, 200, 40, 255)}
app.open_palette_library(); app._lib_select(moss.id); app._lib_use(); pump()
assert app.lib_name.cget("text") == "Moss"
capture("4_session.png")
app.close_palette_library(); app._session_end(10)
try:
    pump(0.3)
except tk.TclError:
    pass
print("edit session: palette saved from the texture and opened from the library")
print("ALL OK")
