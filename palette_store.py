"""
The palette library: colour palettes saved from textures, kept in a small
SQLite database so any project (or Grass Block edit session) can open them.

    %APPDATA%\\PixelForge\\palettes.db   (~/.config/PixelForge on Linux)
        palettes(id, name UNIQUE (any case), colours, source, created, updated)

`colours` is a JSON list of "#rrggbbaa" strings, most-used first. No app
logic here: the UI is palette_ui.py. Also the colour maths for recolouring
a picture to a palette (nearest colour, alpha kept).
"""

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from platform_support import config_dir

MAX_COLOURS = 256  # a palette keeps at most this many (the most used)


def default_path() -> Path:
    """Next to Pixel Forge's settings, in the user's own config folder."""
    return config_dir() / "palettes.db"


@dataclass(frozen=True)
class Palette:
    id: int
    name: str
    colours: tuple      # RGBA tuples, most-used first
    source: str         # where it was saved from (a file name), may be ""
    created: str        # ISO timestamps
    updated: str


class NameTaken(Exception):
    """A palette with this name (in any case) already exists."""


def to_hex(rgba) -> str:
    return "#%02x%02x%02x%02x" % tuple(rgba)


def from_hex(text: str) -> tuple:
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) for i in range(0, 8, 2))


def colours_of(img: Image.Image) -> list[tuple]:
    """The visible colours of a picture, most-used first (see-through pixels
    aren't colours). At most MAX_COLOURS."""
    counts = [cc for cc in (img.convert("RGBA").getcolors(img.width * img.height) or []) if cc[1][3]]
    counts.sort(key=lambda cc: -cc[0])
    return [rgba for _, rgba in counts[:MAX_COLOURS]]


class PaletteStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_path()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path)
        con.execute("""CREATE TABLE IF NOT EXISTS palettes (
                           id INTEGER PRIMARY KEY,
                           name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                           colours TEXT NOT NULL,
                           source TEXT NOT NULL DEFAULT '',
                           created TEXT NOT NULL,
                           updated TEXT NOT NULL)""")
        return con

    @staticmethod
    def _row(row) -> Palette:
        pid, name, colours, source, created, updated = row
        return Palette(pid, name, tuple(from_hex(c) for c in json.loads(colours)), source, created, updated)

    def save(self, name: str, colours, source: str = "", replace: bool = False) -> Palette:
        """Save a palette. An existing name raises NameTaken, unless replace=True
        (then that palette's colours and source are updated, its name kept)."""
        name = name.strip()
        if not name:
            raise ValueError("a palette needs a name")
        colours = [tuple(c) for c in colours][:MAX_COLOURS]
        if not colours:
            raise ValueError("there are no colours to save")
        data = json.dumps([to_hex(c) for c in colours])
        now = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as con, con:
            found = con.execute("SELECT id FROM palettes WHERE name = ?", (name,)).fetchone()
            if found and not replace:
                raise NameTaken(name)
            if found:
                con.execute("UPDATE palettes SET colours = ?, source = ?, updated = ? WHERE id = ?",
                            (data, source, now, found[0]))
                pid = found[0]
            else:
                pid = con.execute("INSERT INTO palettes (name, colours, source, created, updated) "
                                  "VALUES (?, ?, ?, ?, ?)", (name, data, source, now, now)).lastrowid
        return self.get(pid)

    def all(self) -> list[Palette]:
        """Every palette, most recently saved first."""
        with closing(self._connect()) as con:
            rows = con.execute("SELECT id, name, colours, source, created, updated FROM palettes "
                               "ORDER BY updated DESC, id DESC").fetchall()
        return [self._row(r) for r in rows]

    def get(self, pid: int) -> Palette | None:
        with closing(self._connect()) as con:
            row = con.execute("SELECT id, name, colours, source, created, updated FROM palettes WHERE id = ?",
                              (pid,)).fetchone()
        return self._row(row) if row else None

    def rename(self, pid: int, name: str) -> Palette:
        name = name.strip()
        if not name:
            raise ValueError("a palette needs a name")
        with closing(self._connect()) as con, con:
            other = con.execute("SELECT id FROM palettes WHERE name = ? AND id != ?", (name, pid)).fetchone()
            if other:
                raise NameTaken(name)
            con.execute("UPDATE palettes SET name = ? WHERE id = ?", (name, pid))
        return self.get(pid)

    def delete(self, pid: int) -> None:
        with closing(self._connect()) as con, con:
            con.execute("DELETE FROM palettes WHERE id = ?", (pid,))


# --------------------------------------------------------------------------
# Recolouring to a palette
# --------------------------------------------------------------------------

def _distance(a, b) -> float:
    """How different two colours look ("redmean": cheap, close to perceived)."""
    r = (a[0] + b[0]) / 2
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return (2 + r / 256) * dr * dr + 4 * dg * dg + (2 + (255 - r) / 256) * db * db


def nearest(rgb, palette) -> tuple:
    """The palette colour that looks closest to rgb (its RGB only)."""
    return min(palette, key=lambda p: _distance(rgb, p))[:3]


def recolour(img: Image.Image, palette) -> Image.Image:
    """Every visible pixel moved to the nearest palette colour; each pixel
    keeps its own alpha, and see-through pixels stay as they are."""
    opaque = [c for c in palette if c[3]] or list(palette)
    data = bytearray(img.convert("RGBA").tobytes())
    cache = {}
    for j in range(0, len(data), 4):
        if not data[j + 3]:
            continue
        rgb = bytes(data[j:j + 3])
        if rgb not in cache:
            cache[rgb] = bytes(nearest(tuple(rgb), opaque))
        data[j:j + 3] = cache[rgb]
    return Image.frombytes("RGBA", img.size, bytes(data))
