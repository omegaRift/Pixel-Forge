"""Updates in the window: the startup check, the notification bar, Check for Updates,
installing with a progress bar, and Restart Now (invisible window; the network, the
download and the restart are all stand-ins)."""
import io
import json
import os
import time
from contextlib import redirect_stdout

from harness import *  # the invisible app window: app, root, pump, capture, squashed, at, drag, find...
import update_ui
import updater

V = updater.VERSION
W = app.waits
asked, errors = [], []
answer = {"yes": False}
pf.messagebox.askyesno = lambda *a, **k: asked.append(a[1]) or answer["yes"]
pf.messagebox.showinfo = lambda *a, **k: errors.append(a[1])
pf.messagebox.showerror = lambda *a, **k: errors.append(a[1])

NEW = updater.Release("9.0.0", "http://127.0.0.1:9/app", 63_925_592, "ab" * 32)
net = {"latest": updater.Release(V, "http://127.0.0.1:9/app"), "check_error": None, "install_error": None,
       "checks": 0, "installs": [], "starts": 0, "start_error": None, "slow": 0.0}


def fake_fetch():
    net["checks"] += 1
    time.sleep(net["slow"])
    if net["check_error"]:
        raise updater.UpdateError(net["check_error"])
    return net["latest"]


def fake_install(release, progress=None, **k):
    net["installs"].append(release.version)
    for i in range(1, 11):
        time.sleep(0.1)
        progress(i / 10)
    if net["install_error"]:
        raise updater.UpdateError(net["install_error"])


def fake_relaunch(*a, **k):
    if net["start_error"]:
        raise updater.UpdateError(net["start_error"])
    net["starts"] += 1


app._update_fetch, app._update_install, app._update_relaunch = fake_fetch, fake_install, fake_relaunch


def until(cond, limit=15.0):
    end = time.time() + limit
    while time.time() < end:
        root.update(); time.sleep(0.02)
        if cond():
            return
    raise AssertionError("timed out")


def bar():
    """What the notification shows: (text, action button or None, close button), or None when hidden."""
    if not app.update_bar.winfo_ismapped():
        return None
    action = str(app.update_action.cget("text")) if app.update_action.winfo_ismapped() else None
    return str(app.update_text.cget("text")), action, str(app.update_close.cget("text"))


def saved():
    return json.loads((Path(os.environ["APPDATA"]) / "PixelForge" / "settings.json").read_text(encoding="utf-8"))


def fresh(**changes):
    """Forget what earlier steps found, as at a new start."""
    until(lambda: not app.busy())
    app._update_found = app._update_installed = None
    app.settings.pop("updated_to", None)
    app.hide_update_bar()
    net.update(latest=NEW, check_error=None, install_error=None, slow=0.0)
    net.update(changes)
    pump(0.1)


# 1. Run from source (as here), nothing about updates shows; enabled, the button joins the status bar
pump()
assert not app.update_btn.winfo_ismapped() and bar() is None and net["checks"] == 0
assert app.auto_update_var.get() is True, "updating automatically is the default"
app.enable_updates(check=False); pump()
assert app.update_btn.winfo_ismapped() and app.status.winfo_ismapped()
assert app.update_btn.winfo_rootx() > app.status.winfo_rootx() and str(app.update_btn.cget("text")) == "Check for Updates"
assert not squashed(), squashed()
print("Check for Updates: hidden until the app can update itself, then at the right end of the status bar")

# 2. Asked for, and this is the newest: a progress bar while it looks, then the answer in the notification bar
net["slow"] = 0.9
app.check_for_updates()
assert app.busy()
until(lambda: W.frame.winfo_ismapped())
assert W.label.cget("text").startswith("Checking for updates..."), W.label.cget("text")
assert app.update_btn.winfo_ismapped(), "the button stays put beside the progress bar"
app.check_for_updates(); pump(0.1)                       # clicking again meanwhile: no second check
assert net["checks"] == 1
until(lambda: not app.busy() and not W.frame.winfo_ismapped())
assert bar() == (f"You have the newest version (Pixel Forge {V}).", None, "Close"), bar()
assert not squashed(), squashed()
capture("newest.png")
app.update_close.invoke(); pump(0.1)
assert bar() is None
print(f"asked, up to date: 'Checking for updates...' bar, then '{f'You have the newest version (Pixel Forge {V}).'}'")

