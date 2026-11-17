"""Batch: several pictures converted at once with the sidebar's settings, each saved as its own
sprite (invisible windows; the pictures are the real test pictures)."""
import os
import shutil
import time

os.environ["PIXEL_FORGE_HIDDEN"] = "1"  # dialogs are created withdrawn
from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
import batch_ui
import pixel_core

errors, asked, infos = [], [], []
answers = {"yesno": True, "ync": True, "folder": ""}
root.report_callback_exception = lambda *a: errors.append(a[1])
pf.messagebox.askyesno = lambda *a, **k: asked.append(a[1]) or answers["yesno"]
pf.messagebox.askyesnocancel = lambda *a, **k: asked.append(a[1]) or answers["ync"]
pf.messagebox.showinfo = lambda *a, **k: infos.append(a[1])
pf.messagebox.showerror = lambda *a, **k: infos.append(a[1])
batch_ui.filedialog.askdirectory = lambda **k: answers["folder"]
batch_ui.filedialog.askopenfilenames = lambda **k: answers.get("files", ())

work = SCR / "batch"
shutil.rmtree(work, ignore_errors=True)
OUT, OUT2 = work / "out", work / "out2"
for d in (OUT, OUT2, work / "other"):
    d.mkdir(parents=True)
pictures = sorted(IMAGES.glob("*.jpg"))
assert len(pictures) >= 4, pictures
broken = work / "not a picture.png"
broken.write_text("this is not an image", encoding="utf-8")
twin = work / "other" / pictures[0].name   # the same name as the first picture, in another folder
shutil.copy(pictures[0], twin)


def until(cond, limit=60.0):
    end = time.time() + limit
    while time.time() < end:
        root.update(); time.sleep(0.02)
        if cond():
            return
    raise AssertionError("timed out")


def show_invisibly(top):
    """Lay the batch window out for real (so it can be pictured), as the harness does the main window."""
    top.update_idletasks()
    if WINDOWS:
        h = int(top.wm_frame(), 16)
        u32.SetWindowLongW(h, -20, u32.GetWindowLongW(h, -20) | 0x80000 | 0x20 | 0x08000000 | 0x80)
        u32.SetLayeredWindowAttributes(h, 0, 0, 2)
        u32.ShowWindow(h, 4)
    else:
        top.deiconify()
    pump(0.4)
    return h if WINDOWS else None


def capture_top(top, name):
    """A picture of the batch window (PrintWindow of its own handle on Windows, the X screen on Linux)."""
    top.update()
    if not WINDOWS:
        from PIL import ImageGrab
        x, y = top.winfo_rootx(), top.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + top.winfo_width(), y + top.winfo_height()),
                       xdisplay=os.environ.get("DISPLAY")).convert("RGB").save(OUT_SHOTS / name)
        return
    import harness  # capture() pictures harness.root by harness.hwnd: point both at the batch window a moment
    saved = harness.root, harness.hwnd

    class Proxy:
        def __getattr__(self, attr):
            return getattr(top, attr)
    harness.root, harness.hwnd = Proxy(), int(top.wm_frame(), 16)
    try:
        capture(name)
    finally:
        harness.root, harness.hwnd = saved


OUT_SHOTS = OUT.parent


def rows():
    return {item.path.name: (item.status, item.message) for item in app._batch_items}


def png(path):
    return Image.open(path).convert("RGBA")


# 1. The button: in the top bar after Open..., with Ctrl+B; the top bar still fits everywhere
pump()
b = app.batch_btn
assert str(b.cget("text")) == "Batch..." and b.winfo_ismapped()
assert b.winfo_rootx() > find(app.top_bar, ttk.Button, "Open...").winfo_rootx()
assert b.winfo_rootx() < app.save_btn.winfo_rootx()
assert "open_batch" in root.bind("<Control-b>") or root.bind("<Control-b>")
for size in ("900x720", "1140x800", "1280x800"):
    root.geometry(f"{size}+40+40"); pump(0.4)
    assert not squashed(), (size, squashed())
root.geometry("1140x800+40+40"); pump(0.3)
print("Batch... sits after Open... in the top bar (Ctrl+B); nothing squashed at 900, 1140 and 1280 wide")

# 2. In an edit session it does nothing (that window is about its one texture)
app.session = {"path": "x"}
app.open_batch(); pump(0.1)
assert app._batch_dialog is None
app.session = None

