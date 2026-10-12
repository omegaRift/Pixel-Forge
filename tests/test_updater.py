"""updater: finding the newest release, putting it in place of the app, and starting it.
No window needed, and no real network: releases are served by a small local web server,
and "the app" is a file in the scratch folder."""
import hashlib
import http.server
import json
import os
import shutil
import sys
import threading
from functools import partial

from _paths import APP, SCR  # (this also puts the app on sys.path)

import updater as up  # noqa: E402

work = SCR / "updater"
shutil.rmtree(work, ignore_errors=True)
served = work / "served"
served.mkdir(parents=True)

# 1. Versions
assert up.parse("v1.10.2") == (1, 10, 2) and up.parse("1.2") == (1, 2) and up.parse("V3") == (3,)
assert up.parse("nightly") is None and up.parse("1.2-beta") is None and up.parse("") is None
assert up.is_newer("1.10.0", "1.9.9") and up.is_newer("v2.0", "1.99.99") and up.is_newer("1.2.1", "1.2")
assert not up.is_newer("1.2.0", "1.2.0") and not up.is_newer("1.2", "1.2.0") and not up.is_newer("1.1.9", "1.2.0")
assert not up.is_newer("nightly", "1.0.0") and not up.is_newer("9.9.9", "dev"), "an unreadable version is never 'newer'"
assert up.parse(up.VERSION) is not None and not up.is_newer(up.VERSION)
print(f"versions compare by number (1.10 is newer than 1.9); this is {up.VERSION}")

# 2. From its source folder the app doesn't update itself
assert up.app_file() is None and not up.supported()
for call in (lambda: up.install(up.Release("9.0.0", "http://127.0.0.1:9/x")), up.relaunch):
    try:
        call()
        raise AssertionError("no error")
    except up.UpdateError as exc:
        assert "can't" in str(exc)
print("run from source: not supported, and install/relaunch refuse in words")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(served)))
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_address[1]}"

payload = b"\x7fELF" + os.urandom(600_000)
(served / up.ASSET).write_bytes(payload)
sha = hashlib.sha256(payload).hexdigest()


def serve(name, tag="v9.1.0", assets=None, raw=None):
    if assets is None:
        assets = [{"name": "notes.txt", "browser_download_url": f"{base}/notes.txt", "size": 3},
                  {"name": up.ASSET, "browser_download_url": f"{base}/{up.ASSET}", "size": len(payload),
                   "digest": f"sha256:{sha}"}]
    (served / name).write_text(raw if raw is not None else json.dumps({"tag_name": tag, "assets": assets}),
                               encoding="utf-8")
    return f"{base}/{name}"


# 3. Reading the newest release
rel = up.latest_release(serve("latest.json"))
assert rel == up.Release("9.1.0", f"{base}/{up.ASSET}", len(payload), sha) and rel.megabytes == 1, rel
old = up.latest_release(serve("old.json", assets=[{"name": up.ASSET, "browser_download_url": f"{base}/{up.ASSET}"}]))
assert old.size == 0 and old.sha256 is None, "a release without a size or checksum still reads"
os.environ["PIXEL_FORGE_UPDATE_API"] = serve("env.json", tag="v9.2.0")
assert up.latest_release().version == "9.2.0", "PIXEL_FORGE_UPDATE_API says where to look"
del os.environ["PIXEL_FORGE_UPDATE_API"]
for label, api, words in (
        ("no Linux file", serve("empty.json", assets=[]), "no Linux app file"),
        ("odd name", serve("odd.json", tag="nightly"), "odd name"),
        ("not JSON", serve("bad.json", raw="<html>rate limited</html>"), "Couldn't check for updates"),
        ("missing", f"{base}/nope.json", "Couldn't check for updates"),
        ("no server", "http://127.0.0.1:9/latest.json", "Check the internet connection")):
    try:
        up.latest_release(api, timeout=5)
        raise AssertionError(f"{label}: no error")
    except up.UpdateError as exc:
        assert words in str(exc), (label, str(exc))
print("the newest release is read (version, file, size, checksum); every failure is said in words")

