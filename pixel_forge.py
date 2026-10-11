"""
PIXEL FORGE (desktop) - an offline pixel art generator in its own window.

Same pipeline as the browser version (see pixel_core.py), but built with
Tkinter, which ships with Python, so the only dependency is Pillow.
No browser, no server, no network.

Run with:
    python pixel_forge.py [optional/image/path.png]
"""

import json
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from PIL import Image, ImageTk

from edit_session import (DESCRIPTION, EXIT_ERROR, EditSessionMixin, parse_args, write_result)
from editor_ui import LayerEditorMixin, checkerboard
from gradient_ui import GradientMixin
from palette_ui import PaletteLibraryMixin
from platform_support import MONO, bind_wheel, config_dir, fit_window, open_folder, use_bundled_fonts
from projection_ui import ProjectionMixin
from mc_preview import best_fit, pretty_name, render_inventory
from ui_widgets import ScrollArea, Tooltip
from waitbar import WaitBar
from pixel_core import (GRID_OPTIONS, PREVIEW_SIZE, ai_model_loaded, ai_status, auto_line_color, find_subject,
                        pixelate_detailed, subject_is_cached)

# --------------------------------------------------------------------------
# Look & feel: a dark, arcade-cabinet palette
# --------------------------------------------------------------------------

BG = "#12121c"        # window background
PANEL = "#1c1c2b"     # sidebar / image panels
BORDER = "#2e2e45"
TEXT = "#e8e8f0"
MUTED = "#8a8aa3"
ACCENT = "#ff3e7f"    # hot pink
ACCENT_HI = "#ff6b9d"
CYAN = "#3ef0ff"

FONT = (MONO, 10)
FONT_BOLD = (MONO, 10, "bold")
FONT_HEAD = (MONO, 12, "bold")
FONT_TITLE = (MONO, 22, "bold")

APP_DIR = Path(__file__).resolve().parent
FORGE_ICO = APP_DIR / "forge.ico"                # app + launcher icon (built from Forge.png)
FORGE_PNG = APP_DIR / "Forge.png"                # the icon art itself
# The launcher that started us (it passes its own path, wherever it lives),
# else the one build-launcher.bat makes in the app folder.
LAUNCHER_EXE = Path(os.environ.get("PIXEL_FORGE_LAUNCHER") or APP_DIR / "Pixel Forge.exe")
APP_ID = "PixelForge.Desktop"                    # Windows taskbar identity

FILE_TYPES = [("Images", "*.png *.jpg *.jpeg"), ("PNG", "*.png"), ("JPEG", "*.jpg *.jpeg")]
AS_IS_TYPES = [("Images", "*.png *.gif *.bmp *.webp *.jpg *.jpeg"), ("PNG", "*.png"), ("All files", "*.*")]
MAX_AS_IS = 256  # the biggest (square) picture Open As-Is takes, as Grass Block's textures
CONVERT_S_PER_MP = 0.06   # converting takes about this long per megapixel (learnt as it goes)
CONVERT_ON_THREAD = 0.3   # pictures expected to take longer convert on a thread, with a progress bar

# A classic space invader, used for the window icon and the header logo.
INVADER = [
    "..X.....X..",
    "...X...X...",
    "..XXXXXXX..",
    ".XX.XXX.XX.",
    "XXXXXXXXXXX",
    "X.XXXXXXX.X",
    "X.X.....X.X",
    "...XX.XX...",
]


def make_invader(scale: int) -> Image.Image:
    """Draw the invader sprite and blow it up with NEAREST (sharp pixels)."""
    w, h = len(INVADER[0]), len(INVADER)
    img = Image.new("RGBA", (w + 2, w + 2), (0, 0, 0, 0))  # square, padded
    top = (w + 2 - h) // 2
    for y, row in enumerate(INVADER):
        for x, ch in enumerate(row):
            if ch == "X":
                img.putpixel((x + 1, y + top), (0x3E, 0xF0, 0xFF, 255))
    return img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)


# --------------------------------------------------------------------------
# Remembered settings (currently just the export folder)
# --------------------------------------------------------------------------

def settings_file() -> Path:
    """settings.json in the user's own config folder (%APPDATA%\\PixelForge on
    Windows, ~/.config/PixelForge on Linux)."""
    return config_dir() / "settings.json"


def load_settings() -> dict:
    try:
        data = json.loads(settings_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}  # first run, or an unreadable file: start fresh


def save_settings(settings: dict) -> None:
    path = settings_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError:
        pass  # not being able to remember a setting shouldn't break saving art


def load_icon_image(size: int) -> Image.Image | None:
    """The app icon at `size` px, crisp, or None if it can't be read.

    Accepts a real multi-size forge.ico, or a plain PNG (even one renamed to
    .ico), falling back to Forge.png. Pixel art is enlarged/reduced with
    NEAREST so it stays sharp. Never raises: a bad icon must not stop the
    app from opening."""
    for path in (FORGE_ICO, FORGE_PNG):
        try:
            img = Image.open(path)
            if img.format == "ICO":
                sizes = img.info.get("sizes") or set()
                if (size, size) in sizes:
                    img.size = (size, size)  # pick that frame of the .ico
            return img.convert("RGBA").resize((size, size), Image.Resampling.NEAREST)
        except Exception:  # missing, unreadable, or not an image
            continue
    return None


