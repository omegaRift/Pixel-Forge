"""Screenshots at default + minimum size, and a list of squashed widgets."""
import ctypes, ctypes.wintypes as wt, os, shutil, sys, time
from pathlib import Path
from PIL import Image

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
EXPORT = SCR / "layout_export"; EXPORT.mkdir(exist_ok=True)
PHASE = sys.argv[1] if len(sys.argv) > 1 else "phase"
OUT = SCR / PHASE; shutil.rmtree(OUT, ignore_errors=True); OUT.mkdir()
os.environ["APPDATA"] = str(SCR / "appdata_phase"); shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
import pixel_forge as pf
import tkinter as tk

pf._windows_setup()
root = tk.Tk(); root.withdraw()
app = pf.PixelForgeApp(root)
root.geometry("1140x800+40+40"); root.update_idletasks()
hwnd = int(root.wm_frame(), 16); u32 = ctypes.windll.user32
u32.SetWindowLongW(hwnd, -20, u32.GetWindowLongW(hwnd, -20) | 0x80000 | 0x20 | 0x08000000)
u32.SetLayeredWindowAttributes(hwnd, 0, 0, 2); u32.ShowWindow(hwnd, 4)
pf.set_window_icons(hwnd)


def pump(sec=0.6):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.02)


def grab(name):
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
    full = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    ox, oy = root.winfo_rootx() - r.left, root.winfo_rooty() - r.top
    full.crop((ox, oy, ox + root.winfo_width(), oy + root.winfo_height())).save(OUT / name)


LEAF = (tk.Button, tk.Label, tk.Entry, tk.Checkbutton, tk.Radiobutton, tk.Scale,
        __import__("tkinter.ttk", fromlist=["x"]).Button, __import__("tkinter.ttk", fromlist=["x"]).Label,
        __import__("tkinter.ttk", fromlist=["x"]).Checkbutton, __import__("tkinter.ttk", fromlist=["x"]).Radiobutton,
        __import__("tkinter.ttk", fromlist=["x"]).Scale, __import__("tkinter.ttk", fromlist=["x"]).Combobox)


def squashed():
    """Visible controls given noticeably less room than they asked for, or
    pushed outside the window."""
    out = []
    W, H = root.winfo_width(), root.winfo_height()
    def walk(w):
        for c in w.winfo_children():
            if c.winfo_ismapped() and isinstance(c, LEAF):
                x = c.winfo_rootx() - root.winfo_rootx(); y = c.winfo_rooty() - root.winfo_rooty()
                short_w = c.winfo_reqwidth() - c.winfo_width()
                short_h = c.winfo_reqheight() - c.winfo_height()
                # a Scale (slider) is allowed to be narrower than requested if it's still >= 60 px
                slider_ok = isinstance(c, (tk.Scale,)) or c.winfo_class() == "TScale" and c.winfo_width() >= 60
                entry_ok = c.winfo_class() == "Entry" and c.winfo_width() >= 80  # designed to shrink
                if ((short_w > 2 and not slider_ok and not entry_ok) or short_h > 2 or x + c.winfo_width() > W + 1
                        or y + c.winfo_height() > H + 1):
                    label = ""
                    try: label = c.cget("text")
                    except tk.TclError: pass
                    out.append(f"{c.winfo_class()} '{label}' {c.winfo_width()}x{c.winfo_height()} (wants {c.winfo_reqwidth()}x{c.winfo_reqheight()}) at {x},{y}")
            walk(c)
    walk(root)
    return out


axe = sorted(IMAGES.glob("Gemini*"))[1]
app.load_image(axe); app.transparent_var.set(True); app._settings_changed(); app.item_name.set("Flesh Axe")
app.set_export_dir(EXPORT)  # a realistic path (scratch settings only)
report = []
for size in ("1140x800", "900x720"):
    root.geometry(f"{size}+40+40")
    for view in ("sprite", "edit", "game", "original"):
        if view == "original": app.notebook.select(0)
        else: app.view_var.set(view); app._on_view()
        if view == "edit" and len(app.layers) < 3:
            app.add_layer(); app.add_layer()
        pump()
        grab(f"{size}_{view}.png")
        issues = squashed()
        report.append(f"{size} {view}: {'OK - nothing squashed' if not issues else ''}")
        report += [f"    - {i}" for i in issues]
# Zoomed-in Edit view (Zoom tool, 2 clicks at the centre) at the default size
root.geometry("1140x800+40+40"); app.view_var.set("edit"); app._on_view(); pump()
app.select_tool("zoom"); pump()
cw, ch = app._canvas_size(app.art_canvas)
class _Ev:
    def __init__(self, **k): self.__dict__.update(k)
app._on_drag_start(_Ev(x=cw // 2, y=ch // 3)); pump(0.2)
grab("1140x800_zoomed.png"); report.append(f"zoomed shot at {app.zoom_label.cget('text')}; squashed: {squashed() or 'none'}")
root.destroy()
print("\n".join(report))
