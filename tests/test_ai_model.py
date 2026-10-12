"""ai_model: finding, downloading and running the AI background-removal model without rembg.
No window needed. The download is tested against a small local web server; the real model is
only used if it's already on this machine."""
import hashlib
import http.server
import os
import shutil
import threading
import time
from functools import partial

from PIL import Image, ImageChops

from _paths import APP, IMAGES, SCR  # (this also puts the app on sys.path)

work = SCR / "ai_model"
shutil.rmtree(work, ignore_errors=True)
(work / "served").mkdir(parents=True)
os.environ["PIXEL_FORGE_DATA_DIR"] = str(work / "data")
import ai_model as am  # noqa: E402
import platform_support as ps  # noqa: E402

# 1. Where things go
assert ps.data_dir() == work / "data" and am.data_model() == work / "data" / "models" / "isnet-general-use.onnx"
assert am.download_target() == am.APP_MODEL, "from source: next to the app (where rembg looks too)"
am.frozen = lambda: True
assert am.download_target() == am.data_model(), "the packaged app: the data folder (its own folder is temporary)"
am.frozen = lambda: False
print("model locations OK")

# 2. Downloading, against a local server: progress, checksum, and a clean failure
payload = os.urandom(700_000)
(work / "served" / "model.onnx").write_bytes(payload)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Server(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass  # (a download this test cuts short: nothing to report, and nothing to print while Python closes)


server = Server(("127.0.0.1", 0), partial(Quiet, directory=str(work / "served")))
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_address[1]}/model.onnx"
target = work / "data" / "models" / "isnet-general-use.onnx"
seen = []
got = am.download_model(progress=seen.append, url=url, target=target, sha256=hashlib.sha256(payload).hexdigest())
assert got == target and target.read_bytes() == payload
assert seen and seen[-1] == 1.0 and seen == sorted(seen) and len(seen) >= 2, seen
assert not target.with_name(target.name + ".part").exists()
print(f"download: {len(payload):,} bytes, progress in {len(seen)} steps up to 100%, checksum verified")

target.unlink()
for label, kwargs, words in (
        ("wrong checksum", dict(url=url, sha256="0" * 64), "damaged"),
        ("missing file", dict(url=url.replace("model.onnx", "nope.onnx"), sha256=None), "couldn't be downloaded"),
        ("no server", dict(url="http://127.0.0.1:9/model.onnx", sha256=None), "couldn't be downloaded"),
        ("cancelled", dict(url=url, sha256=None, should_stop=lambda: True), "cancelled")):
    try:
        am.download_model(target=target, **kwargs)
        raise AssertionError(f"{label}: no error")
    except am.ModelError as exc:
        assert words in str(exc), (label, str(exc))
    assert not target.exists() and not target.with_name(target.name + ".part").exists(), f"{label}: nothing left behind"
print("failed downloads say why in words and leave no half file")
server.shutdown()

# 3. can_download: only when the engine is here and the model isn't
real_has, real_app_model = am.has, am.APP_MODEL
am.APP_MODEL = work / "no" / "model.onnx"
am.has = lambda m: m in ("onnxruntime", "numpy")
assert am.model_file() is None and am.can_download() and am.engine() == "onnxruntime"
am.has = lambda m: False
assert not am.can_download() and am.engine() is None
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(b"x")
am.has = lambda m: m in ("onnxruntime", "numpy")
assert am.model_file() == target and not am.can_download(), "the model is here: nothing to download"
target.unlink()
am.has, am.APP_MODEL = real_has, real_app_model
print("can_download / engine OK")

# 4. The real model, if this machine has it: the direct path gives what rembg gives
model = am.model_file()
if model is None or not (am.has("onnxruntime") and am.has("numpy")):
    print("SKIPPED the model run: the model or onnxruntime isn't on this machine")
else:
    session = am.Session(model)
    pictures = sorted(IMAGES.glob("*.jpg"))[:3]
    for path in pictures:
        img = Image.open(path).convert("RGB")
        img.thumbnail((1024, 1024))
        t = time.perf_counter()
        mask = session.mask(img)
        seconds = time.perf_counter() - t
        assert mask.mode == "L" and mask.size == img.size
        lo, hi = mask.getextrema()
        assert lo < 30 and hi > 225, (path.name, lo, hi)  # it found a subject and a background
        note = ""
        if am.has("rembg") and am.APP_MODEL.is_file():
            os.environ["U2NET_HOME"] = str(APP)
            from rembg import new_session, remove
            if "rembg_session" not in globals():
                rembg_session = new_session(am.MODEL)
            theirs = remove(img, session=rembg_session, only_mask=True).convert("L")
            diff = ImageChops.difference(mask, theirs).getextrema()[1]
            assert diff <= 1, (path.name, "differs from rembg by", diff)
            note = f", same as rembg (largest difference {diff} of 255)"
        print(f"  {path.name[:24]:24} mask in {seconds:.1f} s{note}")
    print("the model runs without rembg")
print("ALL OK")
