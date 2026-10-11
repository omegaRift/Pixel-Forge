"""The real Pixel Forge window for a test, never on screen.

    from harness import *

gives a running app in an invisible window (fully transparent, click-through,
never activated: it can't take the mouse or the focus), with its settings in
a scratch APPDATA so the user's own settings and palette library are never
touched. Screenshots (capture) go to OUT.

    app, root         the PixelForgeApp and its Tk root
    pf, L             the pixel_forge and layers modules
    pump(seconds)     let the window work for a moment
    capture(name)     screenshot of the window's contents into OUT
    squashed()        visible controls given less room than they need
    Ev, at, drag      fake mouse events on the sprite, in art pixels
    find(parent, cls, text)   a widget by its label
"""

import ctypes
import ctypes.wintypes as wt
import os
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

from _paths import APP, IMAGES, SCR, TESTS

_name = Path(sys.argv[0]).stem.removeprefix("test_") or "harness"
OUT = SCR / f"{_name}_shots"
shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True)
os.environ["APPDATA"] = str(SCR / f"appdata_{_name}")  # scratch settings + palette library
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)

import pixel_forge as pf  # noqa: E402  (after APPDATA is redirected)
import layers as L  # noqa: E402
import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

pf._windows_setup()
root = tk.Tk()
root.withdraw()
app = pf.PixelForgeApp(root)
root.geometry("1140x800+40+40")
root.update_idletasks()
hwnd = int(root.wm_frame(), 16)
u32 = ctypes.windll.user32
# Layered + transparent to clicks + never activated + no taskbar button, at alpha 0:
# a real, laid-out window that PrintWindow can capture and nobody can see.
u32.SetWindowLongW(hwnd, -20, u32.GetWindowLongW(hwnd, -20) | 0x80000 | 0x20 | 0x08000000 | 0x80)
u32.SetLayeredWindowAttributes(hwnd, 0, 0, 2)
u32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def capture(name):
    root.update()
    r = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    g = ctypes.windll.gdi32
    hdc = u32.GetWindowDC(hwnd)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    g.SelectObject(mdc, bmp)
    u32.PrintWindow(hwnd, mdc, 2)

    class BMI(ctypes.Structure):
        _fields_ = [("a", wt.DWORD), ("w", wt.LONG), ("h", wt.LONG), ("p", wt.WORD), ("b", wt.WORD), ("c", wt.DWORD),
                    ("s", wt.DWORD), ("x", wt.LONG), ("y", wt.LONG), ("u", wt.DWORD), ("i", wt.DWORD)]
    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)), 0)
    g.DeleteObject(bmp)
    g.DeleteDC(mdc)
    u32.ReleaseDC(hwnd, hdc)
    full = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    ox, oy = root.winfo_rootx() - r.left, root.winfo_rooty() - r.top
    full.crop((ox, oy, ox + root.winfo_width(), oy + root.winfo_height())).save(OUT / name)


LEAF = (tk.Button, tk.Label, tk.Entry, tk.Checkbutton, tk.Radiobutton, tk.Scale, ttk.Button, ttk.Label,
        ttk.Checkbutton, ttk.Radiobutton, ttk.Scale, ttk.Combobox)


def squashed():
    """Visible controls given less room than they asked for, or outside the window."""
    out, W, H = [], root.winfo_width(), root.winfo_height()

    def walk(w):
        for c in w.winfo_children():
            if c.winfo_ismapped() and isinstance(c, LEAF):
                x = c.winfo_rootx() - root.winfo_rootx()
                y = c.winfo_rooty() - root.winfo_rooty()
                short_w, short_h = c.winfo_reqwidth() - c.winfo_width(), c.winfo_reqheight() - c.winfo_height()
                ok_w = c.winfo_class() in ("TScale", "Entry") and c.winfo_width() >= 60
                # (a control scrolled out of the sidebar's view is fine: it's inside a scrolling area)
                inside_scroll = app.adjust_area.contains(c) or app.layer_area.contains(c)
                if (short_w > 2 and not ok_w) or short_h > 2 or (not inside_scroll and (
                        x + c.winfo_width() > W + 1 or y + c.winfo_height() > H + 1)):
                    try:
                        label = c.cget("text")
                    except tk.TclError:
                        label = ""
                    out.append(f"{c.winfo_class()} '{label}' {c.winfo_width()}x{c.winfo_height()} "
                               f"(wants {c.winfo_reqwidth()}x{c.winfo_reqheight()}) at {x},{y}")
            walk(c)
    walk(root)
    return out


class Ev:
    """A stand-in for a Tk event: Ev(x=..., y=..., state=...)."""

    def __init__(self, **k):
        self.__dict__.update(k)


def at(px, py, state=0):
    """A mouse event at the centre of art pixel (px, py)."""
    ox, oy, k = app._art_origin
    return Ev(x=ox + px * k + k // 2, y=oy + py * k + k // 2, widget=root, state=state)


def drag(p0, p1, state=0):
    app._on_drag_start(at(*p0))
    app._on_drag(at(*p1, state=state))
    pump(0.1)
    app._on_drag_end(at(*p1, state=state))
    pump()


def find(parent, cls, text):
    for c in parent.winfo_children():
        if isinstance(c, cls) and str(c.cget("text")) == text:
            return c
        hit = find(c, cls, text)
        if hit is not None:
            return hit
    return None