# 3. The window: empty at first, Convert All waits for pictures
app.load_image(pictures[1]); pump(0.5)                 # (the main window has its own picture meanwhile)
main_sprite = app.small_art.tobytes()
main_image = app.original
app.open_batch(); pump(0.2)  # (what Ctrl+B runs; a key press needs the focus, which this window never takes)
top = app._batch_dialog
assert top is not None and top.winfo_exists() and top.state() == "withdrawn", "hidden runs: never on screen"
show_invisibly(top)
assert "No pictures yet" in str(app._batch_area.inner.winfo_children()[0].cget("text"))
assert str(app.batch_go.cget("state")) == "disabled" and str(app.batch_dir_btn.cget("text")) == "Choose..."
assert str(app.batch_sprite_check.cget("text")) == f"Sprite ({app.grid_var.get()}x{app.grid_var.get()})"
assert app.batch_sprite_var.get() and not app.batch_art_var.get()
assert app.batch_remove_var.get() == app.transparent_var.get() and app.batch_method_var.get() == app.bg_method.get()
assert app.batch_match_var.get(), "Match Original after removing is on by default"
assert not app.batch_remove_var.get()
assert all(str(r.cget("state")) == "disabled" for r in app.batch_method_radios + [app.batch_match_check]), \
    "Plain/AI and Match Original go with Remove backgrounds"
app.batch_remove_check.invoke(); pump(0.1)
assert app.batch_remove_var.get()
assert all(str(r.cget("state")) == "normal" for r in app.batch_method_radios + [app.batch_match_check])
print("the batch window opens empty; Convert All waits for pictures; Sprite is ticked, Art isn't; "
      "backgrounds start as the sidebar has them, and Remove backgrounds turns on Plain/AI and Match Original")

# 4. Adding pictures: several at once, never the same file twice, thumbnails as they load
answers["files"] = [str(p) for p in pictures] + [str(broken), str(pictures[0]), str(work / "gone.png")]
app.batch_add_btn.invoke()
assert len(app._batch_items) == len(pictures) + 1, rows()
answers["files"] = [str(twin)]
app._ask_batch_pictures()
n = len(app._batch_items)
assert n == len(pictures) + 2 and str(app.batch_count.cget("text")) == f"{n} pictures"
until(lambda: not app._batch_thumbs)
assert all(i.thumb is not None for i in app._batch_items if i.path != broken)
assert str(app.batch_go.cget("state")) == "normal"
capture_top(top, "batch_added.png")
print(f"{n} pictures added (a duplicate and a missing file ignored), each with its thumbnail")

# 5. Convert All: no folder yet, so it asks; a progress bar in the batch window; every result shown
app.colors_var.set(8); app.transparent_var.set(True); app.offset = [3, -2]; app._settings_changed(); pump(0.5)
until(lambda: not app.busy())
main_sprite, main_image = app.small_art.tobytes(), app.original
answers["folder"] = str(OUT)
real = batch_ui.pixelate_detailed
batch_ui.pixelate_detailed = lambda *a, **k: (time.sleep(0.25), real(*a, **k))[1]  # (long enough for the bar to show)
app.batch_go.invoke()
job = app._batch_job
assert job is not None and app.busy() and app._batch_dir == OUT
assert job["settings"]["offset"] == (0, 0) and job["settings"]["colors"] == 8 and job["settings"]["transparent_bg"]
assert job["settings"]["background"] == "plain" and job["match"] is True
assert all(str(r.cget("state")) == "disabled" for r in app.batch_method_radios + [app.batch_match_check]
           + [app.batch_remove_check]), "no changing them while it works"
assert str(app.batch_go.cget("text")) == "Stop" and str(app.batch_add_btn.cget("state")) == "disabled"
W = app.batch_waits
until(lambda: W.frame.winfo_ismapped(), 20)
words, mode = W.label.cget("text"), str(W.progress.cget("mode"))
assert words.startswith("Converting ") and " of " in words and mode == "determinate", (words, mode)
capture_top(top, "batch_running.png")
until(lambda: not app.busy(), 120)
batch_ui.pixelate_detailed = real
assert not W.frame.winfo_ismapped()
status = rows()
assert status[broken.name][0] == "failed" and status[broken.name][1].startswith("Failed:"), status[broken.name]
done = [i for i in app._batch_items if i.status == "done"]
assert len(done) == len(pictures) + 1, status
summary = str(app.batch_summary.cget("text"))
assert summary.startswith(f"{len(done)} of {n} converted and saved to {OUT}") and "1 failed" in summary, summary
assert app.status_full == f"Batch: {summary}"
print(f"Convert All: asked for a folder, bar '{words}', then: {summary}")

