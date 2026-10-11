"""
The palette library in Pixel Forge's sidebar: Save Palette keeps the colours
of the art on screen in the library database (palette_store), and
Palettes... opens the library in any project - to paint with a saved palette
(it's shown under the sprite's own palette), or to recolour a layer to it.

A mixin for PixelForgeApp, like editor_ui: it uses the app's widgets and the
layer editor's state.
"""

import os
import sqlite3
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from palette_store import NameTaken, PaletteStore, colours_of, recolour
from ui_widgets import ScrollArea, Tooltip

# Theme colours (kept in sync with pixel_forge's palette)
BG, PANEL, BORDER, TEXT, MUTED = "#12121c", "#1c1c2b", "#2e2e45", "#e8e8f0", "#8a8aa3"
STRIP_ROWS = 2    # rows of swatches for a loaded palette in the sidebar
PREVIEW = 32      # colours shown per palette in the library window


def _hex(rgba) -> str:
    return "#%02x%02x%02x" % tuple(rgba[:3])


class PaletteLibraryMixin:
    # ---- sidebar -------------------------------------------------------------

    def _build_palette_library(self):
        """Save Palette / Palettes... under the PALETTE swatches, and the
        strip that shows a palette opened from the library."""
        self.palette_store = PaletteStore()
        self.loaded_palette = None   # a palette_store.Palette opened from the library
        self._lib_swatches = []
        self._lib_dialog = None
        self._lib_area = None
        self._lib_selected = None    # palette id selected in the library window

        section = self.palette_canvas.master
        row = ttk.Frame(section, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        save = ttk.Button(row, text="Save Palette", style="Small.TButton", width=0, command=self.save_palette)
        save.pack(side="left")
        Tooltip(save, "Save these colours in your palette library,\nto use them in any other project")
        lib = ttk.Button(row, text="Palettes...", style="Small.TButton", width=0, command=self.open_palette_library)
        lib.pack(side="left", padx=(6, 0))
        Tooltip(lib, "Your saved palettes: paint with one, or recolour a layer to it")

        self.lib_strip = ttk.Frame(section, style="Panel.TFrame")  # packed while a palette is open
        head = ttk.Frame(self.lib_strip, style="Panel.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Library:", style="Muted.TLabel").pack(side="left")
        self.lib_name = ttk.Label(head, style="Value.TLabel")
        self.lib_name.pack(side="left", padx=(6, 0))
        close = ttk.Button(head, text="✕", style="Arrow.TButton", width=2, command=self.close_loaded_palette)
        close.pack(side="right")
        Tooltip(close, "Put this palette away (it stays in the library)")
        self.lib_more = ttk.Label(head, style="Muted.TLabel")
        self.lib_more.pack(side="right", padx=(0, 6))
        self.lib_canvas = tk.Canvas(self.lib_strip, bg=PANEL, highlightthickness=0, height=16, cursor="hand2")
        self.lib_canvas.pack(fill="x", pady=(6, 0))
        self.lib_canvas.bind("<Button-1>", lambda e: self._on_library_swatch(e, 0))
        self.lib_canvas.bind("<Button-3>", lambda e: self._on_library_swatch(e, 1))
        self.lib_canvas.bind("<Configure>", lambda e: self._draw_loaded_palette())
        Tooltip(self.lib_canvas, lambda: "Click: gradient start colour  ·  right-click: end colour"
                if self.tool_var.get() == "gradient" else "Click a colour to paint with it")

    def _draw_loaded_palette(self):
        c = self.lib_canvas
        c.delete("all")
        self._lib_swatches = []
        p = self.loaded_palette
        if p is None:
            return
        size, gap = 16, 3
        per_row = max(1, (c.winfo_width() or 276) // (size + gap))
        shown = p.colours[: per_row * STRIP_ROWS]
        for i, rgba in enumerate(shown):
            x, y = (i % per_row) * (size + gap), (i // per_row) * (size + gap)
            c.create_rectangle(x, y, x + size, y + size, outline=BORDER, fill=_hex(rgba))
            self._lib_swatches.append((x, y, x + size, y + size, rgba))
        rows = -(-len(shown) // per_row)
        c.configure(height=max(size, rows * (size + gap)))
        more = len(p.colours) - len(shown)
        self.lib_more.configure(text=f"+{more} more" if more else "")

    def _on_library_swatch(self, event, end):
        for x0, y0, x1, y1, rgba in self._lib_swatches:
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self._pick_swatch(rgba, end)  # (editor_ui: same as the sprite's own palette)
                return

    def use_palette(self, pid: int):
        """Open a saved palette in the sidebar, to paint with."""
        p = self.palette_store.get(pid)
        if p is None:
            return
        self.loaded_palette = p
        self.lib_name.configure(text=p.name if len(p.name) <= 20 else p.name[:17] + "...")
        if not self.lib_strip.winfo_manager():
            self.lib_strip.pack(fill="x", pady=(10, 0))
        self.lib_strip.update_idletasks()
        self._draw_loaded_palette()
        self._set_status(f"Palette '{p.name}' ({len(p.colours)} colours) is open under PALETTE: "
                         "click a colour to paint with it.")

    def close_loaded_palette(self):
        self.loaded_palette = None
        self.lib_strip.pack_forget()
        self._draw_loaded_palette()

    # ---- saving ----------------------------------------------------------------

    def save_palette(self):
        """Save the colours of the art on screen (every visible layer) to the
        library, under a name."""
        art = getattr(self, "display_art", None)
        colours = colours_of(art) if art is not None else []
        if not colours:
            self._set_status("There are no colours to save yet: open an image first.")
            return
        suggestion = self.item_name.get().strip() if self.item_name.get().strip() not in ("", "Item") else ""
        if not suggestion and self.source_path is not None:
            suggestion = self.source_path.stem
        name = simpledialog.askstring("Save palette", f"Name for this palette ({len(colours)} colours):",
                                      initialvalue=suggestion, parent=self.root)
        if not name or not name.strip():
            return
        source = self.source_path.name if self.source_path is not None else ""
        try:
            try:
                p = self.palette_store.save(name, colours, source)
            except NameTaken:
                if not messagebox.askyesno("Pixel Forge", f"There's already a palette called '{name.strip()}'.\n\n"
                                                          "Replace its colours with these?", parent=self.root):
                    return
                p = self.palette_store.save(name, colours, source, replace=True)
        except (ValueError, sqlite3.Error, OSError) as exc:
            messagebox.showerror("Pixel Forge", f"Couldn't save the palette:\n\n{exc}", parent=self.root)
            return
        if self.loaded_palette is not None and self.loaded_palette.id == p.id:
            self.use_palette(p.id)  # it changed: show the new colours
        self._set_status(f"Saved palette '{p.name}' ({len(p.colours)} colours). "
                         "Open it in any project with Palettes...")
        self._fill_library()

    # ---- the library window ----------------------------------------------------

    def open_palette_library(self):
        if self._lib_dialog is not None and self._lib_dialog.winfo_exists():
            self._lib_dialog.deiconify()
            self._lib_dialog.lift()
            self._fill_library()
            return
        top = self._lib_dialog = tk.Toplevel(self.root)
        if os.environ.get("PIXEL_FORGE_HIDDEN") == "1":
            top.withdraw()  # automated runs: never on screen
        top.title("Palette Library - Pixel Forge")
        top.configure(bg=BG)
        top.transient(self.root)
        top.geometry(f"{round(520 * self.ui_scale)}x460")
        top.minsize(round(420 * self.ui_scale), 320)
        top.protocol("WM_DELETE_WINDOW", self.close_palette_library)
        top.bind("<Escape>", lambda e: self.close_palette_library())

        outer = ttk.Frame(top, style="Panel.TFrame", padding=12)
        outer.pack(fill="both", expand=True, padx=8, pady=8)
        head = ttk.Frame(outer, style="Panel.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="PALETTE LIBRARY", style="Head.TLabel").pack(side="left")
        self.lib_count = ttk.Label(head, style="Muted.TLabel")
        self.lib_count.pack(side="right")

        buttons = ttk.Frame(outer, style="Panel.TFrame")
        buttons.pack(side="bottom", fill="x", pady=(10, 0))
        self._lib_buttons = {}
        for key, text, tip, cmd, side in (
                ("use", "Use", "Show it under PALETTE, to paint with (or double-click it)", self._lib_use, "left"),
                ("recolour", "Recolour Layer", "Move every colour of the selected layer to the nearest\n"
                                               "colour of this palette (Ctrl+Z undoes it)", self._lib_recolour, "left"),
                ("close", "Close", "", self.close_palette_library, "right"),
                ("delete", "Delete", "Delete it from the library", self._lib_delete, "right"),
                ("rename", "Rename...", "", self._lib_rename, "right")):
            b = ttk.Button(buttons, text=text, style="Small.TButton", width=0, command=cmd)
            b.pack(side=side, padx=(0, 6) if side == "left" else (6, 0))
            if tip:
                Tooltip(b, tip)
            self._lib_buttons[key] = b
        self._lib_buttons["use"].configure(style="Accent.TButton")

        self._lib_area = ScrollArea(outer, bg=PANEL, height=200)
        self._lib_area.pack(fill="both", expand=True, pady=(10, 0))
        self._fill_library()

    def close_palette_library(self):
        if self._lib_dialog is not None and self._lib_dialog.winfo_exists():
            self._lib_dialog.destroy()
        self._lib_dialog = self._lib_area = None

    def _fill_library(self):
        """(Re)build the list of palettes in the library window."""
        if self._lib_area is None or self._lib_dialog is None or not self._lib_dialog.winfo_exists():
            return
        rows = self._lib_area.inner
        for child in rows.winfo_children():
            child.destroy()
        try:
            palettes = self.palette_store.all()
        except (sqlite3.Error, OSError) as exc:
            palettes = []
            ttk.Label(rows, text=f"Couldn't read the palette library:\n{exc}", style="Muted.TLabel",
                      wraplength=440).pack(anchor="w")
        ids = [p.id for p in palettes]
        if self._lib_selected not in ids:
            self._lib_selected = ids[0] if ids else None
        self.lib_count.configure(text=f"{len(palettes)} saved" if palettes else "")
        if not palettes:
            ttk.Label(rows, style="Muted.TLabel", justify="left", wraplength=440,
                      text="No saved palettes yet.\n\nOpen a texture and press Save Palette (under PALETTE) "
                           "to keep its colours here for other projects.").pack(anchor="w", pady=8)
        for p in palettes:
            self._library_row(rows, p)
        for key in ("use", "recolour", "rename", "delete"):
            self._lib_buttons[key].configure(state="normal" if self._lib_selected is not None else "disabled")
        if self.display_art is None or not self.layers:
            self._lib_buttons["recolour"].configure(state="disabled")

    def _library_row(self, parent, p):
        sel = "Sel" if p.id == self._lib_selected else ""
        row = ttk.Frame(parent, style=f"Row{sel}.TFrame", padding=(8, 6))
        row.pack(fill="x", pady=1)
        top = ttk.Frame(row, style=f"Row{sel}.TFrame")
        top.pack(fill="x")
        name = ttk.Label(top, text=p.name, style=f"Row{sel}.TLabel")
        name.pack(side="left")
        when = ttk.Label(top, text=p.updated[:10], style=f"RowMuted{sel}.TLabel")
        when.pack(side="right")
        source = p.source if len(p.source) <= 40 else p.source[:22] + "..." + p.source[-15:]
        info = f"{len(p.colours)} colours" + (f"  ·  from {source}" if source else "")
        meta = ttk.Label(row, text=info, style=f"RowMuted{sel}.TLabel")
        meta.pack(anchor="w", pady=(2, 0))
        size, gap = 12, 2
        shown = p.colours[:PREVIEW]
        per_row = 16
        c = tk.Canvas(row, bg=PANEL if not sel else BORDER, highlightthickness=0,
                      height=(-(-len(shown) // per_row)) * (size + gap), width=per_row * (size + gap))
        c.pack(anchor="w", pady=(6, 0))
        for i, rgba in enumerate(shown):
            x, y = (i % per_row) * (size + gap), (i // per_row) * (size + gap)
            c.create_rectangle(x, y, x + size, y + size, outline=BORDER, fill=_hex(rgba))
        for w in (row, top, name, when, meta, c):
            w.bind("<Button-1>", lambda e, pid=p.id: self._lib_select(pid))
            w.bind("<Double-Button-1>", lambda e, pid=p.id: (self._lib_select(pid), self._lib_use()))
        return row

    def _lib_select(self, pid):
        self._lib_selected = pid
        self._fill_library()

    def _lib_use(self):
        if self._lib_selected is not None:
            self.use_palette(self._lib_selected)

    def _lib_recolour(self):
        """Recolour the selected layer to the selected palette (one undo step)."""
        p = self.palette_store.get(self._lib_selected) if self._lib_selected is not None else None
        if p is None or not self.layers:
            return
        i = self.active_layer
        layer = self.layers[i]
        if not layer.visible:
            self._set_status(f"'{layer.name}' is hidden - show it (tick its box) to recolour it.")
            return
        self._snapshot()
        if layer.gradient is not None:
            self._flatten_gradient(i)  # a gradient layer's pixels come from its settings: make them pixels
        self._freeze(layer)
        layer.image = recolour(layer.image, p.colours)
        self._status_note = f"'{layer.name}' recoloured to palette '{p.name}' (Ctrl+Z undoes it)."
        self._set_status(self._status_note)
        self.use_palette(p.id)
        self._layers_changed()

    def _lib_rename(self):
        p = self.palette_store.get(self._lib_selected) if self._lib_selected is not None else None
        if p is None:
            return
        name = simpledialog.askstring("Rename palette", "New name:", initialvalue=p.name,
                                      parent=self._lib_dialog or self.root)
        if not name or not name.strip() or name.strip() == p.name:
            return
        try:
            p = self.palette_store.rename(p.id, name)
        except NameTaken:
            messagebox.showerror("Pixel Forge", f"There's already a palette called '{name.strip()}'.",
                                 parent=self._lib_dialog or self.root)
            return
        if self.loaded_palette is not None and self.loaded_palette.id == p.id:
            self.use_palette(p.id)
        self._fill_library()

    def _lib_delete(self):
        p = self.palette_store.get(self._lib_selected) if self._lib_selected is not None else None
        if p is None:
            return
        if not messagebox.askyesno("Pixel Forge", f"Delete the palette '{p.name}' from your library?\n\n"
                                                  "This can't be undone.", parent=self._lib_dialog or self.root):
            return
        self.palette_store.delete(p.id)
        if self.loaded_palette is not None and self.loaded_palette.id == p.id:
            self.close_loaded_palette()
        self._lib_selected = None
        self._fill_library()
