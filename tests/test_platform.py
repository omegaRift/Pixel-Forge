"""platform_support: the parts that differ between Windows and Linux (the Steam Deck).
Runs on both; on Linux it needs a display (xvfb-run)."""
import os
import sys
import tempfile
import tkinter as tk
from pathlib import Path

from _paths import APP, SCR  # (this also puts the app on sys.path)
import platform_support as ps

# 1. Settings folder: APPDATA wins wherever it's set; else XDG / ~/.config on Linux
saved = {k: os.environ.pop(k, None) for k in ("APPDATA", "XDG_CONFIG_HOME")}
try:
    os.environ["APPDATA"] = str(SCR / "appdata_platform")
    assert ps.config_dir() == SCR / "appdata_platform" / "PixelForge"
    del os.environ["APPDATA"]
    if ps.WINDOWS:
        assert ps.config_dir() == Path.home() / "PixelForge"
    else:
        assert ps.config_dir() == Path.home() / ".config" / "PixelForge"
        os.environ["XDG_CONFIG_HOME"] = str(SCR / "xdg")
        assert ps.config_dir() == SCR / "xdg" / "PixelForge"
finally:
    for k, v in saved.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v
os.environ["APPDATA"] = str(SCR / "appdata_platform")
import palette_store, pixel_forge as pf  # noqa: E402
assert pf.settings_file() == ps.config_dir() / "settings.json"
assert palette_store.default_path() == ps.config_dir() / "palettes.db"
print("settings folder:", "APPDATA wins; otherwise", "home" if ps.WINDOWS else "XDG_CONFIG_HOME or ~/.config")

# 2. Bundled fonts: only on Linux, only when the app carries a fonts folder
with tempfile.TemporaryDirectory() as tmp:
    before = os.environ.get("FONTCONFIG_FILE")
    assert ps.use_bundled_fonts(Path(tmp)) is False, "no fonts folder: nothing to do"
    (Path(tmp) / "fonts").mkdir()
    used = ps.use_bundled_fonts(Path(tmp))
    assert used is (not ps.WINDOWS and sys.platform != "darwin")
    if used:
        conf = Path(os.environ["FONTCONFIG_FILE"])
        assert conf.parent == Path(tmp) / "fonts" and str(Path(tmp) / "fonts") in conf.read_text()
        assert "/etc/fonts/fonts.conf" in conf.read_text(), "the system's fonts stay available"
    os.environ.pop("FONTCONFIG_FILE", None)
    if before is not None:
        os.environ["FONTCONFIG_FILE"] = before
print("bundled fonts:", "used on Linux when present" if not ps.WINDOWS else "not used on Windows")

# 3. Mouse wheel: one handler, delta > 0 = up, whatever the system sends
root = tk.Tk()
root.withdraw()
x11 = root.tk.call("tk", "windowingsystem") == "x11"
canvas = tk.Canvas(root)
seen = []
ps.bind_wheel(canvas, lambda e: seen.append(e.delta) or "break")
assert "<MouseWheel>" in canvas.bind()
assert ("<Button-4>" in canvas.bind() and "<Button-5>" in canvas.bind()) == x11
if x11:  # Tk 8.6 on X11 turns the wheel into buttons 4 (up) and 5 (down)
    canvas.pack(); root.deiconify(); root.update()
    canvas.event_generate("<Button-4>", x=5, y=5); canvas.event_generate("<Button-5>", x=5, y=5); root.update()
    assert seen == [120, -120], seen
ps.bind_wheel(root, lambda e: None, everywhere=True, add="+")
assert "<MouseWheel>" in root.bind_all()
print("mouse wheel:", "buttons 4/5 give delta +120/-120" if x11 else "<MouseWheel> (this system sends it itself)")

# 4. The window fits the screen (a Steam Deck is 1280x800)
top = tk.Toplevel(root)
top.withdraw()
ps.fit_window(top, 1140, 800, 900, 720)
top.update_idletasks()
w, h = (int(v) for v in top.geometry().split("+")[0].split("x"))
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
assert w == min(1140, sw - 20) and h == min(800, sh - 80), (w, h, sw, sh)
assert top.minsize() == (min(900, w), min(720, h))
huge = tk.Toplevel(root)
huge.withdraw()
ps.fit_window(huge, 5000, 5000, 4000, 4000)  # asking for more than any screen has
huge.update_idletasks()
w2, h2 = (int(v) for v in huge.geometry().split("+")[0].split("x"))
assert (w2, h2) == (sw - 20, sh - 80) and huge.minsize() == (w2, h2), (w2, h2, huge.minsize())
print(f"window: {w}x{h} on this {sw}x{sh} screen; never bigger than the screen has room for")

# 5. Opening a folder never raises
assert ps.open_folder(SCR / "no-such-folder-xyz") in (True, False)
root.destroy()
print("ALL OK")
