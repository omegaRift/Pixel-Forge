"""
Batch: many pictures converted at once, each saved as its own sprite.

Batch... in the top bar (Ctrl+B) opens a window where pictures are added
(Add Pictures..., several at a time), then Convert All runs every one of
them through the converter with the sidebar's current settings - grid,
colours, outline, background removal, sprite clean-up - and saves the
results into a folder: the sprite itself (flesh_axe.png) and/or the
enlarged art (flesh_axe_512.png), named after each picture as Save does.

The work runs off the Tk loop with a progress bar in the batch window; each
picture shows its result (or why it failed) as it is done. Double-clicking
one opens it in the main window, to touch it up by hand.

A mixin for PixelForgeApp, like palette_ui: it uses the app's settings,
export folder and dialogs.
"""

import os
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from editor_ui import checkerboard
from mc_preview import texture_id
from pixel_core import PREVIEW_SIZE, ai_status, pixelate_detailed, private_subjects
from platform_support import MONO, open_folder
from ui_widgets import ScrollArea, Tooltip
from waitbar import WaitBar

# Theme colours (kept in sync with pixel_forge's palette)
BG, PANEL, BORDER, TEXT, MUTED, ACCENT, CYAN = (
    "#12121c", "#1c1c2b", "#2e2e45", "#e8e8f0", "#8a8aa3", "#ff3e7f", "#3ef0ff")
