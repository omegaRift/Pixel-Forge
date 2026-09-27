"""
Edit sessions: another app (Grass Block) asks Pixel Forge to edit one texture.

The whole contract with the calling app lives here and in
docs/INTEGRATION.md. Everything else in Pixel Forge can change freely;
this handshake is versioned (PROTOCOL) and only changes deliberately.

    Pixel Forge.exe --edit <texture.png> [--name "Flesh Axe"]
                    [--result <result.json>] [--caller "Grass Block"]
    Pixel Forge.exe --edit <texture.png> --source <picture> [--transparent] [...]
    Pixel Forge.exe --describe [--result <result.json>]

With --source (mode "convert") the texture is made anew from the picture
with the pixel-art converter, at the texture's own size.

Exit code: 0 saved, 10 cancelled, 1 error (bad arguments, unreadable or
unsupported texture, couldn't save). The result file says the same thing
as JSON; it's written atomically, just before the process exits.
"""

import argparse
import json
import os
import sys
import threading
from collections import Counter
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageChops

from layers import Layer
from pixel_core import ai_status, ai_subject, detect_subject
from ui_widgets import Tooltip

PROTOCOL = 1
EXIT_SAVED, EXIT_ERROR, EXIT_CANCELLED = 0, 1, 10
MIN_SIZE, MAX_SIZE = 8, 256   # square textures only, 8x8 .. 256x256 (protocol 1)

DESCRIPTION = {
    "app": "Pixel Forge",
    "protocol": PROTOCOL,
    "modes": ["edit", "convert"],   # convert: --edit with --source (a new mode, not a protocol change)
    "formats": ["png"],
    "texture": {"square": True, "min": MIN_SIZE, "max": MAX_SIZE},
    "exit_codes": {"saved": EXIT_SAVED, "cancelled": EXIT_CANCELLED, "error": EXIT_ERROR},
}


def write_result(path, data: dict) -> None:
    """Write the result JSON atomically (temp file + rename), so the caller
    never reads half a file. Silently does nothing without a path."""
    if not path:
        return
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"protocol": PROTOCOL, **data}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class _Parser(argparse.ArgumentParser):
    """argparse, but a bad command line is reported through the protocol
    (result file + exit code 1) instead of argparse's own exit code 2."""

    def error(self, message):
        result = _peek_result_path(sys.argv[1:])
        write_result(result, {"status": "error", "message": f"bad arguments: {message}"})
        sys.exit(EXIT_ERROR)


def _peek_result_path(argv):
    for i, a in enumerate(argv):
        if a == "--result" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--result="):
            return a.split("=", 1)[1]
    return None


def parse_args(argv=None):
    p = _Parser(prog="Pixel Forge", description="Offline pixel art generator and editor.")
    p.add_argument("image", nargs="?", help="an image to open (e.g. dropped on the launcher)")
    p.add_argument("--edit", metavar="PNG", help="edit this texture for another app, then save it back")
    p.add_argument("--name", help="item name (shown in the Minecraft preview)")
    p.add_argument("--result", metavar="JSON", help="where to write the result for the calling app")
    p.add_argument("--caller", default="another app", help="name of the calling app, shown in the top bar")
    p.add_argument("--source", metavar="PICTURE",
                   help="with --edit: make the texture anew from this picture with the pixel-art converter")
    p.add_argument("--transparent", action="store_true",
                   help="with --source: start with Transparent BG ticked (e.g. an item icon)")
    p.add_argument("--describe", action="store_true", help="report the protocol version and exit")
    args = p.parse_args(argv)
    if args.source and not args.edit:
        p.error("--source needs --edit (the texture to make)")
    return args


