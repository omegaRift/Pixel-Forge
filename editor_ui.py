"""
The Edit view of Pixel Forge: paint on the sprite, with layers.

A mixin for PixelForgeApp (it uses the app's widgets, colours and state).
The generated sprite is the bottom "Base" layer. While untouched it stays
*live* - every settings change re-generates it. Painting on it, or merging
into it, freezes it so edits are never overwritten; Regenerate brings the
live version back. Saving, the in-game preview and the palette all use the
composite of every visible layer (layers.composite). The Gradient tool and
gradient layers live in gradient_ui.
"""

from tkinter import colorchooser, messagebox, simpledialog
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from layers import (BASE_NAME, BLEND_MODES, MAX_LAYERS, History, Layer, blank, composite, faded,
                    flood_fill, line_pixels, merge_down, merge_visible, resize_layers)
from ui_widgets import ScrollArea, Tooltip

# Theme colours (kept in sync with pixel_forge's palette)
BG, PANEL, BORDER, TEXT, MUTED, ACCENT, CYAN = (
    "#12121c", "#1c1c2b", "#2e2e45", "#e8e8f0", "#8a8aa3", "#ff3e7f", "#3ef0ff")
# The left tool strip: (name, tool_var value, mouse cursor, shortcut key)
TOOLS = (("Move", "move", "fleur", "M"), ("Pen", "pen", "pencil", "B"), ("Eraser", "eraser", "dotbox", "E"),
         ("Fill", "fill", "spraycan", "G"), ("Gradient", "gradient", "tcross", "Shift+G"),
         ("Picker", "picker", "crosshair", "I"), ("Zoom", "zoom", "plus", "Z"))
PAINT_TOOLS = {"pen", "eraser", "fill", "gradient", "picker"}  # the tools of Edit mode
TOOL_TIPS = {
    "move": "Move (M)\nDrag moves the subject in the grid, Ctrl+wheel scales it",
    "pen": "Pen (B)\nLeft click paints, right click erases",
    "eraser": "Eraser (E)",
    "fill": "Fill (G)\nFills the connected area of one colour",
    "gradient": "Gradient (Shift+G)\nDrag across the sprite to add a gradient overlay layer;\n"
                "drag again to re-aim it. Shift: 45° steps",
    "picker": "Picker (I)\nClick to take a colour from the sprite",
    "zoom": "Zoom (Z)\nClick: zoom in  ·  right-click / Alt+click: out (down to actual size)  ·  "
            "double-click: fit\n"
            "Any tool: the mouse wheel zooms, middle-drag pans",
}

# 12x12 pixel-art icons, drawn with Pillow (Consolas lacks most symbol glyphs).
ICONS = {
    "move": ["....XX....", "...XXXX...", "....XX....", ".X..XX..X.", "XXXXXXXXXX",
             "XXXXXXXXXX", ".X..XX..X.", "....XX....", "...XXXX...", "....XX...."],
    "pen": [".......XX.", "......XXXX", ".....XXXX.", "....XXXX..", "...XXXX...",
            "..XXXX....", ".XXXX.....", ".XX.......", "XX........", "X........."],
    "eraser": ["....XXX...", "...XXXXX..", "..XXXXXXX.", ".X.XXXXXX.", "X...XXXX..",
               ".X...XX...", "..X.XX....", "...XX.....", "..........", "XXXXXXXXXX"],
    "fill": ["...XX.....", "..X..X....", ".X....X...", "XXXXXXXX..", ".XXXXXXXX.",
             "..XXXXXX.X", "...XXXX..X", "....XX...X", "........XX", "........X."],
    "gradient": ["XXXXXXXXXX", "XXXX..X..X", "XXXXXX.X.X", "XXXX..X..X", "XXXXXX.X.X",
                 "XXXX..X..X", "XXXXXX.X.X", "XXXX..X..X", "XXXXXX.X.X", "XXXXXXXXXX"],
    "picker": [".......XX.", "......XXXX", ".....XXXXX", "......XXX.", ".....X.X..",
               "....X.X...", "...X.X....", "..X.X.....", ".XX.......", "X........."],
    "zoom": ["..XXXX....", ".X....X...", "X......X..", "X......X..", "X......X..",
             ".X....X...", "..XXXXXX..", "......XX..", ".......XX.", "........XX"],
    "undo": ["..X.......", ".XX.......", "XXXXXXX...", ".XX....X..", "..X.....X.",
             "........X.", "........X.", ".......X..", "....XXX...", ".........."],
}
ICONS["redo"] = [row[::-1] for row in ICONS["undo"]]