GOOD, BAD, DIM = "#7ee787", "#ff6b6b", "#55556b"
BATCH_TYPES = [("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("PNG", "*.png"),
               ("JPEG", "*.jpg *.jpeg"), ("All files", "*.*")]
THUMB = 40  # px, the pictures and results in the list
FONT = (MONO, 10)


class BatchItem:
    """One picture in the batch."""

    def __init__(self, path: Path):
        self.path = path
        self.status = "waiting"     # waiting / working / done / skipped / failed
        self.message = ""           # what happened, in words
        self.sprite = None          # the converted sprite (grid x grid), once done
        self.saved: list[Path] = []
        self.thumb = None           # ImageTk images, kept alive here
        self.result_thumb = None
        self.widgets = {}

    @property
    def tid(self) -> str:
        """The file name it is saved under (without .png), in Save's style ('Flesh Axe.jpg' ->
        flesh_axe), but from the whole name: Save's Item name shortens long ones for the tooltip."""
        return texture_id(self.path.stem)


class BatchMixin:
    def _build_batch_ui(self):
        self._batch_items: list[BatchItem] = []
        self._batch_dialog = None
        self._batch_area = None
        self._batch_job = None
        self._batch_dir: Path | None = None   # where this batch saves (default: the export folder)
        self._batch_thumbs = []               # items still waiting for their thumbnail
        self.batch_sprite_var = tk.BooleanVar(value=True)
        self.batch_art_var = tk.BooleanVar(value=False)
        # Backgrounds, chosen here for the whole batch (they start as the sidebar has them)
        self.batch_remove_var = tk.BooleanVar(value=False)
        self.batch_method_var = tk.StringVar(value="plain")
        self.batch_match_var = tk.BooleanVar(value=True)
        self._batch_bg_set = False

        # Top bar, next to Open...: [Batch...]
        self.batch_btn = ttk.Button(self.top_bar, text="Batch...", width=8, command=self.open_batch)
        self.batch_btn.pack(side="left", padx=(0, 4), before=self.save_btn)
        Tooltip(self.batch_btn, "Convert several pictures at once with the current settings,\n"
                                "each saved as its own sprite (Ctrl+B)")
        self.root.bind("<Control-b>", lambda e: self.open_batch())

    # ---- the window ------------------------------------------------------------

    def open_batch(self, paths=None):
        """Show the batch window (paths: pictures to add to it)."""
        if self.session:  # an edit session is about its one texture
            return
        if self._batch_dialog is not None and self._batch_dialog.winfo_exists():
            self._batch_dialog.deiconify()
            self._batch_dialog.lift()
        else:
            self._build_batch_window()
        if paths:
            self.add_batch_pictures(paths)

    def _build_batch_window(self):
        s = self.ui_scale
        top = self._batch_dialog = tk.Toplevel(self.root)
        if os.environ.get("PIXEL_FORGE_HIDDEN") == "1":
            top.withdraw()  # automated runs: never on screen
        top.title("Batch - Pixel Forge")
        top.configure(bg=BG)
        top.transient(self.root)
        top.geometry(f"{round(640 * s)}x560")
        top.minsize(round(560 * s), 420)
        top.protocol("WM_DELETE_WINDOW", self.close_batch)
        top.bind("<Escape>", lambda e: self.close_batch())

        outer = ttk.Frame(top, style="Panel.TFrame", padding=12)
        outer.pack(fill="both", expand=True, padx=8, pady=8)
        head = ttk.Frame(outer, style="Panel.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="BATCH", style="Head.TLabel").pack(side="left")
        self.batch_count = ttk.Label(head, style="Muted.TLabel")
        self.batch_count.pack(side="right")
        ttk.Label(outer, style="Muted.TLabel", justify="left", wraplength=round(580 * s),
                  text="Every picture is converted with the sidebar's settings (grid, colours, outline, "
                       "clean-up) and the background choice below, and saved as its own sprite, named after "
                       "the picture.").pack(
            fill="x", pady=(4, 8))

        # Bottom, from the bottom up: buttons, progress / summary, options, the add row
        buttons = ttk.Frame(outer, style="Panel.TFrame")
        buttons.pack(side="bottom", fill="x", pady=(10, 0))
        self.batch_go = ttk.Button(buttons, text="Convert All", style="Accent.TButton", width=12,
                                   command=self.start_batch)
        self.batch_go.pack(side="left")
        ttk.Button(buttons, text="Close", style="Small.TButton", width=6,
                   command=self.close_batch).pack(side="right")
        self.batch_open_btn = ttk.Button(buttons, text="Open Folder", style="Small.TButton", width=12,
                                         command=self._open_batch_dir)
        self.batch_open_btn.pack(side="right", padx=(0, 6))

        progress = ttk.Frame(outer, style="Panel.TFrame")
        progress.pack(side="bottom", fill="x", pady=(8, 0))
        self.batch_summary = ttk.Label(progress, style="Muted.TLabel", anchor="w", justify="left",
                                       wraplength=round(580 * s))
        self.batch_summary.pack(fill="x")
        self.batch_waits = WaitBar(top, progress, covers=[self.batch_summary])  # (its bar, in this window)

        options = ttk.Frame(outer, style="Panel.TFrame")
        options.pack(side="bottom", fill="x", pady=(8, 0))
        background = ttk.Frame(outer, style="Panel.TFrame")
        background.pack(side="bottom", fill="x", pady=(8, 0))
        st = ttk.Style(top)  # (greyed while Remove backgrounds is off: they only apply to removing)
        for kind in ("TCheckbutton", "TRadiobutton"):
            st.map(f"Batch.{kind}", foreground=[("disabled", DIM), ("selected", ACCENT)],
                   indicatorforeground=[("disabled", DIM)], background=[("active", PANEL)])
        if not self._batch_bg_set:  # the first time: as the sidebar has it
            self._batch_bg_set = True
            self.batch_remove_var.set(self.transparent_var.get())
            self.batch_method_var.set(self.bg_method.get())
        self.batch_remove_check = ttk.Checkbutton(background, text="Remove backgrounds",
                                                  variable=self.batch_remove_var,
                                                  command=self._update_batch_controls)
        self.batch_remove_check.pack(side="left")
        Tooltip(self.batch_remove_check, "Every picture's background is removed (see-through), as with\n"
                                         "Transparent BG in the sidebar")
        self.batch_method_radios = []
        for value, text, tip in (("plain", "Plain", "For a plain-coloured background (fast)"),
                                 ("ai", "AI", "For busy backgrounds and photos (about a second a picture)")):
            r = ttk.Radiobutton(background, text=text, value=value, variable=self.batch_method_var,
                                style="Batch.TRadiobutton")
            r.pack(side="left", padx=(12 if value == "plain" else 8, 0))
            Tooltip(r, tip)
            self.batch_method_radios.append(r)
        self.batch_match_check = ttk.Checkbutton(background, text="Match Original", variable=self.batch_match_var,
                                                 style="Batch.TCheckbutton")
        self.batch_match_check.pack(side="right")
        Tooltip(self.batch_match_check, "After a picture's background is removed, Match Original runs on it\n"
                                        "by itself: the colours are re-fitted to read like the source")
        ttk.Label(options, text="Save to").pack(side="left", padx=(0, 8))
        self.batch_dir_btn = ttk.Button(options, style="Small.TButton", width=18, command=self._choose_batch_dir)
        self.batch_dir_btn.pack(side="left")
        Tooltip(self.batch_dir_btn, lambda: str(self._batch_folder() or "Not chosen yet: Convert All asks"))
        self.batch_art_check = ttk.Checkbutton(options, text=f"Art ({PREVIEW_SIZE})", variable=self.batch_art_var)
        self.batch_art_check.pack(side="right")
        self.batch_sprite_check = ttk.Checkbutton(options, variable=self.batch_sprite_var)
        self.batch_sprite_check.pack(side="right", padx=(0, 12))
        Tooltip(self.batch_sprite_check, "The sprite itself, e.g. flesh_axe.png (what Save Sprite saves)")
        Tooltip(self.batch_art_check, f"The art enlarged to {PREVIEW_SIZE}x{PREVIEW_SIZE}, e.g. "
                                      f"flesh_axe_{PREVIEW_SIZE}.png (what Save Art saves)")

        add_row = ttk.Frame(outer, style="Panel.TFrame")
        add_row.pack(side="bottom", fill="x", pady=(8, 0))
        self.batch_add_btn = ttk.Button(add_row, text="Add Pictures...", style="Small.TButton", width=15,
                                        command=self._ask_batch_pictures)
        self.batch_add_btn.pack(side="left")
        Tooltip(self.batch_add_btn, "Choose pictures to add (pick several at once with Ctrl or Shift)")
        self.batch_clear_btn = ttk.Button(add_row, text="Clear", style="Small.TButton", width=6,
                                          command=self.clear_batch)
        self.batch_clear_btn.pack(side="right")
        self.batch_remove_btn = ttk.Button(add_row, text="Remove Finished", style="Small.TButton", width=16,
                                           command=self._remove_finished)
        self.batch_remove_btn.pack(side="right", padx=(0, 6))
        Tooltip(self.batch_remove_btn, "Take the pictures that were converted and saved off the list")

        self._batch_area = ScrollArea(outer, bg=BG, style="Bg.TFrame", height=200, step=THUMB + 10)
        self._batch_area.pack(fill="both", expand=True)
        self._fill_batch()

    def close_batch(self):
        if self._batch_job is not None:
            if not messagebox.askyesno("Pixel Forge", "Stop the batch?\n\nThe pictures done so far stay saved.",
                                       parent=self._batch_dialog):
                return
            self._batch_job["stop"].set()
        if self._batch_dialog is not None and self._batch_dialog.winfo_exists():
            self._batch_dialog.destroy()
        self._batch_dialog = self._batch_area = None

    def _batch_open(self) -> bool:
        return self._batch_dialog is not None and self._batch_dialog.winfo_exists()

    # ---- the list ------------------------------------------------------------

    def _ask_batch_pictures(self):
        paths = filedialog.askopenfilenames(title="Add pictures to the batch", filetypes=BATCH_TYPES,
                                            parent=self._batch_dialog)
        if paths:
            self.add_batch_pictures(paths)

    def add_batch_pictures(self, paths):
        """Add pictures to the list (a picture already on it isn't added twice)."""
        have = {item.path.resolve() for item in self._batch_items}
        added = 0
        for p in paths:
            path = Path(p)
            if path.resolve() in have or not path.is_file():
                continue
            have.add(path.resolve())
            item = BatchItem(path)
            self._batch_items.append(item)
            self._batch_thumbs.append(item)
            added += 1
        self._fill_batch()
        if self._batch_thumbs:
            self.root.after(1, self._next_batch_thumb)
        return added

    def _next_batch_thumb(self):
        """Thumbnails one at a time, so adding many big pictures never freezes the window."""
        if not self._batch_thumbs:
            return
        item = self._batch_thumbs.pop(0)
        try:
            with Image.open(item.path) as img:
                img.draft("RGB", (THUMB * 2, THUMB * 2))  # (a JPEG decodes small: much faster)
                img.thumbnail((THUMB, THUMB))
                item.thumb = ImageTk.PhotoImage(self._on_checks(img.convert("RGBA")))
        except Exception:
            item.thumb = None
        self._show_batch_item(item)
        if self._batch_thumbs:
            self.root.after(1, self._next_batch_thumb)

    @staticmethod
    def _on_checks(img: Image.Image) -> Image.Image:
        """A picture centred in a THUMB square, on the checkerboard where it's see-through."""
        tile = checkerboard(THUMB, THUMB, 5).convert("RGBA")
        tile.alpha_composite(img, ((THUMB - img.width) // 2, (THUMB - img.height) // 2))
        return tile

    def remove_batch_item(self, item: BatchItem):
        if self._batch_job is None and item in self._batch_items:
            self._batch_items.remove(item)
            self._fill_batch()

    def _remove_finished(self):
        if self._batch_job is None:
            self._batch_items = [i for i in self._batch_items if i.status != "done"]
            self._fill_batch()

    def clear_batch(self):
        if self._batch_job is None:
            self._batch_items = []
            self._batch_thumbs = []
            self._fill_batch()

    def _fill_batch(self):
        """Rebuild the list (and the buttons that depend on it)."""
        if not self._batch_open():
            return
        inner = self._batch_area.inner
        for child in inner.winfo_children():
            child.destroy()
        if not self._batch_items:
            ttk.Label(inner, style="Bg.TLabel", foreground=MUTED, justify="left",
                      text="No pictures yet.\n\nAdd Pictures... chooses them: pick several at once\n"
                           "with Ctrl or Shift.").pack(anchor="w", padx=12, pady=12)
        for item in self._batch_items:
            self._batch_row(inner, item)
        self._update_batch_controls()

    def _batch_row(self, parent, item: BatchItem):
        row = tk.Frame(parent, bg=BG, highlightthickness=1, highlightbackground=BORDER)
        row.pack(fill="x", padx=(0, 4), pady=(0, 4))
        if getattr(self, "_batch_blank", None) is None:  # (an empty THUMB square: a Label sized in pixels)
            self._batch_blank = ImageTk.PhotoImage(Image.new("RGBA", (THUMB, THUMB), (0, 0, 0, 0)))
        source = tk.Label(row, bg=BG, image=self._batch_blank)
        source.pack(side="left", padx=6, pady=4)
        arrow = tk.Label(row, text="→", bg=BG, fg=MUTED, font=FONT)
        arrow.pack(side="left")
        result = tk.Label(row, bg=BG, image=self._batch_blank)
        result.pack(side="left", padx=6, pady=4)
        remove = ttk.Button(row, text="✕", style="Arrow.TButton", width=2,
                            command=lambda: self.remove_batch_item(item))
        remove.pack(side="right", padx=6)
        Tooltip(remove, "Take this picture off the list")
        words = tk.Frame(row, bg=BG)
        words.pack(side="left", fill="x", expand=True, padx=(6, 0))
        name = tk.Label(words, bg=BG, fg=TEXT, anchor="w", font=FONT, width=1)  # (width: whatever is left)
        name.pack(fill="x")
        status = tk.Label(words, bg=BG, fg=MUTED, anchor="w", font=FONT, width=1)
        status.pack(fill="x")
        item.widgets = {"row": row, "source": source, "result": result, "name": name, "status": status,
                        "remove": remove}
        for w in (row, source, arrow, result, words, name, status):
            w.bind("<Double-Button-1>", lambda e: self._open_batch_item(item))
        for label in (name, status):
            label.bind("<Configure>", lambda e, l=label: self._fit_label(l), add="+")
        Tooltip(name, lambda: f"{item.path}\n{getattr(name, 'full_text', '')}\nDouble-click: open it in the main window")
        Tooltip(status, lambda: getattr(status, "full_text", "") if status.cget("text") != getattr(
            status, "full_text", "") else "")
        self._show_batch_item(item)

    def _show_batch_item(self, item: BatchItem):
        """Bring one row up to date (a picture's state changes while the batch runs)."""
        w = item.widgets
        if not w or not w["row"].winfo_exists():
            return
        w["source"].configure(image=item.thumb or self._batch_blank)
        w["result"].configure(image=item.result_thumb or self._batch_blank)
        names = self._batch_names(item)
        self._fit_label(w["name"], f"{item.path.name}  →  {', '.join(names)}" if names else item.path.name)
        colour = {"done": GOOD, "failed": BAD, "working": CYAN, "skipped": MUTED}.get(item.status, MUTED)
        text = item.message or {"waiting": "Waiting", "working": "Converting..."}.get(item.status, "")
        w["status"].configure(fg=colour)
        self._fit_label(w["status"], text)
        w["remove"].configure(state="disabled" if self._batch_job is not None else "normal")

    def _batch_files(self, tid: str) -> list[tuple[str, str]]:
        """(file name, "sprite" or "art") for each kind of file that is ticked."""
        files = []
        if self.batch_sprite_var.get():
            files.append((f"{tid}.png", "sprite"))
        if self.batch_art_var.get():
            files.append((f"{tid}_{PREVIEW_SIZE}.png", "art"))
        return files

    @staticmethod
    def _fit_label(label, text=None):
        """Show `text` (default: the label's last one) in the room the label has, shortened
        in the middle with '...' when it doesn't fit, so both ends of a long name show."""
        if text is not None:
            label.full_text = text
        text = getattr(label, "full_text", "")
        room = label.winfo_width() - 6
        measure = tkfont.Font(font=label.cget("font")).measure
        if room <= 6 or measure(text) <= room:
            label.configure(text=text)
            return
        lo, hi = 0, len(text)  # the most characters that fit, half from each end
        while lo < hi:
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if measure(text[:mid - mid // 2] + "..." + text[len(text) - mid // 2:]) <= room \
                else (lo, mid - 1)
        label.configure(text=text[:lo - lo // 2] + "..." + (text[len(text) - lo // 2:] if lo // 2 else ""))

    def _batch_names(self, item: BatchItem) -> list[str]:
        if item.saved:
            return [p.name for p in item.saved]
        return [name for name, _ in self._batch_files(item.tid)]

    def _update_batch_controls(self):
        if not self._batch_open():
            return
        running = self._batch_job is not None
        n = len(self._batch_items)
        self.batch_count.configure(text=f"{n} picture{'s' if n != 1 else ''}" if n else "")
        grid = self.grid_var.get()
        self.batch_sprite_check.configure(text=f"Sprite ({grid}x{grid})")
        folder = self._batch_folder()
        text = (folder.name or str(folder)) if folder else "Choose..."
        self.batch_dir_btn.configure(text=text if len(text) <= 18 else text[:15] + "...",
                                     state="disabled" if running else "normal")
        self.batch_go.configure(text="Stop" if running else "Convert All",
                                command=self.stop_batch if running else self.start_batch,
                                state="normal" if running or n else "disabled")
        for b in (self.batch_add_btn, self.batch_clear_btn, self.batch_remove_btn,
                  self.batch_sprite_check, self.batch_art_check, self.batch_remove_check):
            b.configure(state="disabled" if running else "normal")
        removing = self.batch_remove_var.get() and not running  # (Plain/AI and Match go with removing)
        for b in (*self.batch_method_radios, self.batch_match_check):
            b.configure(state="normal" if removing else "disabled")
        self.batch_open_btn.configure(state="normal" if folder and folder.is_dir() else "disabled")

    def _open_batch_item(self, item: BatchItem):
        """Double-click: the picture in the main window, to work on by hand."""
        if self.load_image(item.path):
            self.root.lift()

    # ---- the folder ------------------------------------------------------------

    def _batch_folder(self) -> Path | None:
        return self._batch_dir or self.export_dir

    def _choose_batch_dir(self):
        start = self._batch_folder() or Path.home()
        folder = filedialog.askdirectory(title="Save the batch's sprites in", initialdir=str(start),
                                         mustexist=True, parent=self._batch_dialog)
        if folder:
            self._batch_dir = Path(folder)
            self._update_batch_controls()

    def _open_batch_dir(self):
        folder = self._batch_folder()
        if folder and folder.is_dir():
            open_folder(folder)

    # ---- converting ------------------------------------------------------------

    def start_batch(self):
        """Convert All: every picture on the list, with the sidebar's settings."""
        if self._batch_job is not None or not self._batch_items:
            return
        parent = self._batch_dialog
        if not (self.batch_sprite_var.get() or self.batch_art_var.get()):
            messagebox.showinfo("Pixel Forge", "Tick Sprite or Art (or both): what should be saved?", parent=parent)
            return
        removing = self.batch_remove_var.get()
        method = self.batch_method_var.get() if removing else self.bg_method.get()
        if method == "ai":
            problem = ai_status()
            if problem:  # only the model missing? offer it, then start
                if not self._offer_ai_download(self.start_batch):
                    messagebox.showinfo("Pixel Forge", problem, parent=parent)
                return
        folder = self._batch_folder()
        if folder is None or not folder.is_dir():
            self._choose_batch_dir()
            folder = self._batch_dir
            if folder is None or not folder.is_dir():
                return
        # File names: as Save names them; two pictures with the same name get _2, _3...
        plan, taken = [], set()
        for item in self._batch_items:
            tid, n = item.tid, 2
            while tid in taken:
                tid, n = f"{item.tid}_{n}", n + 1
            taken.add(tid)
            plan.append((item, [(folder / name, kind) for name, kind in self._batch_files(tid)]))
        existing = [p for _, files in plan for p, _ in files if p.exists() and p not in self._overwrite_ok]
        replace = True
        if existing:
            answer = messagebox.askyesnocancel(
                "Pixel Forge", f"{len(existing)} of the files already exist in\n{folder}\n\n"
                               "Yes: replace them\nNo: skip those pictures", parent=parent)
            if answer is None:
                return
            replace = answer
        settings = self._settings()
        settings["offset"] = (0, 0)  # a nudge belongs to the window's picture (scale is kept, as for Open)
        settings["transparent_bg"], settings["background"] = removing, method
        for item, _ in plan:
            item.status, item.message, item.sprite, item.saved, item.result_thumb = "waiting", "", None, [], None
        job = self._batch_job = {
            "plan": plan, "settings": settings, "replace": replace, "folder": folder,
            "match": removing and self.batch_match_var.get(),
            "stop": threading.Event(), "done": threading.Event(), "changed": [], "lock": threading.Lock(),
            "finished": 0, "wait": self.batch_waits.begin("batch", f"Converting {len(plan)} pictures...")}
        job["wait"].progress(0.0)
        self._fill_batch()
        threading.Thread(target=self._batch_work, args=(job,), daemon=True).start()
        self._poll_batch(job)

    def stop_batch(self):
        if self._batch_job is not None:
            self._batch_job["stop"].set()
            self.batch_go.configure(state="disabled", text="Stopping...")

    def _batch_work(self, job):
        """The worker thread: no Tk here, only the items and the job."""
        plan, total = job["plan"], len(job["plan"])
        for n, (item, files) in enumerate(plan):
            paths = [p for p, _ in files]
            if job["stop"].is_set():
                break
            job["wait"].text = f"Converting {n + 1} of {total}..."  # (which one: its row says so)
            self._batch_set(job, item, "working", "")
            try:
                if not job["replace"] and any(p.exists() for p in paths):
                    self._batch_set(job, item, "skipped", "Skipped: its file is already there")
                else:
                    with Image.open(item.path) as img:
                        img.load()
                        with private_subjects():
                            art = pixelate_detailed(img, **job["settings"])
                            removed = job["settings"]["transparent_bg"] and art.subject_found
                            if removed and job["match"]:  # its background is gone: Match Original, as the button does
                                if not job["stop"].is_set():
                                    job["wait"].text = f"Converting {n + 1} of {total}: matching the original..."
                                art = pixelate_detailed(img, **job["settings"], match_source=True)
                    sprite = art.small
                    for path, kind in files:  # (exactly what Save Sprite / Save Art save for a fresh picture)
                        out = sprite if kind == "sprite" else sprite.resize((PREVIEW_SIZE, PREVIEW_SIZE),
                                                                            Image.Resampling.NEAREST)
                        out.save(path, format="PNG")
                    item.sprite, item.saved = sprite, paths
                    found = "" if art.subject_found is not False else "  (no subject found: the whole picture was used)"
                    if removed:
                        found = "  (background removed" + (", original matched)" if job["match"] else ")")
                    self._batch_set(job, item, "done", f"Saved {', '.join(p.name for p in paths)}{found}")
            except Exception as exc:  # one bad picture doesn't stop the rest
                self._batch_set(job, item, "failed", f"Failed: {exc}")
            job["finished"] = n + 1
            job["wait"].progress((n + 1) / total)
        job["done"].set()

    @staticmethod
    def _batch_set(job, item, status, message):
        item.status, item.message = status, message
        with job["lock"]:
            job["changed"].append(item)

    def _poll_batch(self, job):
        with job["lock"]:
            changed, job["changed"] = job["changed"], []
        for item in dict.fromkeys(changed):  # (each once, in order)
            if item.sprite is not None and item.result_thumb is None:
                k = max(1, THUMB // item.sprite.width)
                big = item.sprite.resize((item.sprite.width * k, item.sprite.height * k), Image.Resampling.NEAREST)
                item.result_thumb = ImageTk.PhotoImage(self._on_checks(big))
            for path in item.saved:
                self._overwrite_ok.add(path)  # saved by us: a later Save of the same name needn't ask
            if self._batch_open():
                self._show_batch_item(item)
                if item.status == "working":
                    self._batch_area.show(item.widgets["row"])
        if not job["done"].is_set():
            self.root.after(100, lambda: self._poll_batch(job))
            return
        self._batch_job = None
        job["wait"].end(record=False)  # (it has real progress)
        self._batch_finished(job)

    def _batch_finished(self, job):
        items = [item for item, _ in job["plan"]]
        done = sum(i.status == "done" for i in items)
        failed = sum(i.status == "failed" for i in items)
        skipped = sum(i.status == "skipped" for i in items)
        left = sum(i.status in ("waiting", "working") for i in items)
        for i in items:
            if i.status == "working":
                i.status, i.message = "waiting", ""
        parts = [f"{done} of {len(items)} converted and saved to {job['folder']}"]
        parts += [f"{failed} failed"] * bool(failed) + [f"{skipped} skipped"] * bool(skipped)
        parts += [f"stopped, {left} not done"] * bool(left)
        summary = "  ·  ".join(parts)
        self._set_status(f"Batch: {summary}")
        if self._batch_open():
            self.batch_summary.configure(text=summary, foreground=BAD if failed else GOOD if done else MUTED)
            self._fill_batch()
