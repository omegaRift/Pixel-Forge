import sys
if sys.platform != "win32":
    print("SKIPPED: this suite drives Windows-only window calls (the rest cover the same app on Linux)")
    raise SystemExit(0)
import ctypes, ctypes.wintypes as wt, json, sys, time
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
# Keep the app's remembered settings inside the scratch folder, never the
# user's real %APPDATA%\PixelForge\settings.json.
import os, shutil
TEST_APPDATA = str(SCR / "appdata_desktop")
shutil.rmtree(TEST_APPDATA, ignore_errors=True)
os.environ["APPDATA"] = TEST_APPDATA
import pixel_forge as pf
assert str(pf.settings_file()).startswith(TEST_APPDATA)
import tkinter as tk

OUT = SCR / "desktop_shots"; OUT.mkdir(exist_ok=True)

# Transparent-background test image with shapes (wide, to show the crop box)
src = Image.new("RGBA", (900, 600), (0, 0, 0, 0))
d = ImageDraw.Draw(src)
for x in range(900):
    d.line([(x, 80), (x, 520)], fill=(x * 255 // 900, 90, 255 - x * 255 // 900, 255))
d.ellipse((300, 150, 600, 450), fill=(255, 220, 0, 255))
d.rectangle((400, 250, 500, 350), fill=(20, 20, 20, 255))
src.save(OUT / "desk_src.png")


def pump(sec=0.4):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.02)


def capture(name):
    """Read-only PrintWindow capture of our own (off-screen) window."""
    root.update()
    hwnd = int(root.wm_frame(), 16)
    r = wt.RECT(); ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    hdc = u.GetWindowDC(hwnd); mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h); g.SelectObject(mdc, bmp)
    u.PrintWindow(hwnd, mdc, 2)
    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
    bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    g.DeleteObject(bmp); g.DeleteDC(mdc); u.ReleaseDC(hwnd, hdc)
    Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB").save(OUT / name)
    print("captured", name, w, h)


pf._windows_setup()
root = tk.Tk()
root.withdraw()
app = pf.PixelForgeApp(root)
root.geometry("1140x800+40+40")
root.update_idletasks()
# Invisible (alpha 0), click-through, never activated, no taskbar button:
# Tk still paints it, but the user never sees it or loses focus to it.
hwnd = int(root.wm_frame(), 16)
GWL_EXSTYLE, LAYERED, TRANSPARENT, NOACTIVATE, TOOL = -20, 0x80000, 0x20, 0x08000000, 0x80
u32 = ctypes.windll.user32
u32.SetWindowLongW(hwnd, GWL_EXSTYLE, u32.GetWindowLongW(hwnd, GWL_EXSTYLE) | LAYERED | TRANSPARENT | NOACTIVATE | TOOL)
u32.SetLayeredWindowAttributes(hwnd, 0, 0, 2)   # LWA_ALPHA, alpha 0
u32.ShowWindow(hwnd, 4)                          # SW_SHOWNOACTIVATE
pump()
capture("desk_empty.png")

TEST = IMAGES
axe = sorted(TEST.glob("Gemini*"))[1]
assert app.load_image(axe)
pump()
# New defaults: 16x16, 10 colours, clean-up on, detail 30
assert app.small_art.size == (16, 16) and app.colors_label.cget("text") == "10"
assert app.enhance_var.get() and app.detail_var.get() == 30
ref = pdet_default = __import__("pixel_core").pixelate_detailed(
    app.original, 16, 10, outline="outside", detail=30, fit_subject=True, enhance=True)
assert ref.small.tobytes() == app.small_art.tobytes()
n_on = len(app.small_art.getcolors(256)); assert n_on <= 10
capture("desk_default16.png")
app.enhance_var.set(False); app._settings_changed(); pump()
assert ref.small.tobytes() != app.small_art.tobytes(), "toggle changes output"
print(f"defaults OK: 16x16, 10 colours ({n_on} used), clean-up on; toggle off changes output")