# 3. The check fails: the reason, and Try Again
fresh(check_error="Couldn't check for updates (no route to host). Check the internet connection.")
app.check_for_updates(); until(lambda: not app.busy())
assert bar() == (net["check_error"], "Try Again", "Close"), bar()
net["check_error"] = None; net["latest"] = updater.Release(V, "x")
app.update_action.invoke(); until(lambda: not app.busy())
assert bar()[0].startswith("You have the newest version")
print("a failed check says why, with Try Again")

# 4. The startup check is quiet: up to date or offline, nothing appears at all
fresh(latest=updater.Release(V, "x"))
n = net["checks"]
app.check_for_updates(quiet=True); pump(0.6)
assert net["checks"] == n + 1 and bar() is None and not W.frame.winfo_ismapped()
fresh(check_error="offline")
app.check_for_updates(quiet=True); until(lambda: not app.busy()); pump(0.2)
assert bar() is None and not errors and not asked
# ... but Check for Updates clicked while it is still looking gets its answer (and a progress bar)
fresh(latest=updater.Release(V, "x"), slow=1.2)
n = net["checks"]
app.check_for_updates(quiet=True); pump(0.2)
app.update_btn.invoke()
until(lambda: W.frame.winfo_ismapped())
assert W.label.cget("text").startswith("Checking for updates...")
until(lambda: not app.busy() and not W.frame.winfo_ismapped())
assert net["checks"] == n + 1 and bar() and bar()[0].startswith("You have the newest version"), bar()
print("the startup check says nothing when there is no update, or no internet (unless asked meanwhile)")

# 5. A newer version, updating automatically (the default): downloaded with a progress bar, then Restart Now
fresh()
update_ui.STARTUP_CHECK_MS = 50
n = net["checks"]
app.enable_updates()                                     # (as main() does: the check follows by itself)
until(lambda: net["checks"] == n + 1 and app._update_job is not None and net["installs"])
assert bar() == ("Pixel Forge 9.0.0 is available: downloading it (64 MB)...", None, "Hide"), bar()
until(lambda: W.frame.winfo_ismapped())
words, mode, value = W.label.cget("text"), str(W.progress.cget("mode")), float(W.progress.cget("value"))
assert words.startswith("Downloading Pixel Forge 9.0.0...") and mode == "determinate" and value > 0, (words, mode, value)
capture("downloading.png")
assert not squashed(), squashed()
until(lambda: not app.busy() and not W.frame.winfo_ismapped())
assert bar() == ("Pixel Forge 9.0.0 is installed. Restart to use it.", "Restart Now", "Later"), bar()
assert net["installs"] == ["9.0.0"] and saved()["updated_to"] == "9.0.0" and not asked and not errors
assert "update" not in W.times, "the download has real progress: no typical time is learnt"
capture("installed.png")
for size in ("900x720", "1280x800", "1140x800"):
    root.geometry(f"{size}+40+40"); pump(0.4)
    assert not squashed(), (size, squashed())
print("newer version at startup: notification, download with a filling bar, then 'installed. Restart to use it.'")

# 6. Later hides the notification; Check for Updates brings it back without looking again or downloading again
app.update_close.invoke(); pump(0.1)
assert bar() is None
n = net["checks"]
app.update_btn.invoke(); pump(0.2)
assert bar()[1] == "Restart Now" and net["checks"] == n and net["installs"] == ["9.0.0"]
print("Later hides it; Check for Updates shows 'installed' again (no second download)")