# 6. The files: named as Save names them, the twin gets _2, each exactly what the converter makes
settings = dict(job["settings"])
for item in done:
    tid = batch_ui.texture_id(item.path.stem)  # (the whole name: Save shortens long ones for the tooltip)
    want = OUT / (f"{tid}_2.png" if item.path == twin else f"{tid}.png")
    assert item.saved == [want] and want.is_file(), (item.path, item.saved)
    with Image.open(item.path) as img:
        img.load()
        with pixel_core.private_subjects():  # (this check mustn't touch the window's cache either)
            first = pixel_core.pixelate_detailed(img, **settings)
            matched = first.subject_found
            expected = (pixel_core.pixelate_detailed(img, **settings, match_source=True) if matched else first).small
    assert ("background removed, original matched" in item.message) == bool(matched), item.message
    got = png(want)
    assert got.size == (16, 16) and got.tobytes() == expected.convert("RGBA").tobytes(), item.path
    assert item.result_thumb is not None
assert not list(OUT.glob(f"*_{pf.PREVIEW_SIZE}.png")), "Art wasn't ticked"
assert sorted(p.name for p in OUT.iterdir()) == sorted(p.name for i in done for p in i.saved)
print(f"files: {', '.join(sorted(p.name for p in OUT.iterdir()))} - each the converter's own result, "
      "background removed and the original matched")

# 7. The main window kept its picture, its sprite and its cached subject
assert app.original is main_image and app.small_art.tobytes() == main_sprite
assert pixel_core.subject_is_cached(app.original, "plain"), "the batch never pushed the window's picture out"
print("the main window's picture, sprite and subject cache are untouched by the batch")

# 8. Again with Art too, into a folder where a file is already there: asks; No skips that picture
app._batch_dir = OUT2
first = app._batch_items[0]
(OUT2 / f"{first.tid}.png").write_bytes(b"someone else's file")
app.batch_art_var.set(True)
answers["ync"] = False
n_asked = len(asked)
app.start_batch(); until(lambda: not app.busy(), 120)
assert len(asked) == n_asked + 1 and "1 of the files already exist" in asked[-1]
assert first.status == "skipped" and (OUT2 / f"{first.tid}.png").read_bytes() == b"someone else's file"
second = app._batch_items[1]
art = png(OUT2 / f"{second.tid}_{pf.PREVIEW_SIZE}.png")
sprite = png(OUT2 / f"{second.tid}.png")
assert art.size == (pf.PREVIEW_SIZE,) * 2
assert art.tobytes() == sprite.resize(art.size, Image.Resampling.NEAREST).tobytes(), "Art = the sprite enlarged"
assert "1 skipped" in str(app.batch_summary.cget("text"))
answers["ync"] = True                                    # ... and Yes replaces it
app.start_batch(); until(lambda: not app.busy(), 120)
assert first.status == "done" and png(OUT2 / f"{first.tid}.png").size == (16, 16)
print("a file already there: asked; No skips that picture, Yes replaces it; Art is the sprite enlarged")

# 9. Stop: the picture under way finishes, the rest wait


def slow(*a, **k):
    time.sleep(0.6)
    return real(*a, **k)


batch_ui.pixelate_detailed = slow
app._batch_dir = work / "stopped"
app._batch_dir.mkdir()
app.start_batch()
until(lambda: any(i.status == "done" for i in app._batch_items) or not app.busy(), 30)
app.batch_go.invoke()                                     # (it says Stop now)
assert str(app.batch_go.cget("text")) == "Stopping..."
until(lambda: not app.busy(), 30)
left = [i for i in app._batch_items if i.status == "waiting"]
assert left and "stopped" in str(app.batch_summary.cget("text")) and str(app.batch_go.cget("text")) == "Convert All"
print(f"Stop: the picture under way finished, {len(left)} left waiting")

# 10. Closing the window while it works: asked first; it stops, and the main window is told
app._batch_dir = work / "closed"
app._batch_dir.mkdir()
app.start_batch(); pump(0.3)
answers["yesno"] = False
app.close_batch(); pump(0.1)
assert top.winfo_exists() and app.busy(), "No keeps it going"
answers["yesno"] = True
app.close_batch()
assert not top.winfo_exists() and app._batch_dialog is None
until(lambda: not app.busy(), 30)
assert app.status_full.startswith("Batch: ") and "stopped" in app.status_full
assert not errors, errors
batch_ui.pixelate_detailed = real
print("closing while it works asks first; Yes stops it, and the status line says how far it got")

# 11. Reopened, the list is still there; double-click opens a picture in the main window
app.open_batch(); pump(0.2)
top = app._batch_dialog
show_invisibly(top)
assert len(app._batch_items) == n and len(app._batch_area.inner.winfo_children()) == n
item = app._batch_items[2]
assert all(item.widgets[k].bind("<Double-Button-1>") for k in ("row", "source", "result", "name", "status"))
app._open_batch_item(item); pump(0.5)  # (what the double-click runs: Tk can't fake a double-click)
assert app.source_path == item.path
print("reopened, the list is kept; double-clicking a picture opens it in the main window")