def check_texture(path) -> Image.Image:
    """Load a texture for editing, or raise ValueError saying why not."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"file not found: {path}")
    try:
        img = Image.open(path)
        img.load()
    except Exception as exc:
        raise ValueError(f"not a readable image: {exc}") from exc
    if img.format != "PNG":
        raise ValueError(f"expected a PNG texture, got {img.format}")
    w, h = img.size
    if w != h:
        raise ValueError(f"only square textures can be edited (this one is {w}x{h})")
    if not MIN_SIZE <= w <= MAX_SIZE:
        raise ValueError(f"texture size {w}x{h} is outside {MIN_SIZE}..{MAX_SIZE} px")
    return img.convert("RGBA")


def check_source(path) -> Image.Image:
    """Load the picture a texture is made from (mode "convert"): anything
    Pillow opens, of any size (an animation's first frame), or raise
    ValueError saying why not."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"picture not found: {path}")
    try:
        img = Image.open(path)
        img.seek(0)  # an animated GIF/WebP: its first frame
        img.load()
    except Exception as exc:
        raise ValueError(f"the picture isn't a readable image: {exc}") from exc
    return img if img.mode in ("RGB", "RGBA") else img.convert("RGBA")


def _edge_colour(img: Image.Image):
    """The colour around a texture's edges (the most common, JPEG-noise
    tolerant), or None when its edges are mostly see-through already."""
    w, h = img.size
    px = img.load()
    border = [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(1, h - 1) for x in (0, w - 1)]
    opaque = [px[p][:3] for p in border if px[p][3] >= 128]
    if len(opaque) < len(border) * 0.5:
        return None
    bucket = Counter(tuple(c // 24 for c in col) for col in opaque).most_common(1)[0][0]
    members = [col for col in opaque if tuple(c // 24 for c in col) == bucket]
    return tuple(sum(col[i] for col in members) // len(members) for i in range(3))


def clear_background(img: Image.Image, method: str = "plain"):
    """Remove BG on a texture layer: (the layer with its background see-through,
    what happened), or (None, why not). "plain" takes away the colour around
    the edges, flood-filled inward (the converter's Remove BG: Plain); "ai"
    keeps the subject a neural network finds (rembg), for busy pictures. Pixel
    art keeps hard edges: each pixel is kept whole or cleared."""
    img = img.convert("RGBA")
    alpha = img.getchannel("A")
    if not alpha.point(lambda a: 255 if a >= 128 else 0).getbbox():
        return None, "This layer is empty: nothing to take a background from"
    probe = img
    if alpha.getextrema()[0] < 128:
        # Partly see-through already: the see-through pixels take the edge colour, so the
        # background still reads as one plain area around the subject.
        edge = _edge_colour(img)
        if edge is None:
            return None, "Its background is see-through already"
        probe = Image.new("RGBA", img.size, (*edge, 255))
        probe.alpha_composite(img)
    if method == "ai":
        k = max(1, 512 // max(img.size))  # the network sees pixel art better big, and crisp
        subject = ai_subject(probe.resize((img.width * k, img.height * k), Image.Resampling.NEAREST))
        mask = subject.mask.resize(img.size, Image.Resampling.BOX) if subject else None
    else:
        subject = detect_subject(probe)
        mask = subject.mask if subject else None
    if mask is None:
        return None, ("The AI found no subject in this layer" if method == "ai"
                      else "No plain background around its edges to take away (try AI)")
    kept = ImageChops.darker(alpha, mask.point(lambda m: 255 if m >= 128 else 0))
    before, after = alpha.tobytes(), kept.tobytes()
    cleared = sum(1 for a, b in zip(before, after) if a and not b)
    left = len(after) - after.count(0)
    if not cleared:
        return None, "No background found outside the subject: nothing was taken away"
    if left < max(2, (len(before) - before.count(0)) * 0.03):  # it would all go: that's no subject found
        return None, ("The AI found no subject in this layer" if method == "ai"
                      else "No subject found: it would all be taken away")
    out = img.copy()
    out.putalpha(kept)
    note = (" - at this size the AI can miss thin parts; on a plain background, Plain often does better"
            if method == "ai" and max(img.size) <= 16 else "")
    return out, f"Background removed ({'AI' if method == 'ai' else 'Plain'}): {cleared} pixels are see-through now{note}"


class EditSessionMixin:
    """The session mode of PixelForgeApp: the texture opens as-is (no
    generation), or with a picture (--source) it's made anew in the pixel-art
    converter; the top bar offers Save & Return / Cancel, and closing the
    window cancels."""

    session: dict | None = None
    texture_mode = False
    convert_mode = False
    _start_settings = None
    exit_code = EXIT_SAVED

    def start_session(self, session: dict):
        """session: {"path", "name", "result", "caller", "source", "transparent"}."""
        self.session = session
        self.root.protocol("WM_DELETE_WINDOW", self.session_cancel)
        try:
            img = check_texture(session["path"])
            source = check_source(session["source"]) if session.get("source") else None
        except ValueError as exc:
            self._session_fail(str(exc))
            return False
        self._build_session_bar()
        if source is not None:
            self.open_source(Path(session["path"]), img.width, Path(session["source"]), source)
        else:
            self.open_texture(Path(session["path"]), img)
        if session.get("name"):
            self.item_name.set(session["name"])
        return True

    def open_source(self, path: Path, size: int, source_path: Path, source: Image.Image):
        """Make the texture anew from a picture, in the pixel-art converter:
        every generation setting is there (palette, outline, Remove BG, Transparent BG,
        scale and position), the grid is fixed to the texture's own size, and
        Save & Return writes the art - every visible layer - at that size."""
        self.reset_layers()
        self.zoom, self.pan = None, [0, 0]
        self.texture_mode, self.convert_mode = False, True
        self._last = None
        self.original, self.source_path, self.region = source, source_path, None
        self.offset = [0, 0]
        self.grid_var.set(size)
        self._fix_grid(size)
        if self.session.get("transparent"):
            self.transparent_var.set(True)
        self._status_note = (f"Making {path.name} ({size}x{size}) for {self.session['caller']} from "
                             f"{source_path.name}: set the converter on the right, paint if you like, "
                             "then Save & Return (Cancel leaves it unchanged)")
        self.select_tool("move")
        self._draw_original()
        self.process()
        self._start_settings = self._key(self._settings())

    def open_texture(self, path: Path, img: Image.Image):
        """Open a finished texture for editing, exactly as it is: one plain
        layer, no pixel-art generation (which would re-blur it)."""
        self.reset_layers()
        self.zoom, self.pan = None, [0, 0]
        self.texture_mode = True
        self._last = None  # no generated result: the status shouldn't describe one
        self.original, self.source_path, self.region = img, path, None
        self.small_art = img.copy()
        self.layers = [Layer("Texture", img.copy())]  # not "live": settings never overwrite it
        self.active_layer = 0
        size = img.width
        self.art_title.configure(text=f"{size}x{size} texture  ·  editing as-is")
        self.orig_title.configure(text="Before your edits")
        self._disable_generation()
        self._refresh_display()
        self.select_tool("pen")
        self._draw_original()
        self._draw_art()
        self._draw_palette()
        self._refresh_layer_panel()
        self._set_status(f"Editing {path.name} for {self.session['caller']}  ·  "
                         "Save & Return writes it back, Cancel leaves it unchanged")

    def _disable_generation(self):
        """Generation settings (and Match Original) don't apply to an
        existing texture: hide them and say why in the Adjustments area."""
        inner = self.adjust_area.inner
        for child in inner.winfo_children():
            child.pack_forget()
        self.match_btn.place_forget()
        ttk.Label(inner, text="TEXTURE", style="Head.TLabel").pack(anchor="w")
        ttk.Label(inner, style="Muted.TLabel", justify="left", wraplength=250,
                  text="You're editing an existing texture, so the generation settings "
                       "are off: it opens exactly as it is.\n\n"
                       "Paint with the tools on the left, add layers below, then "
                       "Save & Return (Ctrl+S) to send it back.").pack(anchor="w", pady=(8, 0))
        # Remove BG, on the selected layer (the converter's own is off here)
        ttk.Label(inner, text="BACKGROUND", style="Head.TLabel").pack(anchor="w", pady=(16, 0))
        row = ttk.Frame(inner, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Remove BG").pack(side="left", padx=(0, 12))
        self.bg_buttons = []
        for text, method, tip in (
                ("Plain", "plain", "Take away the colour around the edges (a plain background)"),
                ("AI", "ai", "Keep the subject an AI finds, for busy backgrounds (takes a few seconds)")):
            button = ttk.Button(row, text=text, style="Small.TButton", width=6,
                                command=lambda m=method: self.remove_texture_background(m))
            button.pack(side="left", padx=(0, 6))
            Tooltip(button, tip)
            self.bg_buttons.append(button)
        ttk.Label(inner, style="Muted.TLabel", justify="left", wraplength=250,
                  text="Makes the selected layer's background see-through, "
                       "pixel by pixel. Ctrl+Z undoes it.").pack(anchor="w", pady=(8, 0))

    _bg_job = None  # a Remove BG running on a worker thread (AI)

    def remove_texture_background(self, method: str):
        """Remove BG on the selected layer: Plain at once, AI on a worker thread
        (the model takes a few seconds), then one undo step."""
        if self._bg_job is not None or not self.layers:
            return
        if method == "ai":
            problem = ai_status()
            if problem:
                self._set_status(problem)
                if not self._session_quiet():
                    messagebox.showinfo("Pixel Forge", problem)
                return
        layer = self.layers[self.active_layer]
        if layer.gradient is not None:  # its pixels are drawn from the gradient's settings
            self._set_status(f"'{layer.name}' is a gradient layer: select the layer with the texture "
                             "to remove its background.")
            return
        job = {"layer": layer, "image": layer.image.copy(), "done": threading.Event(), "result": None, "error": None}
        self._bg_job = job

        def work():
            try:
                job["result"] = clear_background(job["image"], method)
            except Exception as exc:  # e.g. a broken AI model file
                job["error"] = exc
            job["done"].set()

        if method != "ai":
            work()
            self._finish_bg_job(job)
            return
        for button in self.bg_buttons:
            button.configure(state="disabled")
        self._set_status("Removing the background with AI...")
        threading.Thread(target=work, daemon=True).start()
        self._poll_bg_job(job)

    def _poll_bg_job(self, job):
        # Tk isn't thread-safe: the worker never touches widgets, the UI thread checks in on it.
        if not job["done"].is_set():
            self.root.after(100, lambda: self._poll_bg_job(job))
            return
        self._finish_bg_job(job)

    def _finish_bg_job(self, job):
        self._bg_job = None
        for button in self.bg_buttons:
            button.configure(state="normal")
        if job["error"]:
            self._set_status(f"Removing the background failed: {job['error']}")
            return
        new, message = job["result"]
        layer = job["layer"]
        if new is None:
            self._set_status(message)
            return
        still_there = any(l is layer for l in self.layers)  # (by identity: layers compare by content)
        if not still_there or layer.gradient is not None or layer.image.tobytes() != job["image"].tobytes():
            self._set_status("The layer changed while the AI worked, so nothing was taken away: try again")
            return
        self._snapshot()
        layer.image = new
        self._layers_changed()
        self._set_status(f"{message} (Ctrl+Z undoes it)")

    def _build_session_bar(self):
        """Replace the file actions in the top bar with this session's."""
        bar = self.top_bar
        for widget in bar.winfo_children()[2:]:  # keep the logo and title, drop Open/Save/name/export
            widget.pack_forget()
        name = Path(self.session["path"]).name
        text = (f"New for {self.session['caller']}: {name}, from {Path(self.session['source']).name}"
                if self.session.get("source") else f"Editing for {self.session['caller']}: {name}")
        self.session_label = ttk.Label(bar, style="Value.TLabel", text=text)
        cancel = ttk.Button(bar, text="Cancel", width=8, command=self.session_cancel)
        save = ttk.Button(bar, text="Save & Return", style="Accent.TButton", width=14,
                          command=self.session_save)
        save.pack(side="right")
        cancel.pack(side="right", padx=(0, 6))
        self.session_label.pack(side="left", fill="x", expand=True)
        self.session_save_btn, self.session_cancel_btn = save, cancel

    def session_dirty(self) -> bool:
        """Something would be lost by cancelling: painting, or (converting) settings changed."""
        if self.history.undo_stack:
            return True
        return self.convert_mode and self._start_settings is not None and self._key(self._settings()) != self._start_settings

    def session_save(self):
        path = Path(self.session["path"])
        art = self.display_art
        if art is None:  # converting: the art isn't made yet (the AI is still working)
            self._set_status("Nothing to save yet: wait for the art to appear, then Save & Return")
            return
        try:
            art.save(path, format="PNG")
        except OSError as exc:
            messagebox.showerror("Pixel Forge", f"Couldn't save {path.name}:\n\n{exc}")
            return  # stay open: the user can retry or cancel
        write_result(self.session.get("result"), {"status": "saved", "path": str(path),
                                                  "width": art.width, "height": art.height})
        self._session_end(EXIT_SAVED)

    def session_cancel(self):
        if self.session_dirty() and not self._session_quiet() and not messagebox.askyesno(
                "Pixel Forge", "Discard your changes to this texture?"):
            return
        write_result(self.session.get("result"), {"status": "cancelled"})
        self._session_end(EXIT_CANCELLED)

    def _session_fail(self, message: str):
        write_result(self.session.get("result"), {"status": "error", "message": message})
        if not self._session_quiet():
            what = "make this texture" if self.session.get("source") else "edit this texture"
            messagebox.showerror("Pixel Forge", f"Can't {what}:\n\n{message}")
        self._session_end(EXIT_ERROR)

    def _session_end(self, code: int):
        self.exit_code = code
        self.root.after(0, self.root.destroy)

    @staticmethod
    def _session_quiet() -> bool:
        """No dialogs in hidden/automated runs (tests of the calling app)."""
        return os.environ.get("PIXEL_FORGE_HIDDEN") == "1"