# 4. Installing: the app's file is replaced in one step, and only by a download that checks out
app_file = work / "installed" / "PixelForge"
app_file.parent.mkdir()
app_file.write_bytes(b"\x7fELF the old app")
seen = []
assert up.install(rel, progress=seen.append, target=app_file) == app_file
assert app_file.read_bytes() == payload and seen and seen[-1] == 1.0 and seen == sorted(seen)
assert (app_file.parent / "version").read_text().strip() == "v9.1.0"
assert sorted(p.name for p in app_file.parent.iterdir()) == ["PixelForge", "version"], "nothing left behind"
if sys.platform != "win32":
    assert os.access(app_file, os.X_OK), "the new app can be started"
print(f"install: {len(payload):,} bytes over the old app, progress up to 100%, version noted")

app_file.write_bytes(b"\x7fELF the old app")
(served / "page.html").write_bytes(b"<html>" + os.urandom(1000))
for label, release, words in (
        ("wrong checksum", up.Release("9.1.0", rel.url, rel.size, "0" * 64), "damaged"),
        ("an error page", up.Release("9.1.0", f"{base}/page.html"), "isn't the app"),
        ("cut short", up.Release("9.1.0", rel.url, rel.size + 5), "isn't the app"),
        ("missing", up.Release("9.1.0", f"{base}/gone"), "update couldn't be downloaded"),
        ("no server", up.Release("9.1.0", "http://127.0.0.1:9/app"), "update couldn't be downloaded")):
    try:
        up.install(release, target=app_file)
        raise AssertionError(f"{label}: no error")
    except up.UpdateError as exc:
        assert words in str(exc), (label, str(exc))
    assert app_file.read_bytes() == b"\x7fELF the old app", f"{label}: the app must be untouched"
    assert [p.name for p in app_file.parent.iterdir() if p.name not in ("PixelForge", "version")] == [], label
try:
    up.install(rel, target=app_file, should_stop=lambda: True)
    raise AssertionError("cancelled: no error")
except up.UpdateError as exc:
    assert "cancelled" in str(exc) and app_file.read_bytes() == b"\x7fELF the old app"
print("a bad download (checksum, error page, cut short, missing, cancelled) leaves the app as it was")

# 5. Starting the new app: as its own program, without this one's unpacked files
started = []
os.environ.update({"_PYI_ARCHIVE_FILE": "/tmp/old", "_MEIPASS2": "/tmp/_MEIold", "LD_LIBRARY_PATH": "/tmp/_MEIold",
                   "LD_LIBRARY_PATH_ORIG": "/usr/lib/steam", "TCL_LIBRARY": "/tmp/_MEIold/tcl",
                   "FONTCONFIG_FILE": "/tmp/_MEIold/fonts/fonts.conf"})
before = dict(os.environ)
up.relaunch(["a picture.png"], target=app_file, popen=lambda cmd, **k: started.append((cmd, k)))
cmd, k = started[0]
env = k["env"]
assert cmd == [str(app_file), "a picture.png"] and k["start_new_session"] is True
assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and env[up.UPDATED_FROM] == up.VERSION
assert not [key for key in env if key.startswith("_PYI_") or key == "_MEIPASS2"]
assert env["LD_LIBRARY_PATH"] == "/usr/lib/steam" and "LD_LIBRARY_PATH_ORIG" not in env
assert "TCL_LIBRARY" not in env and "FONTCONFIG_FILE" not in env
assert dict(os.environ) == before, "this app's own environment is left alone"
assert env["PATH"] == os.environ["PATH"]


def no_start(cmd, **k):
    raise OSError("Exec format error")


try:
    up.relaunch(target=app_file, popen=no_start)
    raise AssertionError("no error")
except up.UpdateError as exc:
    assert "couldn't be started" in str(exc) and "Start it again yourself" in str(exc)
assert up.updated_from() is None
os.environ[up.UPDATED_FROM] = "1.1.0"
assert up.updated_from() == "1.1.0"
print("relaunch: the new app starts on its own, told which version it replaced; a failure is said in words")
print("ALL OK")
