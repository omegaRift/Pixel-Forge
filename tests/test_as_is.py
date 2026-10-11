"""Opening pixel art as it is (no conversion), in the real app (hidden window)."""
import os, shutil
from pathlib import Path
from PIL import Image, ImageDraw

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
os.environ["PIXEL_FORGE_HIDDEN"] = "1"
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
same = lambda a, b: a.tobytes() == b.tobytes()

# A 16x16 pixel-art sword: exact colours, see-through background, one half-see-through pixel
art = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
d = ImageDraw.Draw(art)
d.line((3, 12, 12, 3), fill=(200, 210, 220, 255), width=2); d.line((2, 10, 5, 13), fill=(120, 70, 30, 255), width=1)
art.putpixel((13, 2), (255, 255, 255, 128))
art_path = SCR / "sword16.png"; art.save(art_path)
Image.new("RGBA", (16, 32), (9, 9, 9, 255)).save(SCR / "tall.png")
Image.new("RGBA", (300, 300), (9, 9, 9, 255)).save(SCR / "big.png")

answers = {"file": str(art_path), "ask": True}
asked, errors = [], []
pf.filedialog.askopenfilename = lambda **k: answers["file"]
pf.messagebox.askyesnocancel = lambda *a, **k: asked.append(a[1]) or answers["ask"]
pf.messagebox.showerror = lambda *a, **k: errors.append(a[1])
yesno = []
pf.messagebox.askyesno = lambda *a, **k: yesno.append(a[1]) or True  # (no real dialog, ever)
inner = app.adjust_area.inner
converter_rows = list(inner.pack_slaves())  # the converter's sections, as first packed

def converter_back():
    return [w for w in inner.pack_slaves() if w not in (app.gradient_panel, app.projection_panel)] == converter_rows

# 1. Open... on a 16x16 picture asks; Yes opens it as it is
app.open_dialog(); pump()
assert asked and "16x16" in asked[-1] and "as it is" in asked[-1]
assert app.texture_mode and not app.session and [l.name for l in app.layers] == ["Texture"]
assert same(app.display_art, art), "pixel for pixel: no alteration"
assert app.small_art.size == (16, 16) and not any(w.winfo_ismapped() for w in converter_rows)
assert not app.match_btn.winfo_ismapped() and "opened as-is" in app.art_title.cget("text")
assert "Opened sword16.png as it is" in app.status_full and app.item_name.get() == "Sword16"
assert str(app.save_raw_btn.cget("state")) == "normal" and app.tool_var.get() == "pen"
capture("1_as_is.png")
print("Open... on a 16x16 picture asks; Yes opens it pixel for pixel as one 'Texture' layer")

# 2. Save Sprite writes it unchanged (at 16x16); painting then saving keeps the rest identical
out = SCR / "as_is_out"; shutil.rmtree(out, ignore_errors=True); out.mkdir()
app.set_export_dir(out); app.save_dialog(raw=True)
assert same(Image.open(out / "sword16.png").convert("RGBA"), art)
app.set_paint_colour((255, 0, 255, 255)); app._on_drag_start(at(0, 0)); app._on_drag_end(at(0, 0)); pump()
app.save_dialog(raw=True)
saved = Image.open(out / "sword16.png").convert("RGBA")
assert saved.getpixel((0, 0)) == (255, 0, 255, 255) and all(
    saved.getpixel((x, y)) == art.getpixel((x, y)) for y in range(16) for x in range(16) if (x, y) != (0, 0))
app.clear_export_dir()
print("Save Sprite: saved exactly as opened; after painting one pixel, only that pixel differs")

# 3. Converting a picture again brings the converter back as it was (and asks about the edit)
axe = sorted(IMAGES.glob("Gemini*"))[1]
answers["file"] = str(axe); n = len(asked)
app.open_dialog(); pump()
assert len(asked) == n, "a big picture isn't asked about"
assert yesno and "discards your layers" in yesno[-1], "one pixel was painted: it asked first"
assert not app.texture_mode and converter_back() and app.match_btn.winfo_ismapped()
assert app.layers[0].live and app.orig_title.cget("text").startswith("Source"), ([(l.name, l.live) for l in app.layers], app.orig_title.cget("text"), app.small_art.size)
print("Open... on the big axe picture: converted as before, converter settings and Match Original back")

# 4. No converts even a small one; Cancel does nothing; untouched as-is files don't ask to discard
answers["file"] = str(art_path); answers["ask"] = False
app.open_dialog(); pump()
assert not app.texture_mode and app.layers[0].live and app.small_art.size[0] in (16, 32)
before = app.display_art.copy(); answers["ask"] = None
app.open_dialog(); pump(); assert same(app.display_art, before)
answers["ask"] = True; app.open_dialog(); pump(); assert app.texture_mode
yesno.clear()
app.open_as_is(art_path); pump(); assert not yesno, "nothing done to it: no 'discard?' question"
app._on_drag_start(at(5, 5)); app._on_drag_end(at(5, 5)); pump()
app.open_as_is(art_path); pump(); assert yesno, "painted: it asks first"
print("No converts, Cancel does nothing; switching files only asks when something was painted")

# 5. Ctrl+Shift+O; refuses non-square and too big (with the reason)
assert "<Control-Key-O>" in root.bind()
answers["file"] = str(SCR / "tall.png"); assert app.open_as_is() is False and "16x32" in errors[-1]
answers["file"] = str(SCR / "big.png"); assert app.open_as_is() is False and "300x300" in errors[-1]
assert pf.PixelForgeApp._pixel_art_size(SCR / "big.png") == 0 and pf.PixelForgeApp._pixel_art_size(art_path) == 16
print("Ctrl+Shift+O bound; 16x32 and 300x300 refused with a reason")

# 6. Other tools work on it; as-is -> convert -> as-is -> convert keeps the converter intact
app.open_as_is(art_path); pump()
app.select_tool("gradient"); pump()
assert inner.pack_slaves()[0] is app.gradient_panel
drag((0, 0), (15, 15)); assert [l.name for l in app.layers] == ["Texture", "Gradient 1"]
report = []
for size in ("1140x800", "900x720"):
    root.geometry(f"{size}+40+40"); pump(0.6)
    capture(f"2_as_is_{size}.png"); report.append(f"{size}: {squashed() or 'nothing squashed'}")
print("\n".join(report)); assert all("nothing squashed" in r for r in report)
root.geometry("1140x800+40+40"); pump()
for _ in range(2):
    app.load_image(axe); pump(); assert converter_back()
    app.open_as_is(art_path); pump(); assert same(app.display_art, art)
app.load_image(axe); pump(); assert converter_back() and not app.texture_mode
print("gradient tool works on it; switching back and forth keeps the converter's sections in order")
print("ALL OK")