# ---- Phase 2 shell: tabs, one-line status, Match Original on the tab row ----
shown = app.status.cget("text")
assert "\n" not in shown and pf.tkfont.Font(font=pf.FONT).measure(shown) <= app.status.winfo_width()
assert "\n" in app.status_full or shown == app.status_full  # full text kept for the tooltip
assert app.notebook.index("current") == 1                   # Pixel Art tab by default
app.notebook.select(0); pump(); assert app.view_var.get() == "sprite"    # Original: view unchanged
app.notebook.select(2); pump(); assert app.view_var.get() == "game"
app.notebook.select(1); pump(); assert app.view_var.get() == "sprite"
app.view_var.set("game"); app._on_view(); pump(); assert app.notebook.index("current") == 2
app.view_var.set("sprite"); app._on_view(); pump(); assert app.notebook.index("current") == 1
mb = app.match_btn
assert mb.winfo_width() >= mb.winfo_reqwidth() and mb.winfo_y() == 0, "Match Original on the tab row, full width"
print(f"tabs <-> view_var OK; status one line ('{shown[:40]}...'); Match Original {mb.winfo_width()}px on the tab row")

# ---- Match Original ----
app.enhance_var.set(True); app._settings_changed(); pump()
assert str(app.match_btn.cget("state")) == "normal" and app.match_btn.cget("text") == "Match Original"
live = app.small_art.copy()
def wait_match(limit=30):
    t0 = time.time(); ticks = 0
    while app._match_job is not None and time.time() - t0 < limit:
        root.update(); time.sleep(0.01); ticks += 1
    pump(0.2)
    return time.time() - t0, ticks
app.match_original(); dt, ticks = wait_match()
core = __import__("pixel_core").pixelate_detailed(app.original, 16, 10, outline="outside", detail=30,
                                                 fit_subject=True, enhance=True, match_source=True)
assert app.small_art.tobytes() == core.small.tobytes(), "UI shows the core's matched result"
assert app.small_art.tobytes() != live.tobytes()
assert app.match_btn.cget("text") == "Matched ✓" and str(app.match_btn.cget("state")) == "disabled"
assert "Matched to the original" in app.status_full
print(f"match 16x16: {dt * 1000:.0f} ms (UI loop ran {ticks}x meanwhile); button -> Matched")
capture("desk_matched.png")
# any change -> back to live preview, button re-enabled
app.nudge(1, 0); pump()
assert app.match_btn.cget("text") == "Match Original" and "Matched" not in app.status_full
# back to the same settings -> the match is shown again instantly
app.nudge(-1, 0); pump()
assert app.small_art.tobytes() == core.small.tobytes() and app.match_btn.cget("text") == "Matched ✓"
print("changing a setting returns to live; returning restores the match")
# 32x32 via Ctrl+M, UI stays responsive
app.grid_var.set(32); app._settings_changed(); pump()
assert "<Control-Key-m>" in app.root.bind(); app.match_original(); pump(0.05)  # the Ctrl+M binding's action
assert app._match_job is not None or app.match_btn.cget("text") == "Matched ✓"
dt, ticks = wait_match()
assert app.match_btn.cget("text") == "Matched ✓"
print(f"match 32x32 via Ctrl+M: {dt * 1000:.0f} ms, UI loop ran {ticks}x meanwhile")
app.grid_var.set(16); app._settings_changed(); pump()
# ---- Minecraft in-game preview ----
import mc_preview
assert app.item_name.get() == mc_preview.pretty_name(axe.stem)
app.view_var.set("game"); app._on_view(); pump()
texts = [app.game_canvas.itemcget(i, "text") for i in app.game_canvas.find_all() if app.game_canvas.type(i) == "text"]
assert any("Transparent BG" in t for t in texts), "tip shown for an opaque sprite"
assert app.palette_canvas.winfo_ismapped() and app.name_row.winfo_ismapped()  # palette lives in the sidebar now: always visible
cw, ch = app._canvas_size(app.game_canvas)
gk, gc, gr = mc_preview.best_fit(cw, ch - 34, app.small_art.width)
mock = mc_preview.render_inventory(app.small_art, app.item_name.get(), cols=gc, rows=gr)
pw = app._photos["game"].width(); assert pw == mock.width * gk, (pw, mock.width, gk)
assert gk >= 2, "icon shown at a realistic GUI scale"
print(f"in-game preview: GUI scale {gk}x, {gc}x{gr} slots, canvas {cw}x{ch}; tip shown for opaque sprite")
app.item_name.set("Flesh Axe"); pump(); capture("desk_export_set.png")
before = (app.scale_var.get(), list(app.offset))