def tool_icon(name: str, colour) -> Image.Image:
    """An icon drawn at 2x (crisp): 10x10 pattern + 1 px margin -> 24x24."""
    rows = ICONS[name]
    img = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "X":
                img.putpixel((x + 1, y + 1), colour)
    return img.resize((24, 24), Image.Resampling.NEAREST)


def hex_colour(rgba) -> str:
    return "#%02x%02x%02x" % tuple(rgba[:3])


def checkerboard(w: int, h: int, cell: int) -> Image.Image:
    """A grey checkerboard, shown behind transparent pixels."""
    cols, rows = -(-w // cell), -(-h // cell)  # ceil division
    a, b = (42, 42, 61), (52, 52, 74)
    small = Image.new("RGB", (cols, rows))
    small.putdata([a if (x + y) % 2 == 0 else b for y in range(rows) for x in range(cols)])
    # NEAREST turns each 1px cell into a solid cell x cell square.
    return small.resize((cols * cell, rows * cell), Image.Resampling.NEAREST).crop((0, 0, w, h))


class LayerEditorMixin:
    # ---- state -------------------------------------------------------------

    def _init_editor_state(self):
        self.layers: list[Layer] = []
        self.active_layer = 0
        self.history = History()
        self.tool_var = tk.StringVar(value="move")   # starts in Sprite mode: Move
        self._last_paint_tool = "pen"                # what Edit mode returns to
        self.zoom: int | None = None                 # None = fit; else px per art pixel
        self.pan = [0, 0]                            # offset from centred, when zoomed past the canvas
        self._pan_drag = None
        self.paint_colour = (24, 16, 32, 255)
        self.display_art: Image.Image | None = None  # composite of all visible layers
        self.display_big: Image.Image | None = None  # ...enlarged for Save Art
        self._stroke = None          # (last x, last y, erase?) while painting
        self._art_origin = (0, 0, 1)  # canvas x, y of the sprite and px per art pixel
        self._layer_photos = []
        self._swatches = []          # palette swatch rects -> colour (click to pick)
        self._told_frozen = False

    # ---- widgets -----------------------------------------------------------

    def _build_editor_ui(self):
        s = ttk.Style(self.root)
        for sel, bg in (("", PANEL), ("Sel", BORDER)):
            s.configure(f"Row{sel}.TFrame", background=bg)
            s.configure(f"Row{sel}.TLabel", background=bg, foreground=TEXT)
            s.configure(f"RowMuted{sel}.TLabel", background=bg, foreground=MUTED)
            s.configure(f"Row{sel}.TCheckbutton", background=bg, indicatorbackground=BG,
                        indicatorforeground=ACCENT, upperbordercolor=MUTED, lowerbordercolor=MUTED)
            s.map(f"Row{sel}.TCheckbutton", background=[("active", bg)])
        s.configure("TCombobox", fieldbackground=BG, background=BORDER, foreground=TEXT,
                    arrowcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        s.map("TCombobox", fieldbackground=[("readonly", BG)], foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", BG)], selectforeground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", BG)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        # An on/off button (the Gradient blend toggle): accent when on.
        s.configure("Toggle.Toolbutton", background=BORDER, foreground=TEXT, padding=(8, 3), font=("Consolas", 10),
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, focuscolor=BORDER)
        s.map("Toggle.Toolbutton", background=[("disabled", PANEL), ("selected", ACCENT), ("active", "#3b3b58")],
              foreground=[("disabled", "#55556b"), ("selected", BG)],
              bordercolor=[("disabled", BORDER), ("selected", ACCENT)])

        # Tool strip: the 44 px left column. Square icon buttons, tooltips.
        s.configure("Tool.Toolbutton", background=PANEL, padding=5, borderwidth=0, relief="flat",
                    bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL, focuscolor=PANEL)
        s.map("Tool.Toolbutton", background=[("selected", ACCENT), ("active", BORDER)],
              bordercolor=[("selected", ACCENT)], lightcolor=[("selected", ACCENT)], darkcolor=[("selected", ACCENT)])
        s.configure("ToolAction.TButton", background=PANEL, padding=5, borderwidth=0,
                    bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL, focuscolor=PANEL)
        s.map("ToolAction.TButton", background=[("active", BORDER), ("disabled", PANEL)])
        self.toolbar = self.left_strip  # (the name the tests know the tools by)
        self._tool_icons = {}
        dark = (0x12, 0x12, 0x1C, 255)
        light = (0xE8, 0xE8, 0xF0, 255)
        self._tool_buttons = {}
        for name, value, _, key in TOOLS:
            normal, chosen = ImageTk.PhotoImage(tool_icon(value, light)), ImageTk.PhotoImage(tool_icon(value, dark))
            self._tool_icons[value] = (normal, chosen)
            b = ttk.Radiobutton(self.toolbar, image=(normal, "selected", chosen), value=value,
                                variable=self.tool_var, style="Tool.Toolbutton",
                                command=lambda v=value: self.select_tool(v))
            b.pack(side="top", pady=(4 if value == "move" else 2, 0))
            Tooltip(b, TOOL_TIPS[value])
            self._tool_buttons[value] = b
        tk.Frame(self.toolbar, bg=BORDER, height=1).pack(side="top", fill="x", padx=8, pady=8)
        for name, tip, cmd in (("undo", "Undo (Ctrl+Z)", self.undo), ("redo", "Redo (Ctrl+Y)", self.redo)):
            icon = ImageTk.PhotoImage(tool_icon(name, light))
            self._tool_icons[name] = (icon, icon)
            b = ttk.Button(self.toolbar, image=icon, style="ToolAction.TButton", command=cmd)
            b.pack(side="top", pady=(0, 2))
            Tooltip(b, tip)

        # Paint colour: in the sidebar's PALETTE header, next to the swatches.
        self.colour_swatch = tk.Canvas(self.palette_head, width=20, height=20, highlightthickness=1,
                                       highlightbackground=MUTED, cursor="hand2")
        self.colour_swatch.pack(side="right")
        ttk.Label(self.palette_head, text="Paint", style="Muted.TLabel").pack(side="right", padx=(0, 6))
        self.colour_swatch.bind("<Button-1>", lambda e: self.pick_paint_colour())
        Tooltip(self.colour_swatch, "Paint colour - click to choose")
        self._show_paint_colour()
        self.palette_canvas.bind("<Button-1>", self._on_palette_click)
        self.palette_canvas.bind("<Button-3>", self._on_palette_right_click)

        # Layers: anchored at the bottom of the right sidebar, always visible.
        # Packed *before* the Adjustments area so pack gives it its room first.
        side = self.right_sidebar
        self.layer_panel = ttk.Frame(side, style="Panel.TFrame")
        self.layer_panel.pack(side="bottom", fill="x", before=self.adjust_area)
        tk.Frame(side, bg=BORDER, height=1).pack(side="bottom", fill="x", pady=8, before=self.adjust_area)

        head = ttk.Frame(self.layer_panel, style="Panel.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="LAYERS", style="Head.TLabel").pack(side="left")
        self._layer_buttons = {}
        for key, text, tip, cmd in (("down", "▼", "Move layer down", self.move_layer_down),
                                    ("up", "▲", "Move layer up", self.move_layer_up),
                                    ("delete", "Del", "Delete layer", self.delete_layer),
                                    ("dup", "Dup", "Duplicate layer", self.duplicate_layer),
                                    ("add", "+", "New layer", self.add_layer)):
            b = ttk.Button(head, text=text, style="Arrow.TButton", width=4 if len(text) > 1 else 2, command=cmd)
            b.pack(side="right", padx=(3, 0))
            Tooltip(b, tip)
            self._layer_buttons[key] = b

        # Rows: at most ROWS_SHOWN visible, the rest scroll.
        self.layer_area = ScrollArea(self.layer_panel, bg=PANEL, height=30)
        self.layer_area.pack(fill="x", pady=8)
        self.layer_rows = self.layer_area.inner

        row = ttk.Frame(self.layer_panel, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Blend", width=8).pack(side="left")
        self.blend_box = ttk.Combobox(row, values=list(BLEND_MODES), state="readonly", font=("Consolas", 10),
                                      width=max(len(m) for m in BLEND_MODES) + 1)  # room for the longest name
        self.blend_box.pack(side="left", fill="x", expand=True)
        self.blend_box.bind("<<ComboboxSelected>>", lambda e: self.set_blend_mode(self.blend_box.get()))
        self.blend_box.bind("<MouseWheel>", lambda e: "break")  # don't change mode by scrolling past it
        # Gradient blend on/off: the layer fades into the ones below (gradient_ui).
        self.grad_blend_var = tk.BooleanVar(value=False)
        self.blend_toggle = ttk.Checkbutton(row, text="Gradient", style="Toggle.Toolbutton",
                                            variable=self.grad_blend_var, command=self._on_blend_toggle)
        self.blend_toggle.pack(side="right", padx=(6, 0), before=self.blend_box)
        Tooltip(self.blend_toggle, "Gradient blend: turn this layer into a gradient blending overlay -\n"
                                   "it fades from fully shown to see-through, into the layers below.\n"
                                   "Drag with the Gradient tool to aim the fade. Click again to remove it.")
        row = ttk.Frame(self.layer_panel, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Opacity", width=8).pack(side="left")
        self.opacity_label = ttk.Label(row, text="100%", style="Value.TLabel", width=4, anchor="e")
        self.opacity_label.pack(side="right")
        self.opacity_scale = ttk.Scale(row, from_=0, to=100, orient="horizontal", command=self._on_opacity)
        self.opacity_scale.pack(side="left", fill="x", expand=True, padx=(0, 6))
        # One undo step per slider drag, not one per tick.
        self.opacity_scale.bind("<ButtonPress-1>", lambda e: self._snapshot())

        actions = ttk.Frame(self.layer_panel, style="Panel.TFrame")
        actions.pack(fill="x", pady=(8, 0))
        actions.columnconfigure((0, 1, 2), weight=1, uniform="a")
        for col, (key, text, tip, cmd) in enumerate((
                ("merge", "Merge Down", "Merge this layer into the one below", self.merge_layer_down),
                ("merge_all", "Merge All", "Merge all visible layers into one (hidden layers are kept)",
                 self.merge_visible_layers),
                ("regen", "Regenerate", "Bring back the live generated Base layer", self.regenerate_base))):
            # width=0: no built-in minimum width (ttk's default would ask for 99 px each)
            b = ttk.Button(actions, text=text, style="Compact.TButton", width=0, command=cmd)
            b.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 2, 0 if col == 2 else 2))
            Tooltip(b, tip)
            self._layer_buttons[key] = b

        self._build_gradient_panel()  # gradient_ui: GRADIENT settings, top of the Adjustments area

    ROWS_SHOWN = 5

    def _show_editor(self, show: bool):
        """Called when the view changes (Sprite <-> Edit): keep the chosen
        tool consistent with the mode. The tool strip and the layers panel
        are always visible."""
        tool = self.tool_var.get()
        if show and tool == "move":
            self.tool_var.set(self._last_paint_tool)
        elif not show and tool in PAINT_TOOLS:
            self.tool_var.set("move")
        self._on_tool()
        self._refresh_layer_panel()

    # ---- tools, zoom and pan -------------------------------------------------

    def select_tool(self, tool: str):
        """Pick a tool from the strip (or its key). Move = Sprite mode, the
        paint tools = Edit mode, Zoom keeps the current mode. Always shows
        the Pixel Art tab."""
        self.tool_var.set(tool)
        if tool in PAINT_TOOLS:
            self._last_paint_tool = tool
        wanted = "sprite" if tool == "move" else "edit" if tool in PAINT_TOOLS else self._art_mode
        if self.view_var.get() != wanted or self.notebook.index("current") != 1:
            self.view_var.set(wanted)
            self._on_view()
            self.tool_var.set(tool)  # _on_view may have picked a default for the mode
        self._on_tool()

    ZOOM_STEPS = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128)
    ZOOM_MIN_JUMP = 1.25  # each click changes the zoom by at least this factor

    def _art_layout(self, grid: int, w: int, h: int):
        """Where the sprite goes on the Pixel Art canvas: (k, x, y) with k
        whole px per art pixel. Fit (zoom None) = biggest k that fits;
        otherwise the zoom level, centred, shifted by the pan (clamped so
        the sprite always covers the canvas when it's bigger than it)."""
        k = self.zoom or max(1, min(w, h) // grid)
        size = grid * k
        pos = []
        for axis, room in ((0, w), (1, h)):
            centred = (room - size) // 2 + 1
            if size <= room:
                self.pan[axis] = 0
                pos.append(centred)
            else:
                p = min(1, max(room - size + 1, centred + self.pan[axis]))
                self.pan[axis] = p - centred
                pos.append(p)
        return k, pos[0], pos[1]

    def zoom_at(self, x: int, y: int, direction: int):
        """Step the zoom in (+1) or out (-1), keeping the art pixel under
        (x, y) where it is."""
        if self.small_art is None:
            return
        grid = self.small_art.width
        w, h = self._canvas_size(self.art_canvas)
        k, ox, oy = self._art_layout(grid, w, h)
        # The fitted zoom can be any whole number (e.g. 30x), so step to the
        # nearest listed level that's a real change, not 30x -> 32x.
        jump = self.ZOOM_MIN_JUMP
        steps = [s for s in self.ZOOM_STEPS if (s >= k * jump if direction > 0 else s <= k / jump)]
        if not steps:
            return
        new_k = steps[0] if direction > 0 else steps[-1]
        fit_k = max(1, min(w, h) // grid)
        # "Fit" is a stop on the way: crossing it in either direction lands
        # on it; below it the zoom goes down to 1x, the sprite's real size.
        if (direction < 0 and k > fit_k >= new_k) or (direction > 0 and k < fit_k <= new_k):
            self.zoom_fit()
            return
        ax, ay = (x - ox) / k, (y - oy) / k  # art coordinates under the pointer
        self.zoom = new_k
        size = grid * new_k
        self.pan = [round(x - ax * new_k) - ((w - size) // 2 + 1), round(y - ay * new_k) - ((h - size) // 2 + 1)]
        self._draw_art()

    def zoom_fit(self):
        self.zoom, self.pan = None, [0, 0]
        self._draw_art()

    def _pan_start(self, event):
        self._pan_drag = (event.x, event.y, list(self.pan))

    def _pan_move(self, event):
        if self._pan_drag and self.zoom:
            x0, y0, (px, py) = self._pan_drag
            self.pan = [px + event.x - x0, py + event.y - y0]
            self._draw_art()

    def _pan_end(self, _event):
        self._pan_drag = None

    def _zoom_label_text(self) -> str:
        if self.small_art is None:
            return ""
        w, h = self._canvas_size(self.art_canvas)
        k = self._art_layout(self.small_art.width, w, h)[0]
        return f"{k * 100}%" + ("  (fit)" if self.zoom is None else "  (actual size)" if k == 1 else "")

    def _editing(self) -> bool:
        return self.view_var.get() == "edit"

    # ---- layers <-> generated sprite --------------------------------------

    def _sync_layers(self):
        """A new generated sprite arrived (settings changed): update the live
        Base, rescale painted layers if the grid size changed."""
        grid = self.small_art.width
        if not self.layers:
            self.layers = [Layer(BASE_NAME, self.small_art.copy(), live=True, generated=True)]
            self.active_layer = 0
        else:
            if any(l.image.width != grid for l in self.layers):
                self.layers = resize_layers(self.layers, grid)
            for l in self.layers:
                if l.live:
                    l.image = self.small_art.copy()
        self._refresh_display()
        self._refresh_layer_panel()  # the layers panel is always visible (sidebar)

    def _refresh_display(self):
        from pixel_core import PREVIEW_SIZE
        grid = self.small_art.width
        self.display_art = composite(self.layers, grid) if self.layers else self.small_art.copy()
        self.display_big = self.display_art.resize((PREVIEW_SIZE, PREVIEW_SIZE), Image.Resampling.NEAREST)

    def has_edits(self) -> bool:
        return len(self.layers) > 1 or any(not l.live for l in self.layers)

    def base_frozen(self) -> bool:
        return any(l.generated and not l.live for l in self.layers)

    def reset_layers(self):
        """New image: start again from just the live Base."""
        self.layers, self.active_layer = [], 0
        self.history.clear()

    def _layers_changed(self, quick=False):
        """Redraw after an edit. quick=True during a paint stroke: only the
        sprite itself (thumbnails and palette update when the stroke ends)."""
        self._refresh_display()
        self._draw_art()
        if not quick:
            self._draw_palette()
            self._refresh_layer_panel()
            self._update_status()

    def _snapshot(self):
        self.history.push(self.layers, self.active_layer)

    def _freeze(self, layer: Layer):
        """Editing the live Base: stop regenerating it so edits survive."""
        if layer.live:
            layer.live = False
            if not self._told_frozen:
                self._told_frozen = True
                self._set_status("The Base layer is now edited, so changing settings won't overwrite it.\n"
                                 "Select it and press Regenerate to get the live version back (or Undo).")

    # ---- layer panel -------------------------------------------------------

    def _refresh_layer_panel(self):
        for child in self.layer_rows.winfo_children():
            child.destroy()
        self._layer_photos = []
        self._vis_vars = []
        rows = {}
        for i in reversed(range(len(self.layers))):  # top layer first, like image editors
            rows[i] = self._layer_row(i)
        # Show up to ROWS_SHOWN rows; more than that scroll (max 8 layers).
        self.layer_rows.update_idletasks()
        shown = list(rows.values())[: self.ROWS_SHOWN]
        height = sum(r.winfo_reqheight() + 2 for r in shown) if shown else 30
        self.layer_area.canvas.configure(height=height)
        if self.active_layer in rows:
            self.layer_area.after_idle(lambda r=rows[self.active_layer]: self.layer_area.show(r))
        layer = self.layers[self.active_layer] if self.layers else None
        n = len(self.layers)
        state = lambda ok: "normal" if ok else "disabled"  # noqa: E731
        self._layer_buttons["add"].configure(state=state(n < MAX_LAYERS))
        self._layer_buttons["dup"].configure(state=state(layer is not None and n < MAX_LAYERS))
        self._layer_buttons["delete"].configure(state=state(n > 1))
        self._layer_buttons["up"].configure(state=state(self.active_layer < n - 1))
        self._layer_buttons["down"].configure(state=state(self.active_layer > 0))
        self._layer_buttons["merge"].configure(state=state(self.active_layer > 0))
        self._layer_buttons["merge_all"].configure(state=state(sum(l.visible for l in self.layers) > 1))
        self._layer_buttons["regen"].configure(state=state(layer is not None and layer.generated and not layer.live))
        if layer:
            self.blend_box.set(layer.mode)
            self.opacity_scale.set(layer.opacity)
            self.opacity_label.configure(text=f"{layer.opacity}%")
            self.grad_blend_var.set(layer.fade is not None)
            # (a gradient layer fades with its own colours: "Fade to transparent")
            self.blend_toggle.state(["disabled"] if layer.gradient is not None else ["!disabled"])
        self._update_gradient_panel()  # a gradient layer selected (or not): show its settings

    def _layer_row(self, i: int):
        layer = self.layers[i]
        sel = "Sel" if i == self.active_layer else ""
        row = ttk.Frame(self.layer_rows, style=f"Row{sel}.TFrame", padding=(4, 2))
        row.pack(fill="x", pady=1)
        var = tk.BooleanVar(value=layer.visible)
        self._vis_vars.append(var)
        ttk.Checkbutton(row, variable=var, style=f"Row{sel}.TCheckbutton",
                        command=lambda i=i, v=var: self.set_visible(i, v.get())).pack(side="left")
        thumb = Image.new("RGBA", layer.image.size, (52, 52, 74, 255))
        thumb.alpha_composite(faded(layer))  # as it's shown (with its gradient blend)
        k = max(1, 32 // layer.image.width)  # whole-number scale: 16 -> 32 px, 32 -> 32 px (crisp)
        photo = ImageTk.PhotoImage(thumb.resize((layer.image.width * k,) * 2, Image.Resampling.NEAREST))
        self._layer_photos.append(photo)
        pic = tk.Label(row, image=photo, bd=0, bg=BG)
        pic.pack(side="left", padx=(2, 8))
        name = ttk.Label(row, text=layer.name, style=f"Row{sel}.TLabel")
        name.pack(side="left")
        tag = "live" if layer.live else ("edited" if layer.generated else "")
        info = " ".join(x for x in (tag, "fade" if layer.fade is not None else "",
                                    "" if layer.mode == "Normal" else layer.mode,
                                    "" if layer.opacity == 100 else f"{layer.opacity}%") if x)
        extra = ttk.Label(row, text=info, style=f"RowMuted{sel}.TLabel")
        extra.pack(side="right")
        for w in (row, pic, name, extra):
            w.bind("<Button-1>", lambda e, i=i: self.select_layer(i))
        name.bind("<Double-Button-1>", lambda e, i=i: self.rename_layer(i))
        Tooltip(name, "Double-click to rename")
        return row

    # ---- layer operations (each is one undo step) -------------------------

    def select_layer(self, i: int):
        self.active_layer = i
        if self.layers[i].fade is not None:
            self.grad_mode.set("blend")  # the Gradient tool now re-aims its blend
        self._refresh_layer_panel()
        if self.tool_var.get() == "gradient" and self._art_mode == "edit":
            self._draw_art()  # the direction guide follows the selection

    def add_layer(self):
        if len(self.layers) >= MAX_LAYERS:
            return
        self._snapshot()
        used = {l.name for l in self.layers}
        n = next(k for k in range(1, 100) if f"Layer {k}" not in used)
        self.layers.insert(self.active_layer + 1, Layer(f"Layer {n}", blank(self.small_art.width)))
        self.active_layer += 1
        self._layers_changed()

    def duplicate_layer(self):
        if len(self.layers) >= MAX_LAYERS:
            return
        self._snapshot()
        src = self.layers[self.active_layer].copy()
        src.name, src.live, src.generated = f"{src.name} copy", False, False
        self.layers.insert(self.active_layer + 1, src)
        self.active_layer += 1
        self._layers_changed()

    def delete_layer(self):
        if len(self.layers) <= 1:
            return
        self._snapshot()
        del self.layers[self.active_layer]
        self.active_layer = max(0, self.active_layer - 1)
        self._layers_changed()

    def move_layer_up(self):
        i = self.active_layer
        if i < len(self.layers) - 1:
            self._snapshot()
            self.layers[i], self.layers[i + 1] = self.layers[i + 1], self.layers[i]
            self.active_layer += 1
            self._layers_changed()

    def move_layer_down(self):
        i = self.active_layer
        if i > 0:
            self._snapshot()
            self.layers[i], self.layers[i - 1] = self.layers[i - 1], self.layers[i]
            self.active_layer -= 1
            self._layers_changed()

    def merge_layer_down(self):
        i = self.active_layer
        if i <= 0:
            return
        self._snapshot()
        if self.layers[i - 1].live:
            self._freeze(self.layers[i - 1])
        self.layers = merge_down(self.layers, i)
        self.active_layer = i - 1
        self._layers_changed()

    def merge_visible_layers(self):
        if sum(l.visible for l in self.layers) < 2:
            return
        self._snapshot()
        first_visible = next(i for i, l in enumerate(self.layers) if l.visible)
        self.layers = merge_visible(self.layers)
        self.active_layer = first_visible
        self._layers_changed()

    def regenerate_base(self):
        layer = self.layers[self.active_layer]
        if layer.generated and not layer.live:
            self._snapshot()
            layer.image, layer.live = self.small_art.copy(), True
            self._layers_changed()

    def set_visible(self, i: int, visible: bool):
        self._snapshot()
        self.layers[i].visible = visible
        self._layers_changed()

    def set_blend_mode(self, mode: str):
        layer = self.layers[self.active_layer]
        if mode in BLEND_MODES and mode != layer.mode:
            self._snapshot()
            layer.mode = mode
            self._layers_changed()

    def _on_opacity(self, value):
        if not self.layers:
            return
        layer = self.layers[self.active_layer]
        v = round(float(value))
        if v != layer.opacity:
            layer.opacity = v
            self.opacity_label.configure(text=f"{v}%")
            self._debounce("opacity", 30, self._layers_changed)

    def rename_layer(self, i: int):
        name = simpledialog.askstring("Rename layer", "Layer name:", initialvalue=self.layers[i].name,
                                      parent=self.root)
        if name and name.strip():
            self._snapshot()
            self.layers[i].name = name.strip()[:24]
            self._layers_changed()

    def undo(self):
        self._restore(self.history.undo(self.layers, self.active_layer))

    def redo(self):
        self._restore(self.history.redo(self.layers, self.active_layer))

    def _restore(self, snap):
        if snap is None or self.small_art is None:
            return
        layers, active = snap
        self.layers = resize_layers(layers, self.small_art.width)
        for l in self.layers:
            if l.live:  # a live Base follows the *current* settings
                l.image = self.small_art.copy()
        self.active_layer = min(active, len(self.layers) - 1)
        self._layers_changed()

    # ---- painting ------------------------------------------------------------

    def _on_tool(self):
        cursor = {v: c for _, v, c, _ in TOOLS}.get(self.tool_var.get(), "")
        self.art_canvas.configure(cursor=cursor if self.original is not None else "")
        self._gradient_tool_changed()

    def pick_paint_colour(self):
        rgb, _ = colorchooser.askcolor(color=hex_colour(self.paint_colour), title="Paint colour", parent=self.root)
        if rgb:
            self.set_paint_colour((*(int(c) for c in rgb), 255))

    def set_paint_colour(self, rgba):
        self.paint_colour = tuple(rgba[:3]) + (255,)
        self._show_paint_colour()

    def _show_paint_colour(self):
        self.colour_swatch.configure(bg=hex_colour(self.paint_colour))

    def _swatch_at(self, x, y):
        for x0, y0, x1, y1, rgba in self._swatches:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return rgba
        return None

    def _on_palette_click(self, event):
        """Click a swatch (any view): paint with that colour - Pen tool,
        Pixel Art tab in Edit mode. With the Gradient tool it's the
        gradient's start colour instead."""
        rgba = self._swatch_at(event.x, event.y)
        if rgba is None:
            return
        if self.tool_var.get() == "gradient":
            self._gradient_palette_pick(0, rgba)
            return
        self.set_paint_colour(rgba)
        self.select_tool("pen")

    def _on_palette_right_click(self, event):
        """With the Gradient tool: the gradient's end colour."""
        rgba = self._swatch_at(event.x, event.y)
        if rgba is not None and self.tool_var.get() == "gradient":
            self._gradient_palette_pick(1, rgba)

    def _pixel_at(self, x, y):
        ox, oy, k = self._art_origin
        grid = self.small_art.width
        px, py = (x - ox) // k, (y - oy) // k
        return (px, py) if 0 <= px < grid and 0 <= py < grid else None

    def _edit_press(self, event, erase=False):
        if self.small_art is None or not self.layers:
            return
        if self.tool_var.get() == "gradient":
            if not erase:  # (right-click does nothing with the Gradient tool)
                self._gradient_press(event)
            return
        p = self._pixel_at(event.x, event.y)
        if p is None:
            return
        tool = "eraser" if erase else self.tool_var.get()
        if tool == "picker":
            colour = self.display_art.getpixel(p)
            if colour[3]:
                self.set_paint_colour(colour)
            return
        layer = self.layers[self.active_layer]
        if not layer.visible:
            self._set_status(f"'{layer.name}' is hidden - show it (tick its box) to paint on it.")
            return
        self._snapshot()
        if layer.gradient is not None:
            self._flatten_gradient(self.active_layer)  # paint on what it shows, as pixels
        self._freeze(layer)
        if tool == "fill":
            flood_fill(layer.image, *p, self.paint_colour)
            self._layers_changed()
            return
        self._put(layer, p, tool == "eraser")
        self._stroke = (p, tool == "eraser")
        self._layers_changed(quick=True)

    def _edit_drag(self, event):
        if self._grad_drag is not None:
            self._gradient_drag(event)
            return
        if not self._stroke:
            return
        p = self._pixel_at(event.x, event.y)
        (lx, ly), erase = self._stroke
        if p is None or p == (lx, ly):
            return
        layer = self.layers[self.active_layer]
        for q in line_pixels(lx, ly, *p):  # no gaps on fast drags
            self._put(layer, q, erase)
        self._stroke = (p, erase)
        self._layers_changed(quick=True)

    def _edit_release(self, event):
        if self._grad_drag is not None:
            self._gradient_release(event)
            return
        if self._stroke:
            self._stroke = None
            self._layers_changed()

    def _put(self, layer, p, erase):
        layer.image.putpixel(p, (0, 0, 0, 0) if erase else self.paint_colour)

    def _edit_hover(self, event):
        c = self.art_canvas
        c.delete("hover")
        if not self._editing() or self.small_art is None:
            return
        p = self._pixel_at(event.x, event.y)
        if p:
            ox, oy, k = self._art_origin
            c.create_rectangle(ox + p[0] * k, oy + p[1] * k, ox + (p[0] + 1) * k - 1, oy + (p[1] + 1) * k - 1,
                               outline=CYAN, tags="hover")

    def _draw_editor(self, c, w, h):
        """The composite, enlarged, with a faint pixel grid to paint on."""
        art = self.display_art
        g = art.width
        k, ox, oy = self._art_layout(g, w, h)  # fit or zoomed (+ pan), whole-number k
        big = art.resize((g * k, g * k), Image.Resampling.NEAREST)
        view = checkerboard(big.width, big.height, max(4, k // 2)).convert("RGBA")
        view.alpha_composite(big)
        if k >= 6:
            grid = Image.new("RGBA", view.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(grid)
            for i in range(1, g):
                d.line([(i * k, 0), (i * k, view.height)], fill=(255, 255, 255, 34))
                d.line([(0, i * k), (view.width, i * k)], fill=(255, 255, 255, 34))
            view.alpha_composite(grid)
        self._art_origin = (ox, oy, k)
        self._show("art", c, view, ox, oy)
        self._draw_gradient_guide(c)
