"""The app offering to download the AI model (invisible window; the download itself is faked)."""
import io
import time
from contextlib import redirect_stdout

from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
import edit_session

W = app.waits
state = {"model": False, "fail": None, "calls": 0}
asked, infos, errors = [], [], []
answer = {"yes": False}
pf.messagebox.askyesno = lambda *a, **k: asked.append(a[1]) or answer["yes"]
pf.messagebox.showinfo = lambda *a, **k: infos.append(a[1])
pf.messagebox.showerror = lambda *a, **k: errors.append(a[1])
MISSING = "The AI model isn't downloaded yet (a one-time download of 179 MB)."


def fake_download(progress=None, **k):
    state["calls"] += 1
    for i in range(1, 11):
        time.sleep(0.12)
        progress(i / 10)
    if state["fail"]:
        raise pf.ai_model.ModelError(state["fail"])
    state["model"] = True


def until(cond, limit=15.0):
    end = time.time() + limit
    while time.time() < end:
        root.update(); time.sleep(0.02)
        if cond():
            return
    raise AssertionError("timed out")


pf.ai_model.can_download = lambda: not state["model"]
pf.ai_model.download_model = fake_download
pf.ai_status = edit_session.ai_status = lambda: None if state["model"] else MISSING
ai_done = {}
pf.find_subject = lambda img, background="plain": ai_done.setdefault(id(img), True) and None
pf.subject_is_cached = lambda img, method: id(img) in ai_done
real_pixelate = pf.pixelate_detailed
pf.pixelate_detailed = lambda img, *a, **k: real_pixelate(img, *a, **{**k, "background": "plain"})  # (no real AI here)

axe = sorted(IMAGES.glob("5d5f*"))[0]
app.load_image(axe); pump()

# 1. Choosing AI without the model: asks, in plain words; No changes nothing and downloads nothing
app.bg_method.set("ai"); app._on_bg_method(); pump()
assert len(asked) == 1 and "179 MB" in asked[0] and "without internet" in asked[0] and "Download it now?" in asked[0]
assert app.bg_method.get() == "plain" and state["calls"] == 0 and not infos and not app.busy()
print("AI without its model: asks whether to download 179 MB; No leaves Plain selected, nothing downloaded")

# 2. Yes: a progress bar with real progress, then AI is switched on by itself
answer["yes"] = True
app.bg_method.set("ai"); app._on_bg_method()
assert app.busy() and app._ai_download is not None
until(lambda: W.frame.winfo_ismapped())
words, mode, value = W.label.cget("text"), str(W.progress.cget("mode")), float(W.progress.cget("value"))
assert words.startswith("Downloading the AI model...") and mode == "determinate" and value > 0, (words, mode, value)
app.bg_method.set("ai"); app._on_bg_method(); pump(0.1)   # clicking AI again meanwhile: no second download
assert state["calls"] == 1 and "still downloading" in app.status_full
capture("downloading.png")
until(lambda: not app.busy() and not W.frame.winfo_ismapped())
assert state["model"] and app.bg_method.get() == "ai" and app.transparent_var.get() and not errors
assert "ai_download" not in W.times, "it has real progress: no typical time is learnt"
print(f"Yes: bar '{words.strip()}' filling as it downloads; afterwards AI is on (and Transparent BG with it)")

# 3. A failed download: the reason, in the window; AI stays off
state.update(model=False, fail="The AI model couldn't be downloaded (no route to host). Check the internet connection and try again.")
app.bg_method.set("plain"); app._settings_changed(); pump()
app.bg_method.set("ai"); app._on_bg_method()
until(lambda: not app.busy())
assert errors and "Check the internet connection" in errors[-1] and app.bg_method.get() == "plain"
print("a failed download says why and leaves Plain selected")

# 4. The texture panel's AI button (an edit session) offers it too, then removes the background
state.update(fail=None)
from PIL import ImageDraw
tex = SCR / "ai_dl_tex.png"
t = Image.new("RGBA", (16, 16), (128, 128, 128, 255)); ImageDraw.Draw(t).rectangle((4, 4, 11, 11), fill=(200, 40, 40, 255)); t.save(tex)
real_clear = edit_session.clear_background
edit_session.clear_background = lambda img, method="plain": real_clear(img, "plain")  # (no real AI here)
assert app.start_session({"path": str(tex), "name": "T", "result": None, "caller": "Grass Block"})
pump()
n = len(asked)
app.remove_texture_background("ai")
assert len(asked) == n + 1 and app._ai_download is not None
until(lambda: not app.busy(), 20)
assert state["model"] and app.layers[0].image.getpixel((0, 0))[3] == 0, "downloaded, then the background was removed"
print("texture panel: AI offers the download, then removes the background")

# 5. --download-ai-model (no window): progress in words, 0 when the model is here afterwards
state.update(model=False)
pf.ai_model.model_file = lambda: (SCR / "model.onnx") if state["model"] else None
pf.ai_model.engine = lambda: "onnxruntime"
out = io.StringIO()
with redirect_stdout(out):
    code = pf.download_ai_model_cli()
text = out.getvalue()
assert code == 0 and "Downloading the AI background-removal model (179 MB" in text and "100%" in text and "ready" in text, text
with redirect_stdout(io.StringIO()) as again:
    assert pf.download_ai_model_cli() == 0 and "already here" in again.getvalue()
state.update(model=False, fail="The downloaded AI model is damaged (it doesn't match the expected file). Try again.")
with redirect_stdout(io.StringIO()) as bad:
    assert pf.download_ai_model_cli() == 1 and "damaged" in bad.getvalue()
print("--download-ai-model: prints progress and the result; exit code 0 / 1")
app._session_end(10)
try:
    pump(0.3)
except tk.TclError:
    pass
print("ALL OK")