class Ev2:
    def __init__(self, **k): self.__dict__.update(k)
app._on_wheel(Ev2(x=10, y=10, delta=120)); app._on_drag_start(Ev2(x=10, y=10)); app._on_drag(Ev2(x=200, y=10)); app._on_drag_end(None); pump()
assert (app.scale_var.get(), list(app.offset)) == before, "wheel/drag disabled in the in-game view"
app.transparent_var.set(True); app._settings_changed(); pump()
texts = [app.game_canvas.itemcget(i, "text") for i in app.game_canvas.find_all() if app.game_canvas.type(i) == "text"]
assert not any("Transparent BG" in t for t in texts)
capture("desk_game.png")
app.view_var.set("sprite"); app._on_view(); pump()
assert app.palette_canvas.winfo_ismapped() and app.name_row.winfo_ismapped()  # name row stays: it names the export
app.transparent_var.set(False); app._settings_changed(); pump()
print("name edit, tip, disabled drag/scale, and switching back all OK")

# Continue the rest of the test with the previous settings
app.enhance_var.set(True)
app.grid_var.set(32); app.scale.set(16); app.detail_scale.set(50); app._settings_changed(); pump()
assert app.small_art.size == (32, 32) and app.big_art.size == (512, 512)
st = app.status_full; print("status:", st.replace("\n", " | "))
assert "Subject found" in st
capture("desk_loaded.png")

# Transparent background + inside outline + more detail, 16x16
app.transparent_var.set(True); app.outline_var.set("inside"); app._settings_changed(); pump()
app.detail_scale.set(80); pump()
app.grid_var.set(16); app._settings_changed(); pump()
a = app.small_art.getchannel("A")
print("16x16 inside/transparent: alpha extrema", a.getextrema(), "detail label", app.detail_label.cget("text"))
assert app.small_art.size == (16, 16) and a.getextrema() == (0, 255) and app.detail_label.cget("text") == "80"
capture("desk_transparent.png")

# Custom line colour via a stubbed colour picker (no modal dialog)
pf.colorchooser.askcolor = lambda **k: ((0, 90, 200), "#005ac8")
app.transparent_var.set(False); app.outline_var.set("outside"); app.grid_var.set(32)
app.pick_line_color(); pump()
cols = {c[1][:3] for c in app.small_art.getcolors(1024)}
assert (0, 90, 200) in cols and app.swatch.cget("bg") == "#005ac8"
app._set_line_color(None); pump()
assert (0, 90, 200) not in {c[1][:3] for c in app.small_art.getcolors(1024)}
print("custom line colour applied, Auto restored")

# Colour limit still respected with lines + flat background
app.scale.set(6); pump()
n = len(app.small_art.getcolors(1024)); print("6-colour limit ->", n, "colours"); assert n <= 6
app.scale.set(16); pump()

# Scale & position: slider, wheel, drag, buttons, keys, reset
from pixel_core import pixelate_detailed as pdet
def bb(): return app.small_art.getchannel("A").getbbox()
app.transparent_var.set(True); app._settings_changed(); pump()
full = bb()
app.size_scale.set(50); pump()
half = bb(); print("slider 50%:", app.size_label.cget("text"), full, "->", half)
assert app.scale_var.get() == 50 and (half[2] - half[0]) < (full[2] - full[0]) * 0.6
class Ev:
    def __init__(self, **k): self.__dict__.update(k)