# 7. Restart Now: with work in the window it asks first; No stays
axe = sorted(IMAGES.glob("5d5f*"))[0]
app.load_image(axe); pump()
app.update_action.invoke(); pump(0.1)
assert len(asked) == 1 and "Restart Pixel Forge now?" in asked[0] and "haven't saved" in asked[0]
assert net["starts"] == 0 and root.winfo_exists()
net["start_error"] = "The updated Pixel Forge couldn't be started (Exec format error). Start it again yourself."
answer["yes"] = True
app.update_action.invoke(); pump(0.1)
assert bar() == (net["start_error"], None, "Close") and root.winfo_exists() and net["starts"] == 0
net["start_error"] = None
print("Restart Now asks before losing unsaved work; a restart that can't happen says so and keeps the window")

# 8. Already installed once, and this copy still isn't it: say so, but don't download at every start
fresh()
app.settings["updated_to"] = "9.0.0"
n = len(net["installs"])
app.check_for_updates(quiet=True); until(lambda: not app.busy()); pump(0.2)
assert bar() == (f"Pixel Forge 9.0.0 is available (you have {V}).", "Update Now", "Later"), bar()
assert len(net["installs"]) == n
print("a version that was installed before isn't downloaded again by itself")

# 9. Update automatically unticked: only told, with Update Now; the choice is kept
fresh()
app.update_auto.invoke(); pump(0.1)
assert app.auto_update_var.get() is False and saved()["auto_update"] is False
n = len(net["installs"])
app.check_for_updates(quiet=True); until(lambda: not app.busy()); pump(0.2)
assert bar() == (f"Pixel Forge 9.0.0 is available (you have {V}).", "Update Now", "Later"), bar()
assert len(net["installs"]) == n, "nothing is downloaded until asked"
capture("available.png")
assert not squashed(), squashed()

# ... and a download that fails says why, with Try Again; nothing counts as installed
net["install_error"] = "The update couldn't be downloaded (timed out). Check the internet connection and try again."
app.update_action.invoke()
until(lambda: not app.busy())
assert bar() == (net["install_error"], "Try Again", "Close") and app._update_installed is None
assert "updated_to" not in saved()
net["install_error"] = None
app.update_action.invoke()
until(lambda: not app.busy())
assert bar()[1] == "Restart Now" and app._update_installed == "9.0.0"
app.update_auto.invoke(); pump(0.1)
assert saved()["auto_update"] is True
print("unticked: 'is available' with Update Now; a failed download says why and Try Again finishes it")

# 10. --update and --version, with no window
out = io.StringIO()
with redirect_stdout(out):
    assert pf.update_cli() == 1
assert "Only the installed Linux app updates itself" in out.getvalue()
real = (updater.supported, updater.latest_release, updater.install)
updater.supported = lambda: True
updater.latest_release = lambda: updater.Release(V, "x")
with redirect_stdout(io.StringIO()) as out:
    assert pf.update_cli() == 0 and f"Pixel Forge {V} is the newest version." in out.getvalue()
updater.latest_release = lambda: NEW
updater.install = lambda release, progress=None: [progress(i / 10) for i in range(11)]
with redirect_stdout(io.StringIO()) as out:
    assert pf.update_cli() == 0
text = out.getvalue()
assert f"Downloading Pixel Forge 9.0.0 (you have {V})" in text and "100%" in text and "is installed" in text, text


def broken(release, progress=None):
    raise updater.UpdateError("The downloaded update is damaged (it doesn't match the expected file). Try again.")


updater.install = broken
with redirect_stdout(io.StringIO()) as out:
    assert pf.update_cli() == 1 and "damaged" in out.getvalue()
updater.supported, updater.latest_release, updater.install = real
print("--update: prints progress and the result; exit code 0 / 1")

# 11. The copy an update started says what happened; Restart Now (nothing unsaved asked twice) starts it and closes
os.environ[updater.UPDATED_FROM] = "1.1.0"
app.enable_updates(check=False); pump(0.1)
assert app.status_full == f"Pixel Forge was updated from 1.1.0 to {V}.", app.status_full
del os.environ[updater.UPDATED_FROM]
n = len(asked)
app.update_action.invoke()
assert len(asked) == n + 1 and net["starts"] == 1
try:
    root.winfo_exists()
    raise AssertionError("the window should be gone")
except tk.TclError:
    pass
print("after an update the status line says so; Restart Now starts the new app and closes this one")
print("ALL OK")
