"""Progress bars on waits: slowed on purpose, in the real app (hidden window, no mouse or focus)."""
import json, os, time
from pathlib import Path
from PIL import Image, ImageDraw

from _paths import APP, IMAGES, SCR, TESTS  # (this also puts the app on sys.path)
os.environ["PIXEL_FORGE_HIDDEN"] = "1"
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
import edit_session, waitbar
same = lambda a, b: a.tobytes() == b.tobytes()
real_pixelate = pf.pixelate_detailed
W = app.waits


def until(cond, limit=15.0):
    end = time.time() + limit
    while time.time() < end:
        root.update(); time.sleep(0.02)
        if cond():
            return True
    raise AssertionError("timed out")


def bar_state():
    return W.frame.winfo_ismapped(), W.label.cget("text"), str(W.progress.cget("mode")), float(W.progress.cget("value"))


def slow(seconds, only=None):
    def pixelate(img, *a, **k):
        if only is None or only(k):
            time.sleep(seconds)
        if k.get("background") == "ai":
            k["background"] = "plain"  # (no real AI in this test)
        return real_pixelate(img, *a, **k)
    pf.pixelate_detailed = pixelate


axe = sorted(IMAGES.glob("Gemini*"))[1]
small = sorted(IMAGES.glob("5d5f*"))[0]  # 1 MP

# 1. A quick conversion never shows a bar
app.load_image(small); app.transparent_var.set(True); app._settings_changed()
for _ in range(30):
    root.update(); time.sleep(0.02)
    assert not W.frame.winfo_ismapped()
assert app.status.winfo_ismapped() and not app.busy()
print("quick conversion (1 MP): no bar, status line stays")

# 2. Match Original, slowed: nothing for 400 ms, then a moving bar with words (no estimate yet), then gone
slow(1.5, only=lambda k: k.get("match_source"))
W.times.pop("match", None)
app.match_original(); t0 = time.time()
until(lambda: time.time() - t0 > 0.25); assert not W.frame.winfo_ismapped(), "not before 400 ms"
until(lambda: W.frame.winfo_ismapped())
shown, words, mode, _ = bar_state()
assert time.time() - t0 >= 0.4 and words.startswith("Matching the original...") and mode == "indeterminate"
assert not app.status.winfo_ismapped(), "it takes the status line's place"
ticks = 0
def count(): global ticks; ticks += 1; root.after(50, count)
root.after(50, count)
until(lambda: "1 s" in W.label.cget("text"))
assert ticks >= 5, ("the window keeps responding while it works", ticks)
capture("1_match_no_estimate.png")
until(lambda: not app.busy() and not W.frame.winfo_ismapped())
assert app.status.winfo_ismapped() and 1.3 < W.times["match"] < 2.5
print(f"Match Original (slowed 1.5 s): bar after 400 ms, '{words.strip()}' moving, window responsive; gone after; learnt {W.times['match']} s")

# 3. Next time it's determinate ('about N s left'), and past the estimate 'longer than usual'
app.colors_var.set(9); app._settings_changed(); until(lambda: not app.busy())
app.match_original()
until(lambda: W.frame.winfo_ismapped())
shown, words, mode, value = bar_state()
assert mode == "determinate" and "s left" in words and value > 0, (words, mode, value)
capture("2_match_estimate.png")
until(lambda: not app.busy())
W.times["match"] = 0.6
slow(2.0, only=lambda k: k.get("match_source"))
app.colors_var.set(8); app._settings_changed(); until(lambda: not app.busy())
app.match_original()
until(lambda: W.frame.winfo_ismapped() and "longer than usual" in W.label.cget("text"))
assert str(W.progress.cget("mode")) == "indeterminate", (bar_state(), repr(W.progress.cget("mode")), [(w.kind, w.text, w.estimate) for w in W.waits])
until(lambda: not app.busy() and not W.frame.winfo_ismapped())
print("with an estimate: determinate 'about N s left'; past it: 'N s, longer than usual'")

# 4. A big picture converts on a thread: bar 'Converting the image...', window responsive, newest settings win
slow(1.2)
W.times["convert_per_mp"] = 0.5  # 4 MP -> about 2 s expected: on a thread
app.load_image(axe); t0 = time.time()
assert app._convert_job is not None and app.busy()
until(lambda: W.frame.winfo_ismapped())
assert W.label.cget("text").startswith("Converting the image...") and "s left" in W.label.cget("text")
app.colors_var.set(6); app._settings_changed()  # changed mid-way
until(lambda: not app.busy() and not W.frame.winfo_ismapped(), 20)
pf.pixelate_detailed = real_pixelate
assert len({c for _, c in app.small_art.getcolors(1 << 16) if c[3]}) <= 6, "the art is for the newest settings"
assert W.times["convert_per_mp"] < 0.5
print(f"big picture: converted on a thread with a bar, re-done for settings changed mid-way; speed learnt "
      f"({W.times['convert_per_mp']} s/MP)")

# 5. Converter AI (stubbed model, slowed): 'Removing the background with AI...'
ai_done = {}
def fake_find(img, background="plain"):
    time.sleep(1.0); ai_done[id(img)] = True
pf.find_subject, pf.subject_is_cached = fake_find, lambda img, method: id(img) in ai_done
pf.ai_status = lambda: None
slow(0)
W.times["convert_per_mp"] = 0.01
app.bg_method.set("ai"); app._on_bg_method()
until(lambda: W.frame.winfo_ismapped())
assert W.label.cget("text").startswith("Removing the background with AI...")
until(lambda: not app.busy() and not W.frame.winfo_ismapped())
assert "ai_first" in W.times or "ai" in W.times
app.bg_method.set("plain"); app._settings_changed(); until(lambda: not app.busy())
pf.pixelate_detailed = real_pixelate
print("converter AI: bar while the model works, gone after")

# 6. Texture editing: AI Remove BG (slowed) shows the bar
tex = SCR / "wait_tex.png"
t = Image.new("RGBA", (16, 16), (128, 128, 128, 255)); ImageDraw.Draw(t).rectangle((4, 4, 11, 11), fill=(200, 40, 40, 255)); t.save(tex)
real_clear = edit_session.clear_background
def slow_clear(img, method="plain"):
    time.sleep(1.0); return real_clear(img, "plain")
edit_session.clear_background = slow_clear
edit_session.ai_status = lambda: None
assert app.start_session({"path": str(tex), "name": "T", "result": None, "caller": "Grass Block"})
pump()
app.remove_texture_background("ai")
until(lambda: W.frame.winfo_ismapped())
assert W.label.cget("text").startswith("Removing the background with AI...")
capture("3_texture_ai.png")
until(lambda: not app.busy() and not W.frame.winfo_ismapped())
assert app.layers[0].image.getpixel((0, 0))[3] == 0
print("texture AI Remove BG: bar while it works; background cleared after")

# 7. Saved: the learnt times are in the settings file
saved = json.loads((Path(os.environ["APPDATA"]) / "PixelForge" / "settings.json").read_text())
assert {"match", "convert_per_mp"} <= set(saved["wait_times"]), saved
print("typical times saved per kind:", saved["wait_times"])
app._session_end(10)
try:
    pump(0.3)
except tk.TclError:
    pass
print("ALL OK")