app.zoom_fit(); pump()
app._on_wheel(Ev(x=5, y=5, delta=120, state=0x4)); app._on_wheel(Ev(x=5, y=5, delta=120, state=0x4)); pump()
assert app.scale_var.get() == 60 and round(app.size_scale.get()) == 60, "Ctrl+wheel + slider sync"
assert app.zoom is None, "Ctrl+wheel with Move scales, doesn't zoom"
k = app._art_k
app._on_drag_start(Ev(x=100, y=100)); app._on_drag(Ev(x=100 + 3 * k, y=100 - 2 * k)); app._on_drag_end(None); pump()
assert app.offset == [3, -2], app.offset
before = bb(); app.nudge(1, 0); pump(); after = bb()
assert after[0] - before[0] == 1 and app.offset == [4, -2]
assert "<Control-Key-Down>" in app.root.bind(); app.nudge(0, 1); pump()  # the Ctrl+Down binding's action (key events need OS focus, which the hidden test window never takes)
assert app.offset == [4, -1], app.offset
st = app.status_full; print("status:", st.replace("\n", " | ")); assert "Scale 60%, moved +4, -1" in st
ref = pdet(app.original, 32, 16, outline="outside", detail=80, fit_subject=True, transparent_bg=True, scale=0.6, offset=(4, -1), enhance=True)
assert ref.small.tobytes() == app.small_art.tobytes(), "UI output == core output"
capture("desk_scaled.png")
app.reset_transform(); pump()
assert app.offset == [0, 0] and app.scale_var.get() == 100 and bb() == full
print("scale/position controls OK; reset restores the original framing")
app.transparent_var.set(False); app._settings_changed(); pump()

# ---- AI background removal ----
import pixel_core as pc
infos = []
pf.messagebox.showinfo = lambda *a, **k: infos.append(a)
real_status = pf.ai_status
pf.ai_status = lambda: "AI removal isn't installed. Run install-ai.bat once (needs internet)."
app.bg_method.set("ai"); app._on_bg_method(); pump()
assert app.bg_method.get() == "plain" and infos and "install-ai.bat" in infos[0][1]
print("AI not installed -> message shown, reverted to Plain")
pf.ai_status = real_status

# Busy-background image: plain detection fails, AI succeeds
from PIL import ImageFilter
import random
random.seed(5)
src_img = Image.open(axe).convert("RGB")
cut = pc.detect_subject(src_img).mask
busy = Image.new("RGB", src_img.size, (90, 130, 80)); bd = ImageDraw.Draw(busy)
for _ in range(60):
    x, y, r = random.randint(0, 2048), random.randint(0, 2048), random.randint(40, 300)
    bd.ellipse((x - r, y - r, x + r, y + r), fill=tuple(random.randint(40, 220) for _ in range(3)))
busy = busy.filter(ImageFilter.GaussianBlur(12)); busy.paste(src_img, (0, 0), cut)
busy.save(OUT / "busy_axe.jpg", quality=92)
app.transparent_var.set(False)
app.load_image(OUT / "busy_axe.jpg"); pump()
print("plain on busy_axe:", app.status_full.splitlines()[-1])
capture("desk_busy_plain.png")
app.bg_method.set("ai"); app._on_bg_method()
t0 = time.time(); ticks = 0; saw_busy = False
while "Background removed" not in app.status_full and time.time() - t0 < 60:
    root.update(); time.sleep(0.02)   # the UI keeps running meanwhile
    if app._ai_job is not None:
        ticks += 1
        saw_busy = saw_busy or "Removing background" in app.status_full
pump()
assert saw_busy, "progress message shown while AI runs"
st = app.status_full; print(f"AI done in {time.time() - t0:.1f}s, UI loop ran {ticks} times meanwhile | {st.splitlines()[-1]}")
assert "Background removed with AI" in st and app.transparent_var.get() is True and ticks > 10
a = app.small_art.getchannel("A")
assert a.getextrema() == (0, 255)
capture("desk_ai.png")
# Settings changes after AI are instant (cached)
t = time.perf_counter(); app.grid_var.set(16); app.process(); dt = time.perf_counter() - t
print(f"re-render after AI: {dt * 1000:.0f}ms"); assert dt < 0.5
app.grid_var.set(32); app.bg_method.set("plain"); app.transparent_var.set(False); app._settings_changed(); pump()
app.load_image(axe); pump()

