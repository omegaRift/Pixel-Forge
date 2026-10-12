"""
The AI background-removal model (ISNet "general use") without rembg: finding
it, downloading it once, and running it.

rembg is a convenient wrapper, but it brings hundreds of MB of libraries. For
this model all it does is resize the picture to 1024x1024, run the network,
and scale the result back - which needs only onnxruntime and numpy. Those are
small enough to ship inside the packaged app (the Steam Deck build), and
`Session.mask` below does exactly what rembg does, so the result is the same.

The model itself is 179 MB, too big to ship: it is downloaded once, when the
user agrees to it, into the app's data folder. After that everything runs
offline.
"""

import hashlib
import importlib.util
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from platform_support import data_dir

MODEL = "isnet-general-use"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx"
MODEL_BYTES = 178_648_008
MODEL_SHA256 = "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a"
MODEL_MB = round(MODEL_BYTES / 1_000_000)

APP_DIR = Path(__file__).resolve().parent
# Where rembg looks for it (with U2NET_HOME = the app folder): install-ai.bat puts it here.
APP_MODEL = APP_DIR / "models" / MODEL / f"{MODEL}.onnx"


class ModelError(Exception):
    """Something the user should be told, in words."""


def frozen() -> bool:
    """Running as the packaged one-file app (its own folder is temporary)."""
    return bool(getattr(sys, "frozen", False))


def data_model() -> Path:
    return data_dir() / "models" / f"{MODEL}.onnx"


def model_file() -> Path | None:
    """The model, wherever it is, or None."""
    for path in (APP_MODEL, data_model()):
        if path.is_file():
            return path
    return None


def download_target() -> Path:
    """Where a download goes: the data folder for the packaged app (its own
    folder doesn't last), else next to the app, where rembg finds it too."""
    return data_model() if frozen() else APP_MODEL


def has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def engine() -> str | None:
    """What can run the model: "rembg" (if installed and the model is where
    it looks), else "onnxruntime" (direct), else None."""
    if has("rembg") and APP_MODEL.is_file():
        return "rembg"
    if has("onnxruntime") and has("numpy"):
        return "onnxruntime"
    return None


def can_download() -> bool:
    """AI would work if only the model were here: offer to download it."""
    return model_file() is None and has("onnxruntime") and has("numpy")


# --------------------------------------------------------------------------
# Downloading
# --------------------------------------------------------------------------

def _ssl_context():
    """Certificates from certifi when it's there (the packaged app carries
    it), so the download doesn't depend on how the system stores its own."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def download_model(progress=None, url: str = MODEL_URL, target: Path | None = None,
                   sha256: str | None = MODEL_SHA256, should_stop=None,
                   what: str = "AI model", total: int = MODEL_BYTES) -> Path:
    """Download the model to `target` (default: download_target()), calling
    progress(0..1) as it goes. The file only appears under its real name
    once it is complete and its checksum matches. Raises ModelError, in
    words, if it couldn't.

    The app's updater downloads with this too: `what` is the thing's name in
    the messages, `total` its size if the server doesn't say."""
    target = Path(target) if target else download_target()
    part = target.with_name(target.name + ".part")
    digest, done = hashlib.sha256(), 0
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "PixelForge"})
        with urllib.request.urlopen(request, context=_ssl_context(), timeout=30) as response, open(part, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0) or total
            while True:
                if should_stop is not None and should_stop():
                    raise ModelError("The download was cancelled.")
                block = response.read(1 << 18)
                if not block:
                    break
                out.write(block)
                digest.update(block)
                done += len(block)
                if progress is not None:
                    progress(min(1.0, done / total))
    except ModelError:
        part.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:
        part.unlink(missing_ok=True)
        reason = getattr(exc, "reason", None) or exc
        raise ModelError(f"The {what} couldn't be downloaded ({reason}). "
                         "Check the internet connection and try again.") from exc
    if sha256 and digest.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise ModelError(f"The downloaded {what} is damaged (it doesn't match the expected file). Try again.")
    os.replace(part, target)
    return target


# --------------------------------------------------------------------------
# Running it (what rembg's DisSession does, with onnxruntime and numpy only)
# --------------------------------------------------------------------------

class Session:
    SIZE = (1024, 1024)  # what the network was trained at

    def __init__(self, model: Path | None = None):
        model = model or model_file()
        if model is None:
            raise ModelError("The AI model isn't downloaded yet.")
        import onnxruntime  # heavy imports: only when AI is used
        self._session = onnxruntime.InferenceSession(str(model), providers=["CPUExecutionProvider"])

    def mask(self, img: Image.Image) -> Image.Image:
        """The subject mask for a picture: 'L', the picture's size, white = subject."""
        import numpy as np
        small = img.convert("RGB").resize(self.SIZE, Image.Resampling.LANCZOS)
        pixels = np.array(small)
        pixels = pixels / max(np.max(pixels), 1e-6)
        pixels = (pixels - 0.5) / 1.0                      # mean 0.5, std 1 on every channel
        feed = np.expand_dims(pixels.transpose((2, 0, 1)), 0).astype(np.float32)
        out = self._session.run(None, {self._session.get_inputs()[0].name: feed})
        pred = out[0][:, 0, :, :]
        low, high = np.min(pred), np.max(pred)
        pred = np.squeeze((pred - low) / (high - low))
        mask = Image.fromarray((pred * 255).astype("uint8"))
        return mask.resize(img.size, Image.Resampling.LANCZOS)
