"""
Updating the installed app (the one-file Linux / Steam Deck build) from the
repository's newest release: looking it up, downloading it over the app's
own file, and starting the new one.

Only the packaged app updates itself. Run from its source folder (as on the
Windows PC it is developed on), Pixel Forge is whatever that folder holds,
and `supported()` is False.

No window here: update_ui.py shows the notification and the progress bar.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import ai_model

VERSION = "1.2.0"   # this Pixel Forge. A release's tag must be "v" + this (the build checks it)
REPO = "omegaRift/Pixel-Forge"
ASSET = "PixelForge-linux-x86_64"   # the release file this app is
API = f"https://api.github.com/repos/{REPO}/releases/latest"
UPDATED_FROM = "PIXEL_FORGE_UPDATED_FROM"   # set for the copy started after an update: the old version


class UpdateError(Exception):
    """Something the user should be told, in words."""


@dataclass(frozen=True)
class Release:
    version: str               # "1.3.0"
    url: str                   # the app file's download address
    size: int = 0              # its size in bytes (0: not known)
    sha256: str | None = None  # its checksum, when GitHub gives one

    @property
    def megabytes(self) -> int:
        return round(self.size / 1_000_000)


def parse(version: str) -> tuple[int, ...] | None:
    """'v1.10.2' -> (1, 10, 2). None for anything that isn't numbers and dots."""
    parts = str(version).strip().lstrip("vV").split(".")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def is_newer(latest: str, current: str = VERSION) -> bool:
    """`latest` is a later version than `current` (1.10 is later than 1.9)."""
    a, b = parse(latest), parse(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def app_file() -> Path | None:
    """The installed one-file app this is running from, or None when it isn't
    one (run from source) or its folder can't be written to."""
    if not getattr(sys, "frozen", False) or not sys.platform.startswith("linux"):
        return None
    path = Path(sys.executable).resolve()
    if not path.is_file() or not os.access(path.parent, os.W_OK):
        return None
    return path


def supported() -> bool:
    return app_file() is not None


def latest_release(api: str | None = None, timeout: float = 10) -> Release:
    """The newest published release. Raises UpdateError, in words, if it
    can't be read. PIXEL_FORGE_UPDATE_API points it elsewhere (the build's
    own check uses that)."""
    api = api or os.environ.get("PIXEL_FORGE_UPDATE_API") or API
    request = urllib.request.Request(api, headers={"User-Agent": "PixelForge",
                                                   "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, context=ai_model._ssl_context(), timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise UpdateError(f"Couldn't check for updates ({reason}). Check the internet connection.") from exc
    try:
        version = str(data["tag_name"]).lstrip("vV")
        asset = next(a for a in data.get("assets", []) if a.get("name") == ASSET)
        url = asset["browser_download_url"]
    except (KeyError, TypeError, StopIteration) as exc:
        raise UpdateError("Couldn't check for updates: the newest release has no Linux app file.") from exc
    if parse(version) is None:
        raise UpdateError(f"Couldn't check for updates: the newest release has an odd name ({version}).")
    digest = str(asset.get("digest") or "")
    return Release(version, url, int(asset.get("size") or 0),
                   digest.removeprefix("sha256:") if digest.startswith("sha256:") else None)


def install(release: Release, progress=None, should_stop=None, target: Path | None = None) -> Path:
    """Download the release and put it in place of the app (default target:
    app_file()), calling progress(0..1) as it goes. The app's file is only
    replaced, in one step, by a complete download that checks out: until
    then nothing changes. The running copy keeps working either way.
    Raises UpdateError, in words, if it couldn't."""
    target = Path(target) if target else app_file()
    if target is None:
        raise UpdateError("This copy of Pixel Forge can't update itself.")
    new = target.with_name(target.name + ".new")
    try:
        ai_model.download_model(progress=progress, url=release.url, target=new, sha256=release.sha256,
                                should_stop=should_stop, what="update", total=release.size or 1)
    except ai_model.ModelError as exc:
        raise UpdateError(str(exc)) from exc
    try:
        with open(new, "rb") as f:
            start = f.read(4)
        # A Linux program starts with 7f 'E' 'L' 'F': anything else is an error page, not the app.
        if start != b"\x7fELF" or (release.size and new.stat().st_size != release.size):
            raise UpdateError("The downloaded update isn't the app (it may have been cut short). "
                              "Nothing was changed. Try again.")
        os.chmod(new, 0o755)
        os.replace(new, target)
        try:  # (the installer keeps the version here too; the app itself doesn't read it)
            target.with_name("version").write_text(f"v{release.version}\n", encoding="utf-8")
        except OSError:
            pass
    except OSError as exc:
        raise UpdateError(f"The update couldn't be put in place ({exc}). Nothing was changed.") from exc
    finally:
        new.unlink(missing_ok=True)
    return target


def relaunch(args=(), target: Path | None = None, popen=subprocess.Popen):
    """Start the (updated) app as its own program; the caller then closes this
    one. The packaged app unpacks itself into a temporary folder and tells
    its own child where through the environment: the new copy must not
    inherit that, or it would run the old files."""
    target = Path(target) if target else app_file()
    if target is None:
        raise UpdateError("This copy of Pixel Forge can't restart itself.")
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for key in [k for k in env if k.startswith("_PYI_") or k == "_MEIPASS2"]:
        del env[key]
    if "LD_LIBRARY_PATH_ORIG" in env:      # (what it was before the packaged app changed it)
        env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    elif getattr(sys, "frozen", False):
        env.pop("LD_LIBRARY_PATH", None)
    for key in ("TCL_LIBRARY", "TK_LIBRARY", "FONTCONFIG_FILE"):   # these point into the old temporary folder
        env.pop(key, None)
    env[UPDATED_FROM] = VERSION
    try:
        return popen([str(target), *map(str, args)], env=env, start_new_session=True, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise UpdateError(f"The updated Pixel Forge couldn't be started ({exc}). Start it again yourself.") from exc


def updated_from() -> str | None:
    """The version this copy replaced, if it was just started by an update."""
    return os.environ.get(UPDATED_FROM) or None
