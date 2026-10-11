"""Gradients + gradient blends inside Grass Block's new 'convert' session (hidden window)."""
import sys
from pathlib import Path
from PIL import Image

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
import inspect, edit_session
print("open_source signature:", inspect.signature(edit_session.EditSessionMixin.open_source))

blank = SCR / "convert_blank.png"; Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(blank)
axe = sorted(IMAGES.glob("Gemini*"))[1]
session = {"path": str(blank), "name": "Axe", "result": None, "caller": "Grass Block",
           "source": str(axe), "transparent": True}
assert app.start_session(session)
pump(1.0)
assert app.small_art is not None and app.small_art.size == (16, 16), "converter made 16x16 art"
app.select_tool("gradient"); pump()
assert app.adjust_area.inner.pack_slaves()[0] is app.gradient_panel
drag((0, 0), (15, 15))
assert [l.name for l in app.layers][-1] == "Gradient 1"
app.select_layer(0); app.blend_toggle.invoke(); pump()
assert app.layers[0].fade is not None
shown = app.display_art.copy()
assert shown.tobytes() == L.composite(app.layers, 16).tobytes()
capture("convert_gradient.png")
app.session_save()
saved = Image.open(blank).convert("RGBA")
assert saved.tobytes() == shown.tobytes() and app.exit_code == 0
print("convert session: gradient layer + blend on the Base, Save & Return wrote exactly what was shown")
try:
    pump(0.3)
except tk.TclError:
    pass
print("ALL OK")