def texture_id(name: str) -> str:
    """'Flesh Axe' -> 'flesh_axe': the lowercase, underscore style
    Minecraft uses for texture and item IDs."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "item"


# --------------------------------------------------------------------------
# The app
# --------------------------------------------------------------------------

class PixelForgeApp(EditSessionMixin, GradientMixin, PaletteLibraryMixin, ProjectionMixin, LayerEditorMixin):
    # Edit view: editor_ui.py, gradients: gradient_ui.py, palette library: palette_ui.py,
    # texture projection: projection_ui.py, --edit sessions: edit_session.py
    def __init__(self, root: tk.Tk):
        self.root = root
        self.original: Image.Image | None = None
        self.source_path: Path | None = None
        self.small_art: Image.Image | None = None   # grid x grid
        self.big_art: Image.Image | None = None     # PREVIEW_SIZE export
        self._photos: dict[str, ImageTk.PhotoImage] = {}  # keep refs alive
        self._pending: dict[str, str] = {}               # debounce timers
        self.region: tuple[int, int, int, int] | None = None  # source square the art covers
        self._orig_view: Image.Image | None = None
        self._orig_view_key = None

        # Defaults tuned for 16x16 sprites: few colours, light detail lines.
        self.grid_var = tk.IntVar(value=16)
        self.colors_var = tk.IntVar(value=10)
        self.enhance_var = tk.BooleanVar(value=True)
        self.outline_var = tk.StringVar(value="outside")
        self.detail_var = tk.IntVar(value=30)
        self.fit_var = tk.BooleanVar(value=True)
        self.transparent_var = tk.BooleanVar(value=False)
        self.line_color: tuple[int, int, int] | None = None  # None = auto
        self.scale_var = tk.IntVar(value=100)   # subject size in the grid, percent
        self.offset = [0, 0]                    # subject nudge, in art pixels
        self._drag = None                       # (mouse x, mouse y, offset) at drag start
        self._art_k = 1                         # screen pixels per art pixel in the preview
        self.bg_method = tk.StringVar(value="plain")  # "plain" flood fill or "ai" (rembg)
        self._ai_job = None                     # {"image", "done", "error"} while AI runs
        self._match_job = None                  # {"image", "key", "done", "result"} while matching
        self._convert_job = None                # a big picture converting on a thread (see process)
        self._matched = None                    # (image, settings key, result) of the last match
        # "sprite" (Move tool), "edit" (paint tools) or "game" (Minecraft tab)
        self.view_var = tk.StringVar(value="sprite")
        self.item_name = tk.StringVar(value="Item")   # tooltip name, and the export file name
        # Export folder: saves go straight there (no dialog) when set.
        self.settings = load_settings()
        folder = self.settings.get("export_dir")
        self.export_dir: Path | None = Path(folder) if folder else None
        self._overwrite_ok: set[Path] = set()  # files the user agreed to replace this session
        self._last = None  # (result, settings, matched) currently shown, for the status line
        self._status_note: str | None = None  # shown first in the next status update (see _update_status)
        self._init_editor_state()

        root.title("Pixel Forge")
        root.configure(bg=BG)
        fit_window(root, 1140, 800, 900, 720)  # (less on a small screen, such as a Steam Deck's)
        self._icon = ImageTk.PhotoImage(make_invader(4))  # the header logo
        # Window + taskbar icon: the forge anvil (same icon as the launcher).
        try:
            if sys.platform != "win32" or not FORGE_ICO.exists():
                raise tk.TclError("no .ico")
            root.iconbitmap(default=str(FORGE_ICO))  # every size from the .ico, crisp
        except tk.TclError:  # no icon, or not a real .ico: use the PNG art, else the invader
            art = load_icon_image(32)
            self._window_icon = ImageTk.PhotoImage(art) if art else self._icon
            root.iconphoto(True, self._window_icon)

        self._style()
        self._build()
        self._build_editor_ui()
        self._build_palette_library()
        self._build_projection_ui()
        # Progress bars for waits, in place of the status line (waitbar.py)
        self.waits = WaitBar(root, self.status_bar, covers=[self.status],
                             times=self.settings.setdefault("wait_times", {}),
                             save=lambda: save_settings(self.settings))
        self._bind_keys()

    # ---- theme -----------------------------------------------------------

    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")  # the most restylable built-in ttk theme
        s.configure(".", background=PANEL, foreground=TEXT, font=FONT,
                    bordercolor=BORDER, focuscolor=PANEL)
        s.configure("Bg.TFrame", background=BG)
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("TLabel", background=PANEL, foreground=TEXT)
        s.configure("Bg.TLabel", background=BG)
        s.configure("Title.TLabel", background=BG, foreground=TEXT, font=FONT_TITLE)
        s.configure("Tagline.TLabel", background=BG, foreground=MUTED)
        s.configure("Head.TLabel", foreground=CYAN, font=FONT_HEAD)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Value.TLabel", foreground=ACCENT, font=FONT_BOLD)

        # In clam, the radio circle is filled with indicatorbackground and the
        # "selected" dot is drawn in indicatorforeground.
        s.configure("TRadiobutton", background=PANEL, foreground=TEXT,
                    indicatorbackground=BG, indicatorforeground=ACCENT,
                    upperbordercolor=MUTED, lowerbordercolor=MUTED, indicatormargin=(0, 0, 6, 0))
        s.map("TRadiobutton",
              background=[("active", PANEL)],
              foreground=[("selected", ACCENT)],
              indicatorbackground=[("pressed", BORDER)])
        s.configure("TCheckbutton", background=PANEL, foreground=TEXT,
                    indicatorbackground=BG, indicatorforeground=ACCENT,
                    upperbordercolor=MUTED, lowerbordercolor=MUTED, indicatormargin=(0, 0, 6, 0))
        s.map("TCheckbutton",
              background=[("active", PANEL)],
              foreground=[("selected", ACCENT)],
              indicatorbackground=[("pressed", BORDER)])
        s.configure("Small.TButton", padding=(8, 3), font=FONT)
        s.configure("Arrow.TButton", padding=(2, 3), font=FONT)
        s.configure("Compact.TButton", padding=(4, 3), font=FONT)
        # Segmented Sprite / In-game switch: radio buttons drawn as buttons.
        s.configure("Seg.Toolbutton", background=BORDER, foreground=TEXT, padding=(10, 2), font=FONT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        s.map("Seg.Toolbutton",
              background=[("selected", ACCENT), ("active", "#3b3b58")],
              foreground=[("selected", "#12121c")])
        # Workspace tabs (Original / Pixel Art / Minecraft)
        s.configure("Work.TNotebook", background=BG, borderwidth=0, bordercolor=BORDER,
                    lightcolor=PANEL, darkcolor=PANEL, tabmargins=(0, 0, 0, 0))
        s.configure("Work.TNotebook.Tab", background=BORDER, foreground=MUTED, padding=(14, 5),
                    font=FONT_BOLD, bordercolor=BORDER, lightcolor=BORDER)
        s.map("Work.TNotebook.Tab",
              background=[("selected", PANEL), ("active", "#3b3b58")],
              foreground=[("selected", CYAN), ("active", TEXT)],
              lightcolor=[("selected", PANEL)],
              expand=[("selected", (0, 0, 0, 0))])
        s.configure("Dark.Vertical.TScrollbar", background=BORDER, troughcolor=PANEL, bordercolor=PANEL,
                    lightcolor=BORDER, darkcolor=BORDER, arrowcolor=MUTED, gripcount=0, arrowsize=12)
        s.map("Dark.Vertical.TScrollbar", background=[("active", ACCENT), ("pressed", ACCENT_HI)])
        s.configure("Match.TButton", padding=(10, 3), font=FONT_BOLD, background=ACCENT,
                    foreground="#12121c", bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT)
        s.map("Match.TButton",
              background=[("disabled", PANEL), ("active", ACCENT_HI)],
              foreground=[("disabled", CYAN)],
              bordercolor=[("disabled", BORDER)])

        s.configure("Horizontal.TScale", background=ACCENT, troughcolor=BG, gripcount=0,
                    bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)
        s.map("Horizontal.TScale", background=[("active", ACCENT_HI)])

        s.configure("TButton", background=BORDER, foreground=TEXT, padding=(10, 7),
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, font=FONT_BOLD)
        s.map("TButton",
              background=[("disabled", PANEL), ("active", "#3b3b58")],
              foreground=[("disabled", "#55556b")],
              bordercolor=[("disabled", BORDER)])
        s.configure("Accent.TButton", background=ACCENT, foreground="#12121c",
                    bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT)
        s.map("Accent.TButton", background=[("active", ACCENT_HI)])

    # ---- layout ----------------------------------------------------------

    def _build(self):
        """Workspace layout (Photoshop-style):

            top_bar        logo, file actions, Item name, export folder
            left_strip     44 px tool strip          | center_workspace | right_sidebar 300 px
        """
        outer = ttk.Frame(self.root, style="Bg.TFrame", padding=8)
        outer.pack(fill="both", expand=True)
        self._build_top_bar(outer)

        body = ttk.Frame(outer, style="Bg.TFrame")
        body.pack(fill="both", expand=True)
        # Pack order matters: the fixed-width columns claim their space first,
        # the centre takes whatever is left.
        self.left_strip = ttk.Frame(body, style="Panel.TFrame", width=44)
        self.left_strip.pack(side="left", fill="y")
        self.left_strip.pack_propagate(False)
        self._build_sidebar(body)
        self.center_workspace = ttk.Frame(body, style="Bg.TFrame")
        self.center_workspace.pack(side="left", fill="both", expand=True, padx=8)

        self._build_center(self.center_workspace)

    def _build_center(self, parent):
        """Centre workspace: a one-line status bar docked at the bottom, and a
        notebook with one tab per canvas. Match Original sits at the right
        end of the tab row (placed over the notebook's empty header space),
        so it never competes with a title for width."""
        self.status_full = "No image loaded."  # the status bar shows one line of this
        status_bar = self.status_bar = ttk.Frame(parent, style="Panel.TFrame", padding=(8, 4))
        status_bar.pack(side="bottom", fill="x", pady=(8, 0))  # (a progress bar takes its place while waiting)
        self.status = ttk.Label(status_bar, text=self.status_full, style="Muted.TLabel", anchor="w")
        self.status.pack(fill="x")
        self.status.bind("<Configure>", lambda e: self._fit_status())
        Tooltip(self.status, lambda: self.status_full if self.status.cget("text") != self.status_full else "")

        self.notebook = ttk.Notebook(parent, style="Work.TNotebook")
        self.notebook.pack(fill="both", expand=True)

        # Tab 1: the source image, full size, with the crop box.
        orig_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=12)
        self.orig_title = ttk.Label(orig_tab, text="Source image", style="Muted.TLabel")
        self.orig_title.pack(anchor="w", pady=(0, 8))
        self.orig_canvas = tk.Canvas(orig_tab, bg=BG, highlightthickness=1, highlightbackground=BORDER)
        self.orig_canvas.pack(fill="both", expand=True)

        # Tab 2: the sprite - Sprite (move/scale subject) or Edit (paint, layers).
        self.art_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=12)
        head = ttk.Frame(self.art_tab, style="Panel.TFrame")
        head.pack(fill="x", pady=(0, 8))
        self.art_title = ttk.Label(head, text="PIXEL ART", style="Muted.TLabel")
        self.art_title.pack(side="left")
        # Zoom readout + Fit (the tools in the left strip choose Sprite/Edit).
        fit = ttk.Button(head, text="Fit", style="Small.TButton", width=0, command=self.zoom_fit)
        fit.pack(side="right")
        Tooltip(fit, "Fit the sprite to the view (double-click with Zoom)")
        self.zoom_label = ttk.Label(head, text="", style="Value.TLabel")
        self.zoom_label.pack(side="right", padx=(0, 8))
        self.art_canvas = tk.Canvas(self.art_tab, bg=BG, highlightthickness=1, highlightbackground=BORDER)
        self.art_canvas.pack(fill="both", expand=True)

        # Tab 3: the Minecraft inventory mock-up, on its own canvas.
        game_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=12)
        self.game_canvas = tk.Canvas(game_tab, bg=BG, highlightthickness=1, highlightbackground=BORDER)
        self.game_canvas.pack(fill="both", expand=True)

        self.notebook.add(orig_tab, text="Original")
        self.notebook.add(self.art_tab, text="Pixel Art")
        self.notebook.add(game_tab, text="Minecraft")
        self.notebook.select(self.art_tab)
        self._art_mode = "sprite"  # what the Pixel Art tab shows: "sprite" or "edit"
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._on_tab_changed())

        # "Match Original": a slower pass that re-colours the sprite to read
        # as close to the source as possible (see pixel_core._match_source).
        self.match_btn = ttk.Button(parent, text="Match Original", style="Match.TButton",
                                    command=self.match_original, state="disabled")
        self.match_btn.place(relx=1.0, x=0, y=0, anchor="ne")
        self.match_btn.lift()

        self.orig_canvas.bind("<Configure>", lambda e: self._debounce("orig", 40, self._draw_original))
        self.art_canvas.bind("<Configure>", lambda e: self._debounce(
            "art", 40, lambda: (self._draw_art(), self._draw_palette())))
        self.game_canvas.bind("<Configure>", lambda e: self._debounce("game", 40, self._draw_game))
        self._draw_original()
        self._draw_art()

    # ---- status bar ----------------------------------------------------------

    def _set_status(self, text: str):
        """Set the status. The bar shows it as one line (shortened with
        '...' if needed); hovering shows the full text."""
        self.status_full = text
        self._fit_status()

    def _fit_status(self):
        line = "   ·   ".join(part for part in self.status_full.splitlines() if part.strip())
        if not hasattr(self, "_status_font"):
            self._status_font = tkfont.Font(font=FONT)
        measure = self._status_font.measure
        room = max(40, self.status.winfo_width() - 8)
        if measure(line) > room:
            lo, hi = 0, len(line)  # longest prefix that fits with "..." (binary search)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                lo, hi = (mid, hi) if measure(line[:mid] + "...") <= room else (lo, mid - 1)
            line = line[:lo].rstrip(" ·") + "..."
        self.status.configure(text=line)

    def _build_top_bar(self, parent):
        """One row replacing the old big header: logo, file actions, Item
        name, export folder. The Item name field is packed last with
        expand=True, so when the window is narrow it shrinks first and
        nothing else gets clipped."""
        self.top_bar = ttk.Frame(parent, style="Panel.TFrame", padding=(8, 4))
        self.top_bar.pack(fill="x", pady=(0, 8))
        bar = self.top_bar
        logo = load_icon_image(32)  # the anvil, same as the launcher and window icon
        self._logo = ImageTk.PhotoImage(logo) if logo else self._icon
        ttk.Label(bar, image=self._logo).pack(side="left", padx=(0, 6))
        ttk.Label(bar, text="PIXEL FORGE", style="Head.TLabel").pack(side="left", padx=(0, 16))

        open_btn = ttk.Button(bar, text="Open...", style="Accent.TButton", width=8, command=self.open_dialog)
        open_btn.pack(side="left", padx=(0, 4))
        Tooltip(open_btn, "Open a picture to make pixel art from (Ctrl+O).\n"
                          "Small square pictures: you're asked whether to open them as they are.\n"
                          "Ctrl+Shift+O opens pixel art as it is, no conversion.")
        self.save_btn = ttk.Button(bar, text="Save Art", state="disabled", width=9,
                                   command=lambda: self.save_dialog(raw=False))
        self.save_btn.pack(side="left", padx=(0, 4))
        self.save_raw_btn = ttk.Button(bar, text="Save Sprite", state="disabled", width=11,
                                       command=lambda: self.save_dialog(raw=True))
        self.save_raw_btn.pack(side="left", padx=(0, 12))

        # Right end: export folder [path] [Open] [x]
        ttk.Button(bar, text="✕", style="Arrow.TButton", width=2,
                   command=self.clear_export_dir).pack(side="right")
        self.open_dir_btn = ttk.Button(bar, text="Open", style="Small.TButton", width=5,
                                       command=self.open_export_dir)
        self.open_dir_btn.pack(side="right", padx=(3, 3))
        self.export_btn = ttk.Button(bar, style="Small.TButton", width=17, command=self.choose_export_dir)
        self.export_btn.pack(side="right")
        self._show_export_dir()

        # Item name: the in-game tooltip and the export file name (flesh_axe.png).
        self.name_row = ttk.Frame(bar, style="Panel.TFrame")
        self.name_row.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ttk.Label(self.name_row, text="Item name").pack(side="left", padx=(0, 8))
        name_entry = tk.Entry(self.name_row, textvariable=self.item_name, bg=BG, fg=TEXT, insertbackground=TEXT,
                              relief="flat", highlightthickness=1, highlightbackground=BORDER,
                              highlightcolor=ACCENT, font=FONT, width=12)
        name_entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.item_name.trace_add("write", lambda *_: self._debounce("art", 60, self._draw_art))

    def _build_sidebar(self, parent):
        """The right sidebar (300 px), stacked like an image editor's panels:

            PALETTE      fixed at the top (paint colour + clickable swatches)
            ADJUSTMENTS  the generation settings; takes the space that's left
                         and scrolls, so nothing clips at 720 px
            LAYERS       anchored at the bottom (built by editor_ui, packed
                         *before* Adjustments so it always gets its room)
        """
        side = ttk.Frame(parent, style="Panel.TFrame", padding=12, width=300)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)
        self.right_sidebar = side

        # -- Palette --
        palette = ttk.Frame(side, style="Panel.TFrame")
        palette.pack(side="top", fill="x")
        self.palette_head = ttk.Frame(palette, style="Panel.TFrame")  # editor_ui adds the paint colour here
        self.palette_head.pack(fill="x")
        self.footer_label = ttk.Label(self.palette_head, text="PALETTE", style="Head.TLabel")
        self.footer_label.pack(side="left")
        self.palette_more = ttk.Label(self.palette_head, style="Muted.TLabel")  # "+N more" past PALETTE_ROWS
        self.palette_more.pack(side="left", padx=(8, 0))
        self.palette_canvas = tk.Canvas(palette, bg=PANEL, highlightthickness=0, height=19, cursor="hand2")
        self.palette_canvas.pack(fill="x", pady=(8, 0))
        Tooltip(self.palette_canvas, lambda: "Click: gradient start colour  ·  right-click: end colour"
                if self.tool_var.get() == "gradient" else "Click a colour to paint with it")
        self._sidebar_rule(side)

        # -- Adjustments (scrolling) --
        self.adjust_area = ScrollArea(side, bg=PANEL, height=120)
        self.adjust_area.pack(side="top", fill="both", expand=True)
        self.adjust_scroll = self.adjust_area.canvas
        side = self.adjust_area.inner  # everything below goes into the scrolling area

        # -- Grid & colours --
        ttk.Label(side, text="SPRITE", style="Head.TLabel").pack(anchor="w", pady=(0, 8))
        self.grid_title = ttk.Label(side, text="Grid Resolution")
        self.grid_title.pack(anchor="w")
        self.grid_row = self._radio_row(side, self.grid_var, [(label, size) for label, size in GRID_OPTIONS.items()])

        # ttk.Scale is continuous; the handlers snap it to whole numbers.
        self.scale, self.colors_label = self._slider(side, "Color Palette Limit", 2, 64,
                                                     self.colors_var, self._on_slide)
        ttk.Checkbutton(side, text="Sprite clean-up", variable=self.enhance_var,
                        command=self._settings_changed).pack(anchor="w", pady=(8, 0))

        # -- Outline --
        ttk.Label(side, text="OUTLINE", style="Head.TLabel").pack(anchor="w", pady=(8, 4))
        self._radio_row(side, self.outline_var, [("Off", "off"), ("Outside", "outside"), ("Inside", "inside")])
        self.detail_scale, self.detail_label = self._slider(side, "Detail Lines", 0, 100,
                                                            self.detail_var, self._on_detail)
        self.detail_label.configure(text=self._detail_text())

        row = ttk.Frame(side, style="Panel.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="Line Colour").pack(side="left")
        ttk.Button(row, text="Auto", style="Small.TButton", width=5,
                   command=lambda: self._set_line_color(None)).pack(side="right")
        ttk.Button(row, text="Pick", style="Small.TButton", width=5,
                   command=self.pick_line_color).pack(side="right", padx=(0, 4))
        self.swatch = tk.Canvas(row, width=18, height=18, bg=PANEL, highlightthickness=1,
                                highlightbackground=MUTED)
        self.swatch.pack(side="right", padx=(0, 8))
        self._draw_swatch()

        # -- Subject --
        ttk.Label(side, text="SUBJECT", style="Head.TLabel").pack(anchor="w", pady=(8, 4))
        row = ttk.Frame(side, style="Panel.TFrame")
        row.pack(fill="x", pady=(0, 2))
        ttk.Label(row, text="Remove BG").pack(side="left", padx=(0, 12))
        for text, value in (("Plain", "plain"), ("AI", "ai")):
            ttk.Radiobutton(row, text=text, value=value, variable=self.bg_method,
                            command=self._on_bg_method).pack(side="left", padx=(0, 14))
        row = ttk.Frame(side, style="Panel.TFrame")  # both options on one row
        row.pack(fill="x", pady=2)
        ttk.Checkbutton(row, text="Zoom to fit", variable=self.fit_var,
                        command=self._settings_changed).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row, text="Transparent BG", variable=self.transparent_var,
                        command=self._settings_changed).pack(side="left")

        # Size and position of the subject inside the grid. Also: Ctrl+wheel
        # over the pixel art scales, dragging it moves the subject.
        self.size_scale, self.size_label = self._slider(side, "Scale", 50, 150,
                                                        self.scale_var, self._on_scale)
        self.size_label.configure(text=f"{self.scale_var.get()}%")
        row = ttk.Frame(side, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Move").pack(side="left")
        ttk.Button(row, text="Reset", style="Small.TButton", width=5,
                   command=self.reset_transform).pack(side="right")
        for text, dx, dy in (("→", 1, 0), ("↓", 0, 1), ("↑", 0, -1), ("←", -1, 0)):
            ttk.Button(row, text=text, style="Arrow.TButton", width=2,
                       command=lambda dx=dx, dy=dy: self.nudge(dx, dy)).pack(side="right", padx=(0, 3))

    @staticmethod
    def _sidebar_rule(parent):
        """A 1 px divider between sidebar sections."""
        tk.Frame(parent, bg=BORDER, height=1).pack(side="top", fill="x", pady=8)  # spacing scale: 4 / 8 / 12 / 16

    def _on_global_wheel(self, event):
        """Mouse wheel over a scrolling sidebar area scrolls it. Other wheel
        uses (scaling the sprite on its canvas) have their own bindings."""
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        for area in (self.adjust_area, getattr(self, "layer_area", None), getattr(self, "_lib_area", None)):
            if area is not None and area.contains(widget):
                area.scroll(-1 if event.delta > 0 else 1)
                return

    def _radio_row(self, parent, var, options):
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=(4, 0))
        for label, value in options:
            ttk.Radiobutton(row, text=label, value=value, variable=var,
                            command=self._settings_changed).pack(side="left", padx=(0, 14))
        return row

    def _fix_grid(self, size: int):
        """A texture made for another app keeps its size (edit_session's
        convert mode): the grid choice becomes a fixed readout."""
        self.grid_row.pack_forget()
        self.grid_title.configure(text=f"Grid Resolution: {size} x {size} (the texture's size)")

    def _slider(self, parent, title, lo, hi, var, command):
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text=title).pack(side="left")
        value_label = ttk.Label(row, text=str(var.get()), style="Value.TLabel")
        value_label.pack(side="right")
        scale = ttk.Scale(parent, from_=lo, to=hi, orient="horizontal", command=command)
        scale.set(var.get())
        scale.pack(fill="x", pady=(2, 0))
        return scale, value_label

    def _bind_keys(self):
        self.root.bind("<Control-o>", lambda e: self.open_dialog())
        self.root.bind("<Control-O>", lambda e: self.open_as_is())  # Ctrl+Shift+O: pixel art, as it is
        # In an edit session Ctrl+S is Save & Return.
        self.root.bind("<Control-s>", lambda e: self.session_save() if self.session else self.save_dialog(raw=False))
        self.root.bind("<Control-S>", lambda e: self.session or self.save_dialog(raw=True))  # Ctrl+Shift+S
        # Ctrl+arrows nudge the subject, Ctrl+=/- scale it, Ctrl+0 resets.
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            self.root.bind(f"<Control-{key}>", lambda e, dx=dx, dy=dy: self.nudge(dx, dy))
        self.root.bind("<Control-equal>", lambda e: self.set_scale(self.scale_var.get() + 5))
        self.root.bind("<Control-minus>", lambda e: self.set_scale(self.scale_var.get() - 5))
        self.root.bind("<Control-0>", lambda e: self.reset_transform())
        self.root.bind("<Control-m>", lambda e: self.match_original())
        bind_wheel(self.art_canvas, self._on_wheel)
        bind_wheel(self.root, self._on_global_wheel, everywhere=True, add="+")  # sidebar scrolling
        # Left button: the current tool (Move drags the subject, the paint
        # tools paint, Zoom zooms in; double-click with Zoom fits).
        self.art_canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.art_canvas.bind("<B1-Motion>", self._on_drag)
        self.art_canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self.art_canvas.bind("<Double-Button-1>", lambda e: self.tool_var.get() == "zoom" and self.zoom_fit())
        self.art_canvas.bind("<Alt-Button-1>", lambda e: self._zoom_click(e, -1))
        # Right button: erase (paint tools) or zoom out (Zoom).
        self.art_canvas.bind("<ButtonPress-3>", self._on_right_press)
        self.art_canvas.bind("<B3-Motion>", lambda e: self._editing() and self._edit_drag(e))
        self.art_canvas.bind("<ButtonRelease-3>", lambda e: self._editing() and self._edit_release(e))
        # Middle button: pan (when zoomed in past the view), any tool.
        self.art_canvas.bind("<ButtonPress-2>", self._pan_start)
        self.art_canvas.bind("<B2-Motion>", self._pan_move)
        self.art_canvas.bind("<ButtonRelease-2>", self._pan_end)
        self.art_canvas.bind("<Motion>", self._edit_hover, add="+")
        self.art_canvas.bind("<Leave>", lambda e: self.art_canvas.delete("hover"))
        # Undo/redo, and single-letter tool keys (not while typing a name).
        self.root.bind("<Control-z>", lambda e: self._typing(e) or self.undo())
        self.root.bind("<Control-y>", lambda e: self._typing(e) or self.redo())
        self.root.bind("<Control-Z>", lambda e: self._typing(e) or self.redo())  # Ctrl+Shift+Z
        for key, tool in (("m", "move"), ("b", "pen"), ("e", "eraser"), ("g", "fill"), ("G", "gradient"),
                          ("i", "picker"), ("z", "zoom")):  # "G" is Shift+G
            self.root.bind(f"<KeyPress-{key}>", lambda e, t=tool: self._tool_key(e, t))
        # X swaps the gradient's colours (while the Gradient tool is picked).
        self.root.bind("<KeyPress-x>", lambda e: self._typing(e) or self.tool_var.get() != "gradient"
                       or self.swap_gradient_colours())

    @staticmethod
    def _typing(event) -> bool:
        """True when the key went to a text field (e.g. Item name)."""
        return isinstance(event.widget, (tk.Entry, ttk.Entry))

    def _tool_key(self, event, tool):
        if not self._typing(event):
            self.select_tool(tool)

    def _zoom_click(self, event, direction):
        if self.tool_var.get() == "zoom":
            self.zoom_at(event.x, event.y, direction)
            return "break"  # Alt+click: don't also run the plain-click handler

    def _on_right_press(self, event):
        if self.tool_var.get() == "zoom":
            self.zoom_at(event.x, event.y, -1)
        elif self._editing():
            self._edit_press(event, erase=True)

    # ---- events ----------------------------------------------------------

    def _debounce(self, key: str, ms: int, fn):
        """Run fn once, ms after the *last* call - avoids re-rendering on
        every pixel of a window drag or every tick of a slider drag."""
        if key in self._pending:
            self.root.after_cancel(self._pending[key])
        self._pending[key] = self.root.after(ms, lambda: (self._pending.pop(key, None), fn()))

    def _on_slide(self, value):
        n = round(float(value))
        if n != self.colors_var.get():
            self.colors_var.set(n)
            self.colors_label.configure(text=str(n))
            self._debounce("process", 60, self.process)

    def _on_detail(self, value):
        n = round(float(value))
        if n != self.detail_var.get():
            self.detail_var.set(n)
            self.detail_label.configure(text=self._detail_text())
            self._debounce("process", 60, self.process)

    def _detail_text(self):
        return str(self.detail_var.get()) if self.detail_var.get() else "Off"

    def _settings_changed(self):
        self._debounce("process", 10, self.process)

    # ---- background removal method -----------------------------------------

    def _on_bg_method(self):
        if self.bg_method.get() == "ai":
            problem = ai_status()
            if problem:
                self.bg_method.set("plain")
                messagebox.showinfo("Pixel Forge", problem)
                return
            # Removing the background with AI usually means "I want it gone".
            self.transparent_var.set(True)
        self._settings_changed()

    def _start_ai_job(self):
        img = self.original
        if self._ai_job and self._ai_job["image"] is img:
            return  # already working on this image
        job = {"image": img, "done": threading.Event(), "error": None,
               # (the first AI run in a session also loads the model: a different, longer kind of wait)
               "wait": self.waits.begin("ai" if ai_model_loaded() else "ai_first",
                                        "Removing the background with AI...")}
        self._ai_job = job

        def work():
            try:
                find_subject(img, "ai")  # fills the cache process() reads
            except Exception as exc:  # e.g. corrupt model file
                job["error"] = exc
            job["done"].set()

        threading.Thread(target=work, daemon=True).start()
        self._set_status("Removing background with AI...")
        c = self.art_canvas
        c.delete("all")
        self._placeholder(c, "Removing background\nwith AI...")
        self._poll_ai_job(job)

    def _poll_ai_job(self, job):
        # Tk isn't thread-safe, so the worker never touches widgets; the UI
        # thread checks in on it instead.
        if not job["done"].is_set():
            self.root.after(100, lambda: self._poll_ai_job(job))
            return
        if self._ai_job is job:
            self._ai_job = None
        job["wait"].end(record=not job["error"])
        if job["error"]:
            self.bg_method.set("plain")
            messagebox.showerror("Pixel Forge", f"AI background removal failed:\n\n{job['error']}")
        if job["image"] is self.original:  # still the image on screen
            self.process()

    # ---- subject scale & position -----------------------------------------

    def _on_scale(self, value):
        self.set_scale(round(float(value)), from_slider=True)

    def set_scale(self, percent: int, from_slider: bool = False):
        percent = max(50, min(150, percent))
        if percent == self.scale_var.get():
            return
        self.scale_var.set(percent)
        self.size_label.configure(text=f"{percent}%")
        if not from_slider:
            self.size_scale.set(percent)  # keep the slider in sync with wheel/keys
        self._debounce("process", 40, self.process)

    def nudge(self, dx: int, dy: int):
        """Move the subject by whole art pixels (right/down positive)."""
        self.offset[0] += dx
        self.offset[1] += dy
        self._debounce("process", 10, self.process)

    def reset_transform(self):
        self.offset = [0, 0]
        self.set_scale(100)
        self._debounce("process", 10, self.process)

    def _on_view(self):
        """view_var changed ('sprite' / 'edit' / 'game'): show the matching
        tab, and set up the Pixel Art tab for moving the subject (Sprite)
        or painting (Edit)."""
        view = self.view_var.get()
        if view == "game":
            self._select_tab(2)
        else:
            self._art_mode = view
            self._select_tab(1)
            self._show_editor(view == "edit")
            # Drag-to-move only on the sprite itself; in Edit the cursor shows the tool.
            if view == "sprite":
                self.art_canvas.configure(cursor="" if self.original is None else "fleur")
            self._draw_art()
            self._draw_palette()

    def _select_tab(self, index: int):
        if self.notebook.index("current") != index:
            self._changing_tab = True
            self.notebook.select(index)
            self._changing_tab = False

    def _on_tab_changed(self):
        """The user clicked a tab: keep view_var in step (Original leaves it
        as it was - that tab doesn't change what the others show)."""
        if getattr(self, "_changing_tab", False):
            return
        index = self.notebook.index("current")
        if index == 1 and self.view_var.get() != self._art_mode:
            self.view_var.set(self._art_mode)
            self._on_view()
        elif index == 2 and self.view_var.get() != "game":
            self.view_var.set("game")
            self._draw_game()

    def _on_wheel(self, event):
        """Wheel: zoom at the mouse, any tool. Ctrl+wheel with the Move tool
        scales the subject in the grid instead."""
        step = 1 if event.delta > 0 else -1
        if (getattr(event, "state", 0) & 0x4 and self.original is not None
                and self.view_var.get() == "sprite" and not self.texture_mode):
            self.set_scale(self.scale_var.get() + 5 * step)
        else:
            self.zoom_at(event.x, event.y, step)

    def _on_drag_start(self, event):
        if self.tool_var.get() == "zoom":
            self.zoom_at(event.x, event.y, 1)
        elif self._editing():
            self._edit_press(event)
        elif self.original is not None and self.view_var.get() == "sprite":
            self._drag = (event.x, event.y, tuple(self.offset))

    def _on_drag(self, event):
        if self._editing():
            self._edit_drag(event)
            return
        if not self._drag:
            return
        x0, y0, (ox, oy) = self._drag
        # Convert mouse movement to whole art pixels at the current zoom.
        new = [ox + round((event.x - x0) / self._art_k), oy + round((event.y - y0) / self._art_k)]
        if new != self.offset:
            self.offset = new
            self._debounce("process", 15, self.process)

    def _on_drag_end(self, event):
        self._drag = None
        if self._editing():
            self._edit_release(event)

    def pick_line_color(self):
        start = "#%02x%02x%02x" % self._effective_line_color()
        rgb, _ = colorchooser.askcolor(color=start, title="Outline colour", parent=self.root)
        if rgb:
            self._set_line_color(tuple(int(c) for c in rgb))

    def _set_line_color(self, rgb):
        self.line_color = rgb
        self._draw_swatch()
        self._settings_changed()

    def _effective_line_color(self):
        """The colour actually used: the picked one, or the auto colour."""
        if self.line_color:
            return self.line_color
        return auto_line_color(self.small_art) if self.small_art is not None else (24, 16, 32)

    def _draw_swatch(self):
        self.swatch.configure(bg="#%02x%02x%02x" % self._effective_line_color())

    # ---- file handling ---------------------------------------------------

    def open_dialog(self):
        if self.session:  # an edit session is about its one texture
            return
        path = filedialog.askopenfilename(title="Open an image", filetypes=FILE_TYPES)
        if not path:
            return
        size = self._pixel_art_size(path)
        if size:  # small and square: probably pixel art already - ask how to open it
            choice = messagebox.askyesnocancel(
                "Pixel Forge", f"{Path(path).name} is {size}x{size}: it may be pixel art already.\n\n"
                               "Yes: open it as it is (no conversion, pixel for pixel)\n"
                               "No: convert it like any picture")
            if choice is None:
                return
            if choice:
                self.open_as_is(path)
                return
        self.load_image(path)

    AS_IS_ASK = 128  # square pictures up to this size: Open... asks whether to keep them as they are

    @staticmethod
    def _pixel_art_size(path) -> int:
        """The side of a small square picture (up to AS_IS_ASK), else 0."""
        try:
            with Image.open(path) as img:
                w, h = img.size
        except Exception:
            return 0
        return w if w == h <= PixelForgeApp.AS_IS_ASK else 0

    def open_as_is(self, path=None) -> bool:
        """Open a picture that's already pixel art exactly as it is: one
        layer, pixel for pixel, no conversion (Ctrl+Shift+O)."""
        if self.session:
            return False
        if path is None:
            path = filedialog.askopenfilename(title="Open pixel art as it is", filetypes=AS_IS_TYPES)
            if not path:
                return False
        path = Path(path)
        try:
            img = Image.open(path)
            img.seek(0)  # an animation: its first frame
            img = img.convert("RGBA")
        except Exception as exc:
            messagebox.showerror("Pixel Forge", f"Couldn't open that file as an image:\n\n{exc}")
            return False
        w, h = img.size
        if w != h or w > MAX_AS_IS:
            messagebox.showerror("Pixel Forge", f"{path.name} is {w}x{h}. Only square pictures up to "
                                                f"{MAX_AS_IS}x{MAX_AS_IS} open as they are.\n\n"
                                                "Use Open... to convert it into pixel art instead.")
            return False
        if self.has_edits() and not messagebox.askyesno(
                "Pixel Forge", "Opening another image discards your layers and painting.\n\nContinue?"):
            return False
        self.open_texture(path, img)  # (edit_session: one "Texture" layer, generation settings off)
        self.item_name.set(pretty_name(path.stem))
        self.save_btn.configure(state="normal")
        self.save_raw_btn.configure(state="normal")
        self.root.title(f"Pixel Forge - {path.name} (as it is)")
        self._draw_game()
        return True

    def load_image(self, path) -> bool:
        path = Path(path)
        try:
            img = Image.open(path)
            img.load()
        except Exception as exc:  # missing, corrupt, or not really an image
            messagebox.showerror("Pixel Forge", f"Couldn't open that file as an image:\n\n{exc}")
            return False
        if self.has_edits() and not messagebox.askyesno(
                "Pixel Forge", "Opening another image discards your layers and painting.\n\nContinue?"):
            return False
        if self.texture_mode and not self.session:  # the last one was opened as it is
            self.texture_mode = False
            self._enable_generation()
            self.orig_title.configure(text="Source image")
        self.reset_layers()  # layers belong to the old image
        self.zoom, self.pan = None, [0, 0]  # and so does the zoom: start fitted
        self.original, self.source_path, self.region = img, path, None
        self.offset = [0, 0]  # a nudge belongs to the old image; scale is kept
        self.art_canvas.configure(cursor="fleur" if self.view_var.get() == "sprite" else "")
        self._on_tool()
        self.item_name.set(pretty_name(path.stem))
        self.save_btn.configure(state="normal")
        self.save_raw_btn.configure(state="normal")
        self.root.title(f"Pixel Forge - {path.name}")
        self._draw_original()
        self.process()
        return True

    def export_name(self, raw: bool) -> str:
        """File name from the Item name: the sprite is the texture itself
        ('flesh_axe.png'), the enlarged art gets its size appended."""
        tid = texture_id(self.item_name.get())
        return f"{tid}.png" if raw else f"{tid}_{PREVIEW_SIZE}.png"

    def save_dialog(self, raw: bool):
        """Save Art / Save Sprite: straight into the export folder when one
        is set, otherwise ask where."""
        if self.small_art is None:
            return
        if self.export_dir:
            self._save_to_export_dir(raw)
            return
        path = filedialog.asksaveasfilename(
            title="Save raw sprite" if raw else "Save pixel art",
            initialfile=self.export_name(raw), defaultextension=".png", filetypes=[("PNG", "*.png")])
        if path:
            self.save(path, raw)

    def _save_to_export_dir(self, raw: bool):
        folder = self.export_dir
        if not folder.is_dir():
            if messagebox.askyesno("Pixel Forge", f"The export folder no longer exists:\n\n{folder}\n\n"
                                                  "Choose a different folder?"):
                self.choose_export_dir()
                if self.export_dir and self.export_dir.is_dir():
                    self._save_to_export_dir(raw)
            return
        path = folder / self.export_name(raw)
        if path.exists() and path not in self._overwrite_ok:
            # Ask once per file per session; after that re-exports just replace it.
            if not messagebox.askyesno("Pixel Forge", f"{path.name} already exists in\n{folder}\n\nReplace it?"):
                return
            self._overwrite_ok.add(path)
        self.save(path, raw)

    def save(self, path, raw: bool = False) -> bool:
        # What's on screen: every visible layer combined.
        img = self.display_art if raw else self.display_big
        try:
            img.save(path, format="PNG")
        except OSError as exc:
            messagebox.showerror("Pixel Forge", f"Couldn't save the file:\n\n{exc}")
            return False
        self._overwrite_ok.add(Path(path))  # saved by us: re-exporting it needn't ask
        self._set_status(f"Saved {Path(path).name} to {Path(path).parent}")
        return True

    # ---- export folder ------------------------------------------------------

    def choose_export_dir(self):
        folder = filedialog.askdirectory(title="Export folder for Save Art / Save Sprite",
                                         initialdir=str(self.export_dir or Path.home()), mustexist=True)
        if folder:
            self.set_export_dir(Path(folder))

    def set_export_dir(self, folder: Path | None):
        self.export_dir = folder
        if folder:
            self.settings["export_dir"] = str(folder)
        else:
            self.settings.pop("export_dir", None)
        save_settings(self.settings)
        self._show_export_dir()

    def clear_export_dir(self):
        self.set_export_dir(None)

    def open_export_dir(self):
        if self.export_dir and self.export_dir.is_dir():
            open_folder(self.export_dir)  # in Explorer / the file manager

    def _show_export_dir(self):
        """Folder button text: the export folder's own name (shortened if
        long); the full path is in the status after saving."""
        if not self.export_dir:
            self.export_btn.configure(text="Export folder...")  # until one is set, Save asks where
            self.open_dir_btn.configure(state="disabled")
            return
        text = self.export_dir.name or str(self.export_dir)
        if len(text) > 17:
            text = text[:14] + "..."
        self.export_btn.configure(text=text)
        self.open_dir_btn.configure(state="normal" if self.export_dir.is_dir() else "disabled")

    # ---- processing & drawing -------------------------------------------

    def process(self):
        """Re-run the pixelation pipeline with the current settings."""
        if self.original is None or self.texture_mode:  # a texture is edited as-is, never regenerated
            return
        method = self.bg_method.get()
        if method == "ai" and not subject_is_cached(self.original, "ai"):
            # AI removal takes about a second (more on first use while the
            # model loads): run it on a worker thread, then come back here.
            self._start_ai_job()
            return
        if self._convert_job is not None:  # converting already: go again with these settings when it's done
            self._convert_job["again"] = True
            return
        settings = self._settings()
        if self._matched and self._matched[0] is self.original and self._matched[1] == self._key(settings):
            self._apply(self._matched[2], settings, True)  # these exact settings were matched already
            return
        megapixels = self.original.width * self.original.height / 1e6
        expected = self.waits.times.get("convert_per_mp", CONVERT_S_PER_MP) * megapixels
        if expected > CONVERT_ON_THREAD:  # a big picture: off the Tk loop, with a progress bar
            self._convert_on_thread(settings, expected, megapixels)
            return
        started = time.perf_counter()
        result = pixelate_detailed(self.original, **settings)
        self._learn_convert_speed(time.perf_counter() - started, megapixels)
        self._apply(result, settings, False)

    def _learn_convert_speed(self, seconds: float, megapixels: float):
        if megapixels >= 0.25:  # (tiny pictures say little about the speed)
            self.waits.learn("convert_per_mp", seconds / megapixels)

    def _convert_on_thread(self, settings: dict, expected: float, megapixels: float):
        job = {"image": self.original, "settings": settings, "done": threading.Event(), "result": None,
               "error": None, "again": False, "then": None, "seconds": 0.0,
               "wait": self.waits.begin("convert", "Converting the image...", estimate=expected)}
        self._convert_job = job

        def work():
            started = time.perf_counter()
            try:
                job["result"] = pixelate_detailed(job["image"], **job["settings"])
            except Exception as exc:
                job["error"] = exc
            job["seconds"] = time.perf_counter() - started
            job["done"].set()

        threading.Thread(target=work, daemon=True).start()
        self._poll_convert_job(job, megapixels)

    def _poll_convert_job(self, job, megapixels):
        if not job["done"].is_set():
            self.root.after(50, lambda: self._poll_convert_job(job, megapixels))
            return
        self._convert_job = None
        job["wait"].end(record=False)  # (its speed is learnt per megapixel, below)
        if job["error"]:
            messagebox.showerror("Pixel Forge", f"Converting the image failed:\n\n{job['error']}")
            return
        self._learn_convert_speed(job["seconds"], megapixels)
        if job["image"] is not self.original:
            return  # another picture was opened meanwhile
        if job["again"] or self._key(self._settings()) != self._key(job["settings"]):
            self.process()  # the settings changed while it worked: once more with the new ones
        else:
            self._apply(job["result"], job["settings"], False)
        if job["then"]:
            job["then"]()

    def busy(self) -> bool:
        """Something is still working on a thread (tests wait for this)."""
        return any((self._convert_job, self._ai_job, self._match_job, getattr(self, "_bg_job", None)))

    def _settings(self) -> dict:
        """Every pipeline option as currently set in the UI."""
        return dict(
            grid=self.grid_var.get(),
            colors=self.colors_var.get(),
            outline=self.outline_var.get(),
            detail=self.detail_var.get(),
            line_color=self.line_color,
            fit_subject=self.fit_var.get(),
            transparent_bg=self.transparent_var.get(),
            scale=self.scale_var.get() / 100,
            offset=tuple(self.offset),
            background=self.bg_method.get(),
            enhance=self.enhance_var.get(),
        )

    @staticmethod
    def _key(settings: dict) -> tuple:
        return tuple(sorted(settings.items()))

    # ---- Match Original -----------------------------------------------------

    def match_original(self):
        """Run the slower match-the-source pass for the current settings on
        a worker thread (about 0.1 s at 16x16, up to ~1 s at 32x32)."""
        if self.original is None or self.texture_mode or self._ai_job or self._match_job:
            return
        settings = self._settings()
        key = self._key(settings)
        if self._matched and self._matched[0] is self.original and self._matched[1] == key:
            return  # already showing the match for these settings
        job = {"image": self.original, "key": key, "done": threading.Event(), "result": None, "error": None,
               "wait": self.waits.begin("match", "Matching the original...")}
        self._match_job = job

        def work():
            try:
                job["result"] = pixelate_detailed(job["image"], **settings, match_source=True)
            except Exception as exc:
                job["error"] = exc
            job["done"].set()

        threading.Thread(target=work, daemon=True).start()
        self.match_btn.configure(text="Matching...", state="disabled")
        self._poll_match_job(job)

    def _poll_match_job(self, job):
        if not job["done"].is_set():
            self.root.after(50, lambda: self._poll_match_job(job))
            return
        self._match_job = None
        job["wait"].end(record=not job["error"])
        if job["error"]:
            messagebox.showerror("Pixel Forge", f"Matching the original failed:\n\n{job['error']}")
        elif job["image"] is self.original:
            self._matched = (job["image"], job["key"], job["result"])
        self.process()  # shows the match if the settings haven't changed meanwhile

    # ---- showing a result -------------------------------------------------

    def _apply(self, result, settings: dict, matched: bool):
        g, n = settings["grid"], settings["colors"]
        method = settings["background"]
        self.small_art, self.big_art, self.region = result.small, result.large, result.region
        self._last = (result, settings, matched)
        self._sync_layers()  # the live Base layer follows the new sprite
        if not self._match_job:
            self.match_btn.configure(text="Matched ✓" if matched else "Match Original",
                                     state="disabled" if matched else "normal")
        self.art_title.configure(text=f"{g}x{g} sprite  ·  up to {n} colours")
        w, h = self.original.size
        self.orig_title.configure(text=f"Source {w}x{h}  ·  dashed box = area used")  # file name: status bar
        self._draw_original()
        self._draw_art()
        self._draw_palette()
        if not self.line_color:
            self._draw_swatch()  # auto colour follows the image
        self._update_status()

    def _update_status(self):
        """File, sizes and what the pipeline did, under the original."""
        if not self._last or self.original is None:
            return
        result, settings, matched = self._last
        g, method = settings["grid"], settings["background"]
        visible = [c for c in (self.display_art.getcolors(g * g) or []) if c[1][3]]
        w, h = self.original.size
        name = self.source_path.name
        if len(name) > 36:  # long names have no spaces to wrap at
            name = name[:16] + "..." + name[-17:]
        lines = [f"{name}  {w}x{h} -> {g}x{g}, {len(visible)} colors used"]
        if self.scale_var.get() != 100 or self.offset != [0, 0]:
            lines.append(f"Scale {self.scale_var.get()}%, moved {self.offset[0]:+d}, {self.offset[1]:+d} px"
                         "  (Ctrl+0 resets)")
        if matched:
            lines.append("Matched to the original: colours re-fit to the source. "
                         "Change any setting to go back to the live preview.")
        if result.subject_found:
            lines.append("Background removed with AI." if method == "ai"
                         else "Subject found: background separated.")
        elif method == "ai":
            lines.append("The AI couldn't find a subject in this image.")
        elif result.subject_found is False:
            # Outline/fit/transparency all need a subject on a plain background.
            lines.append("No plain background found, so outline, zoom and "
                         "transparency can't apply. Detail lines still work.")
        if self.base_frozen():
            lines.append("Base layer is edited, so settings changes don't update it "
                         "(Edit view: select it, Regenerate).")
        elif len(self.layers) > 1:
            lines.append(f"{len(self.layers)} layers - saving uses them all combined.")
        if self._status_note:  # a one-off note about the last action goes first, once
            lines.insert(0, self._status_note)
            self._status_note = None
        self._set_status("\n".join(lines))

    def _canvas_size(self, canvas):
        return canvas.winfo_width() - 2, canvas.winfo_height() - 2  # minus the 1px border

    def _show(self, key, canvas, img, x, y):
        photo = ImageTk.PhotoImage(img)
        self._photos[key] = photo  # Tk only draws images Python keeps a reference to
        canvas.create_image(x, y, image=photo, anchor="nw")

    def _placeholder(self, canvas, text):
        w, h = self._canvas_size(canvas)
        canvas.create_text(w // 2, h // 2, text=text, fill=MUTED, font=FONT, justify="center")

    def _draw_original(self):
        c = self.orig_canvas
        c.delete("all")
        w, h = self._canvas_size(c)
        if w < 10 or h < 10:
            return
        if self.original is None:
            self._placeholder(c, "Open an image to start\n\nCtrl+O")
            return
        # Fit inside the panel. A smooth filter is right here: this is
        # the photo, not pixel art. Cached per panel size, because this runs
        # on every settings change (the region box moves) and LANCZOS on a
        # big photo isn't free.
        src = self.original
        scale = min(w / src.width, h / src.height)
        fw, fh = max(1, int(src.width * scale)), max(1, int(src.height * scale))
        key = (id(src), fw, fh)
        if self.texture_mode:  # a finished texture: whole-number NEAREST, crisp like the art
            k = max(1, int(scale))
            fw, fh = src.width * k, src.height * k
            key = (id(src), fw, fh)
        if self._orig_view_key != key:
            resample = Image.Resampling.NEAREST if self.texture_mode else Image.Resampling.LANCZOS
            fitted = src.convert("RGBA").resize((fw, fh), resample)
            view = checkerboard(fw, fh, 10).convert("RGBA")
            view.alpha_composite(fitted)
            self._orig_view, self._orig_view_key = view, key
        x0, y0 = (w - fw) // 2 + 1, (h - fh) // 2 + 1
        self._show("orig", c, self._orig_view, x0, y0)
        # Outline the square the pixel art actually comes from.
        if self.region:
            rx0, ry0, rx1, ry1 = (v * scale for v in self.region)
            c.create_rectangle(x0 + rx0, y0 + ry0, x0 + rx1 - 1, y0 + ry1 - 1, outline=CYAN, dash=(6, 4))

    def _draw_art(self):
        c = self.art_canvas
        c.delete("all")
        w, h = self._canvas_size(c)
        if w < 10 or h < 10:
            return
        self._draw_game()  # the Minecraft tab follows the same art (draws only while visible)
        if self.small_art is None:
            self._placeholder(c, "Open an image to start (Ctrl+O)\n\nScroll to zoom  ·  Move tool: drag to move, Ctrl+scroll to scale")
            self.zoom_label.configure(text="")
            return
        self.zoom_label.configure(text=self._zoom_label_text())
        if self._art_mode == "edit":
            self._draw_editor(c, w, h)
            return
        # Scale by a whole-number factor with NEAREST so every art pixel is
        # an identical, perfectly sharp square at any window size or zoom.
        art = self.display_art
        g = art.width
        k, ox, oy = self._art_layout(g, w, h)  # fit or zoomed (+ pan)
        self._art_k = k  # dragging converts mouse pixels to art pixels with this
        self._art_origin = (ox, oy, k)
        big = art.resize((g * k, g * k), Image.Resampling.NEAREST)
        view = checkerboard(big.width, big.height, max(4, k // 2)).convert("RGBA")
        view.alpha_composite(big)
        self._show("art", c, view, ox, oy)

    def _draw_game(self):
        """The Minecraft tab: the sprite as an item (creative tab, slots,
        tooltip, hotbar). Only drawn while its tab is showing."""
        c = self.game_canvas
        if self.notebook.index("current") != 2:
            return
        c.delete("all")
        w, h = self._canvas_size(c)
        if w < 10 or h < 10:
            return
        if self.small_art is None:
            self._placeholder(c, "Open an image to see it\nas a Minecraft item")
            return
        art = self.display_art
        opaque = art.getchannel("A").getextrema()[0] == 255
        room = h - (34 if opaque else 0)  # leave space for the tip below
        # A whole-number GUI scale keeps it crisp; with little room the
        # inventory shows fewer columns/rows so the icon stays readable.
        k, cols, rows = best_fit(w, room, art.width)
        mock = render_inventory(art, self.item_name.get().strip() or "Item", cols=cols, rows=rows)
        big = mock.resize((mock.width * k, mock.height * k), Image.Resampling.NEAREST)
        y = (room - big.height) // 2 + 1
        self._show("game", c, big, (w - big.width) // 2 + 1, y)
        if opaque:
            # A texture with a solid background shows as a square in-game.
            c.create_text(w // 2, y + big.height + 16, fill=MUTED, font=FONT, width=w - 20, justify="center",
                          text="Tip: tick Transparent BG - item textures need transparency, "
                               "or the background shows in-game.")

    PALETTE_ROWS = 4  # at most this many rows of swatches (gradients and big textures have lots)

    def _draw_palette(self):
        c = self.palette_canvas
        c.delete("all")
        self._swatches = []
        if self.display_art is None:
            self.palette_more.configure(text="")
            return
        # Visible colours only: transparent background pixels aren't paint.
        art = self.display_art
        colors = [cc for cc in (art.getcolors(art.width ** 2) or []) if cc[1][3]]
        colors.sort(key=lambda cc: -cc[0])  # most-used first
        size, gap = 16, 3
        per_row = max(1, (c.winfo_width() or 400) // (size + gap))
        shown = colors[: per_row * self.PALETTE_ROWS]
        for i, (_, rgba) in enumerate(shown):
            x, y = (i % per_row) * (size + gap), (i // per_row) * (size + gap)
            c.create_rectangle(x, y, x + size, y + size, outline=BORDER, fill="#%02x%02x%02x" % rgba[:3])
            self._swatches.append((x, y, x + size, y + size, rgba))  # Edit view: click to paint with it
        rows = -(-len(shown) // per_row)
        c.configure(height=max(size, rows * (size + gap)))
        more = len(colors) - len(shown)
        self.palette_more.configure(text=f"+{more} more" if more else "")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def _windows_setup():
    """Before the window exists. Windows: make it crisp on high-DPI screens
    and give it its own taskbar identity (otherwise it shows up as
    'python'). Linux: use the app's own font if it carries one."""
    if sys.platform != "win32":
        use_bundled_fonts(APP_DIR)
        return
    import ctypes
    try:
        # Without this, Windows bitmap-stretches the whole window on scaled
        # displays, which would blur the pixel art.
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def set_window_icons(hwnd: int) -> bool:
    """Give the window the exact 16/32 px frames from forge.ico.

    Tk's iconbitmap makes its icons by smoothly shrinking the biggest frame,
    which blurs pixel art. LoadImage picks the frame that matches the size
    Windows wants (including on scaled displays) so the taskbar, title bar
    and Alt+Tab show crisp pixels.
    """
    if sys.platform != "win32" or not FORGE_ICO.exists():
        return False
    import ctypes
    u32 = ctypes.windll.user32
    u32.LoadImageW.restype = ctypes.c_void_p
    u32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x80
    ok = True
    for which, (w_metric, h_metric) in ((1, (11, 12)), (0, (49, 50))):  # ICON_BIG: SM_CXICON; ICON_SMALL: SM_CXSMICON
        size = (u32.GetSystemMetrics(w_metric), u32.GetSystemMetrics(h_metric))
        icon = u32.LoadImageW(None, str(FORGE_ICO), IMAGE_ICON, size[0], size[1], LR_LOADFROMFILE)
        if icon:
            u32.SendMessageW(hwnd, WM_SETICON, which, icon)
        ok &= bool(icon)
    return ok


def set_taskbar_relaunch(hwnd: int) -> dict:
    """Tell Windows how to re-launch this window when it's pinned.

    The app runs as pythonw.exe, so without this, "Pin to taskbar" on its
    button would pin Python. These window properties make the pin launch
    "Pixel Forge.exe" with the forge icon and name, under the same app ID
    as the running window - so pin and window share one taskbar button.
    Returns what was set (for checking); does nothing off Windows or
    without the launcher.
    """
    if sys.platform != "win32" or not LAUNCHER_EXE.exists():
        return {}
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    def guid(text):
        u = uuid.UUID(text)
        g = GUID(u.fields[0], u.fields[1], u.fields[2])
        g.d4[:] = u.bytes[8:]
        return g

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):  # just enough for a VT_LPWSTR string
        _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.WORD), ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                    ("value", ctypes.c_void_p), ("pad", ctypes.c_void_p)]

    VT_LPWSTR = 31
    appmodel = guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3")  # System.AppUserModel.* property set
    props = {2: f'"{LAUNCHER_EXE}"',             # RelaunchCommand
             3: f"{FORGE_ICO},0",                # RelaunchIconResource
             4: "Pixel Forge",                   # RelaunchDisplayNameResource
             5: APP_ID}                          # ID - set last; Windows needs it for the others to count
    store = ctypes.c_void_p()
    iid = guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")  # IPropertyStore
    if ctypes.windll.shell32.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd), ctypes.byref(iid), ctypes.byref(store)):
        return {}
    vtable = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    set_value = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                   ctypes.POINTER(PROPVARIANT))(vtable[6])
    commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtable[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    done = {}
    try:
        for pid, text in props.items():
            buffer = ctypes.create_unicode_buffer(text)  # SetValue copies it
            value = PROPVARIANT(VT_LPWSTR, 0, 0, 0, ctypes.cast(buffer, ctypes.c_void_p), None)
            set_value(store, ctypes.byref(PROPERTYKEY(appmodel, pid)), ctypes.byref(value))
            done[pid] = text
        commit(store)
    except OSError:
        pass  # a COM error: the app still works, pinning just falls back to Python
    finally:
        release(store)
    return done


def _test_action(app, action: str):
    """PIXEL_FORGE_TEST_ACTION, for the calling app's automated tests:
    'save' (unchanged; converting, the art as it first appears), 'paint-save'
    (paint the top-left pixel magenta, then save), 'remove-bg-save' /
    'remove-bg-ai-save' (Remove BG Plain / AI on the texture, then save),
    'cancel'."""
    if app.busy():  # a big picture still converting (or the AI working): act once it's done
        app.root.after(100, lambda: _test_action(app, action))
        return
    if action in ("remove-bg-save", "remove-bg-ai-save") and not app.texture_mode:
        app.session_save()  # Remove BG as a button is the texture panel's: converting has its own
        return
    if action in ("remove-bg-save", "remove-bg-ai-save"):
        app.remove_texture_background("ai" if action == "remove-bg-ai-save" else "plain")

        def save_when_done():  # AI finishes on a worker thread
            if app._bg_job is not None:
                app.root.after(100, save_when_done)
            else:
                app.session_save()
        save_when_done()
        return
    if action == "paint-save":
        app._snapshot()
        app.layers[app.active_layer].image.putpixel((0, 0), (255, 0, 255, 255))
        app._layers_changed()
    if action in ("save", "paint-save"):
        app.session_save()
    elif action == "cancel":
        app.session_cancel()


def main():
    args = parse_args()
    if args.describe:  # the calling app asks what this Pixel Forge supports
        write_result(args.result, DESCRIPTION)
        if sys.stdout:  # None under pythonw
            print(json.dumps(DESCRIPTION))
        sys.exit(0)
    hidden = os.environ.get("PIXEL_FORGE_HIDDEN") == "1"  # never shown: automated runs
    _windows_setup()
    root = tk.Tk()
    if hidden:
        root.withdraw()
    try:
        app = PixelForgeApp(root)
        root.update_idletasks()  # the window must exist before setting its taskbar properties
        hwnd = int(root.wm_frame(), 16)
        set_window_icons(hwnd)
        set_taskbar_relaunch(hwnd)
        if args.edit:  # Grass Block (or another app) wants one texture edited, or made from a picture
            session = {"path": args.edit, "name": args.name, "result": args.result, "caller": args.caller,
                       "source": args.source, "transparent": args.transparent}
            doing = (f"new {Path(args.edit).name} from {Path(args.source).name}" if args.source
                     else f"editing {Path(args.edit).name}")
            root.title(f"Pixel Forge - {doing} for {args.caller}")
            if app.start_session(session):
                action = os.environ.get("PIXEL_FORGE_TEST_ACTION")
                if action:
                    root.after(200, lambda: _test_action(app, action))
        elif args.image:  # e.g. "Open with" or drag onto the launcher
            root.after(100, lambda: app.load_image(args.image))
        root.mainloop()
    except Exception:
        if args.edit:  # the caller is waiting: tell it, then fail
            write_result(args.result, {"status": "error", "message": traceback.format_exc(limit=3)})
        # Launched with pythonw there is no console, so surface crashes.
        if not hidden:
            messagebox.showerror("Pixel Forge crashed", traceback.format_exc())
        sys.exit(EXIT_ERROR)
    sys.exit(app.exit_code)


if __name__ == "__main__":
    main()