# 12. Taking pictures off: one, the finished ones, all
app.remove_batch_item(app._batch_items[-1]); pump(0.1)
assert len(app._batch_items) == n - 1
app.batch_remove_btn.invoke(); pump(0.1)
assert all(i.status != "done" for i in app._batch_items)
capture_top(top, "batch_left.png")
app.batch_clear_btn.invoke(); pump(0.1)
assert app._batch_items == [] and str(app.batch_go.cget("state")) == "disabled"
print("the x button takes one off, Remove Finished the converted ones, Clear all")

# 13. Nothing to save ticked, or AI without its model: says so and starts nothing
app.add_batch_pictures([pictures[0]]); pump(0.2)
app.batch_sprite_var.set(False); app.batch_art_var.set(False)
app.start_batch()
assert app._batch_job is None and "Tick Sprite or Art" in infos[-1]
app.batch_sprite_var.set(True)
real_status, real_offer = batch_ui.ai_status, app._offer_ai_download
batch_ui.ai_status = lambda: "AI background removal isn't installed."
app._offer_ai_download = lambda then: False
app.batch_method_var.set("ai")
app.start_batch()
assert app._batch_job is None and infos[-1] == "AI background removal isn't installed."
offered = []
app._offer_ai_download = lambda then: offered.append(then) or True
app.start_batch()
assert app._batch_job is None and offered == [app.start_batch], "only the model missing: it offers it, then starts"
batch_ui.ai_status, app._offer_ai_download = real_status, real_offer
app.batch_method_var.set("plain")
print("nothing ticked, or AI not ready: says so (or offers the AI model) and starts nothing")

# 14. Each picture's subject is found once, though Match Original converts it a second time;
#     Remove backgrounds unticked: the background stays and nothing is matched
real_detect, found = pixel_core.detect_subject, []
pixel_core.detect_subject = lambda img: found.append(img) or real_detect(img)
app._batch_dir = work / "once"
app._batch_dir.mkdir()
app.start_batch(); until(lambda: not app.busy(), 60)
assert len(found) == 1 and "original matched" in app._batch_items[0].message, (len(found), app._batch_items[0].message)
app.batch_remove_var.set(False); app._update_batch_controls()
app._batch_dir = work / "kept"
app._batch_dir.mkdir()
app.start_batch()
assert app._batch_job["settings"]["transparent_bg"] is False and app._batch_job["match"] is False
until(lambda: not app.busy(), 60)
pixel_core.detect_subject = real_detect
kept = png(work / "kept" / f"{app._batch_items[0].tid}.png")
assert kept.getpixel((0, 0))[3] == 255, "the background stays (no see-through corner)"
assert "background removed" not in app._batch_items[0].message
print("the subject is found once per picture even with Match Original; unticked, backgrounds stay")

capture_top(app._batch_dialog, "batch_options_off.png")
app.batch_remove_check.invoke(); pump(0.2)
capture_top(app._batch_dialog, "batch_options.png")
for size in ("900x720", "1280x800"):
    root.geometry(f"{size}+40+40"); pump(0.3)
    assert not squashed(), (size, squashed())
assert not errors, errors
app.close_batch()

# Pictures given on the command line (Picture Scout's "Send all to Pixel Forge"): several open in Batch,
# one opens in the converter, as before. "open" and "batch" are listed in --describe.
import edit_session
assert edit_session.parse_args([str(pictures[0]), str(pictures[1])]).image == [str(pictures[0]), str(pictures[1])]
assert edit_session.parse_args([str(pictures[0])]).image == [str(pictures[0])] and edit_session.parse_args([]).image == []
assert {"open", "batch"} <= set(edit_session.DESCRIPTION["modes"]) and edit_session.DESCRIPTION["protocol"] == 1
app.clear_batch()
pf.open_given(app, [str(pictures[2]), str(pictures[3])]); pump(0.3)
assert app._batch_open(), "several pictures: the Batch window opens"
assert [i.path for i in app._batch_items] == [pictures[2], pictures[3]], app._batch_items
app.close_batch(); app.clear_batch()
pf.open_given(app, [str(pictures[0])]); pump(0.5)
assert not app._batch_open() and app.original is not None and app.original is not main_image, "one picture: the converter"
assert not errors, errors
print("pictures from the command line: several open in Batch, one in the converter")
print("ALL OK")
