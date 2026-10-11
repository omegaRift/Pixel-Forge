"""
What differs between Windows and Linux (the Steam Deck), in one place: the
font, where settings are kept, the mouse wheel, opening a folder, and fitting
the window to the screen. The rest of the app just calls these.
"""

import os
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"

# The app's fixed-width font. On Linux it's DejaVu Sans Mono: the packaged
# app carries its own copy (see use_bundled_fonts), so the layout is the same
# on every system; from source, fontconfig substitutes if it isn't installed.
MONO = "Consolas" if WINDOWS else "Menlo" if sys.platform == "darwin" else "DejaVu Sans Mono"


def pt(size: int) -> int:
    """A font size for this system. The layout is designed around Consolas;
    DejaVu Sans Mono is about a tenth wider at the same size, so on Linux
    sizes are a tenth smaller (10 -> 9) and the text takes the same room."""
    return size if WINDOWS or sys.platform == "darwin" else round(size * 0.9)


def use_bundled_fonts(app_dir: Path) -> bool:
    """Linux, before Tk starts: make the fonts in <app_dir>/fonts (the
    packaged app has them) available to this process only, by pointing
    fontconfig at a config that adds that folder to the system's fonts.
    True if it did."""
    fonts = Path(app_dir) / "fonts"
    if WINDOWS or sys.platform == "darwin" or not fonts.is_dir():
        return False
    conf = fonts / "fonts.conf"
    try:
        conf.write_text('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n'
                        '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
                        f'  <dir>{fonts}</dir>\n</fontconfig>\n', encoding="utf-8")
    except OSError:
        return False
    os.environ["FONTCONFIG_FILE"] = str(conf)
    return True


def config_dir() -> Path:
    """Where Pixel Forge keeps its settings and palette library:
    %APPDATA%\\PixelForge on Windows, ~/.config/PixelForge on Linux (or
    wherever XDG_CONFIG_HOME says). APPDATA wins anywhere it is set, which
    is how the tests point the app at scratch settings."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "PixelForge"
    if WINDOWS:
        return Path.home() / "PixelForge"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "PixelForge"


def open_folder(path) -> bool:
    """Show a folder in the system's file manager. False if that can't be done."""
    try:
        if WINDOWS:
            os.startfile(path)  # Explorer
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def bind_wheel(widget, handler, everywhere: bool = False, add=None):
    """Bind the mouse wheel: handler(event) with event.delta > 0 for "up".
    Windows sends <MouseWheel>; Tk 8.6 on X11 sends buttons 4 and 5 instead,
    which are given a delta here so the handler needn't care."""
    bind = widget.bind_all if everywhere else widget.bind
    bind("<MouseWheel>", handler, add=add)
    if widget.tk.call("tk", "windowingsystem") == "x11":
        def turned(delta):
            def on_button(event):
                event.delta = delta
                return handler(event)
            return on_button
        bind("<Button-4>", turned(120), add=add)
        bind("<Button-5>", turned(-120), add=add)


def fit_window(root, width: int, height: int, min_width: int, min_height: int):
    """Open at width x height, or as much of that as the screen has room for
    (a Steam Deck is 1280x800, before its panel and the title bar), and
    never demand a minimum bigger than that."""
    w = min(width, root.winfo_screenwidth() - 20)
    h = min(height, root.winfo_screenheight() - 80)
    root.geometry(f"{w}x{h}")
    root.minsize(min(min_width, w), min(min_height, h))
