"""Grass Block's texture Remove BG together with gradient layers and blends (hidden window)."""
from pathlib import Path
from PIL import Image, ImageDraw

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...

tex = SCR / "removebg_tex.png"
t = Image.new("RGBA", (16, 16), (128, 128, 128, 255))  # a grey-backed texture
ImageDraw.Draw(t).rectangle((4, 4, 11, 11), fill=(200, 40, 40, 255)); t.save(tex)
assert app.start_session({"path": str(tex), "name": "Test", "result": None, "caller": "Grass Block"})
pump()
assert app.bg_buttons, "Grass Block's Remove BG section is there"
app.select_tool("gradient"); pump()
assert app.adjust_area.inner.pack_slaves()[0] is app.gradient_panel, "GRADIENT stays at the top"
drag((0, 0), (15, 15)); pump()
grad = app.layers[1]
n, img = len(app.history.undo_stack), grad.image.copy()
app.remove_texture_background("plain"); pump()
assert grad.image.tobytes() == img.tobytes() and len(app.history.undo_stack) == n and "gradient layer" in app.status_full
print("Remove BG on a gradient layer: refused, with a reason")

app.select_layer(0); app.blend_toggle.invoke(); pump()
assert app.layers[0].fade is not None
app.remove_texture_background("plain"); pump()
tl = app.layers[0]
assert tl.fade is not None and tl.image.getpixel((0, 0))[3] == 0 and tl.image.getpixel((8, 8))[3] == 255
assert app.display_art.tobytes() == L.composite(app.layers, 16).tobytes()
app.undo(); pump(); assert app.layers[0].image.getpixel((0, 0))[3] == 255 and app.layers[0].fade is not None
print("Remove BG on a faded texture layer: background cleared, blend kept, one undo step")
app._session_end(10)
try:
    pump(0.3)
except tk.TclError:
    pass
print("ALL OK")