# Busy image with no plain background -> explanatory status
Image.effect_noise((400, 400), 90).convert("RGB").save(OUT / "busy.png")
app.load_image(OUT / "busy.png"); pump()
st = app.status_full; print("busy status:", st.replace("\n", " | ")); assert "No plain background" in st
app.load_image(axe); pump()

app.save(OUT / "desk_big.png"); app.save(OUT / "desk_raw.png", raw=True)

# ---- Export folder ----
EXP = OUT / "export test"
shutil.rmtree(EXP, ignore_errors=True); EXP.mkdir()
asked = []
pf.filedialog.asksaveasfilename = lambda **k: asked.append(k) or ""   # cancelled dialog
assert app.export_dir is None and "Export folder" in app.export_btn.cget("text")
assert str(app.open_dir_btn.cget("state")) == "disabled"
app.save_dialog(raw=True); assert asked and asked[-1]["initialfile"] == pf.texture_id(app.item_name.get()) + ".png"
print("no folder -> Save asks where (suggesting", asked[-1]["initialfile"] + ")")
pf.filedialog.askdirectory = lambda **k: str(EXP)
app.choose_export_dir()
assert app.export_dir == EXP and json.loads(pf.settings_file().read_text())["export_dir"] == str(EXP)
assert str(app.open_dir_btn.cget("state")) == "normal"
app.item_name.set("Flesh Axe"); pump(); capture("desk_export_set.png")
n_asked = len(asked)
app.save_dialog(raw=True); app.save_dialog(raw=False)
assert len(asked) == n_asked, "no dialog once a folder is set"
assert Image.open(EXP / "flesh_axe.png").size == app.small_art.size
assert Image.open(EXP / "flesh_axe_512.png").size == (512, 512)
assert "flesh_axe" in app.status_full and str(EXP) in app.status_full
print("folder set -> saved flesh_axe.png + flesh_axe_512.png directly; setting written to settings.json")
# An existing file we didn't write: ask once, then re-exports are silent
(EXP / "bone_club.png").write_bytes(b"hand-made texture")
app.item_name.set("Bone Club"); pump()
answers, asks = [False], []
pf.messagebox.askyesno = lambda *a, **k: asks.append(a) or answers[0]
app.save_dialog(raw=True)
assert (EXP / "bone_club.png").read_bytes() == b"hand-made texture", "declined -> untouched"
answers[0] = True; app.save_dialog(raw=True)
assert Image.open(EXP / "bone_club.png").size == app.small_art.size and len(asks) == 2
app.save_dialog(raw=True); assert len(asks) == 2, "asked only once per file"
print("existing file: declined keeps it; accepted replaces it; later re-exports don't ask again")
# Remembered by a new app instance
top = tk.Toplevel(root); top.withdraw()
app2_settings = pf.load_settings(); assert app2_settings["export_dir"] == str(EXP)
top.destroy()
# Folder deleted meanwhile -> offer to choose another (declined here)
missing = OUT / "gone"; app.set_export_dir(missing)
answers[0] = False; app.save_dialog(raw=True)
assert "no longer exists" in asks[-1][1] and not missing.exists()
app.clear_export_dir()
assert app.export_dir is None and "export_dir" not in json.loads(pf.settings_file().read_text())
print("missing folder handled; Clear forgets the folder")
capture("desk_export.png")
print("saved sizes:", Image.open(OUT / "desk_big.png").size, Image.open(OUT / "desk_raw.png").size)

# Resize the window -> art must stay an integer multiple (sharp)
root.geometry("900x720+40+40"); pump(); capture("desk_min.png")
print("after resize, art photo:", app._photos["art"].width(), "(multiple of 32:", app._photos["art"].width() % 32 == 0, ")")

# Bad file -> error dialog is shown; stub it to avoid a modal popup
shown = []
pf.messagebox.showerror = lambda *a: shown.append(a)
(OUT / "not_image.png").write_text("nope")
assert app.load_image(OUT / "not_image.png") is False and shown
print("bad file handled, previous image kept:", app.source_path.name)
root.destroy()
print("ALL OK")
